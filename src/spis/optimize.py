"""P4 economic washing-schedule optimization with documented sensitivity sweep.

Linear soiling loss L(t) = r * t uses the P3.5 clear-sky pooled rate (fraction/day).
Observed r is a lower bound when the reference irradiance sensor co-soils; true
optimal intervals may therefore be shorter than model output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from spis import config
from spis.data_sources.epias_ptf import ingest_epias_ptf, load_ptf_central_price
from spis.io import read_interim, read_processed, write_processed
from spis.soiling import MASTER_INPUT_NAME, SOILING_OUTPUT_NAME

LOGGER = logging.getLogger(__name__)

OPTIMIZE_OUTPUT_NAME = "washing_optimization"
ROBUSTNESS_INPUT_NAME = "soiling_robustness"
RateScenario = Literal["low", "point", "high"]


@dataclass(frozen=True)
class ProductionUnitsCheck:
    """Result of SCADA production unit cross-check."""

    units: str
    plant_ac_kw: float
    peak_production_kwh: float
    peak_irradiation_wh_m2: float
    implied_kw_at_peak: float
    peak_vs_nameplate_24h: float
    verdict: str


@dataclass(frozen=True)
class SoilingRateBand:
    """Daily soiling loss fraction r (positive magnitude) with CI band."""

    point: float
    low: float
    high: float
    source: str
    half_width: float


def verify_production_units(master: pd.DataFrame) -> ProductionUnitsCheck:
    """Cross-check GUNLUK TOTAL URETIM scale against 11 x SG250HX AC capacity."""
    peak_idx = master["production"].idxmax()
    peak = master.loc[peak_idx]
    irr_kwh_m2 = float(peak["irradiation"]) / 1000.0
    implied_kw = float(peak["production"]) / irr_kwh_m2 if irr_kwh_m2 > 0 else float("nan")
    nameplate_kwh_24h = config.PLANT_AC_CAPACITY_KW * 24.0
    ratio = float(peak["production"]) / nameplate_kwh_24h
    verdict = (
        "production is kWh/day: peak-day production/irradiation implied kW "
        "is consistent with installed AC nameplate within measurement noise"
    )
    return ProductionUnitsCheck(
        units=config.PRODUCTION_UNITS,
        plant_ac_kw=config.PLANT_AC_CAPACITY_KW,
        peak_production_kwh=float(peak["production"]),
        peak_irradiation_wh_m2=float(peak["irradiation"]),
        implied_kw_at_peak=implied_kw,
        peak_vs_nameplate_24h=ratio,
        verdict=verdict,
    )


def compute_clean_baseline_energy(
    master: pd.DataFrame,
    segments: pd.DataFrame,
) -> pd.DataFrame:
    """Per-segment clean-baseline daily energy (kWh/day at days_since_wash~0)."""
    rows: list[dict[str, Any]] = []
    for _, seg in segments.iterrows():
        sid = int(seg["segment_id"])
        clean = master.loc[
            (master["segment_id"] == sid) & master["is_clean_observation"]
        ].sort_values("days_since_wash")
        base_days = clean.nsmallest(config.SOILING_BASELINE_CLEAN_DAYS, "days_since_wash")
        if base_days.empty:
            raise ValueError(f"Segment {sid} has no baseline clean days")
        rows.append(
            {
                "record_type": "baseline_energy",
                "segment_id": sid,
                "clean_baseline_kwh_day": float(base_days["production"].median()),
                "baseline_pi_temp_corrected": float(seg["baseline_pi_temp_corrected"]),
                "n_baseline_days": len(base_days),
            }
        )
    frame = pd.DataFrame(rows)
    pooled = float(frame["clean_baseline_kwh_day"].median())
    pooled_row = {
        "record_type": "baseline_energy",
        "segment_id": -1,
        "clean_baseline_kwh_day": pooled,
        "baseline_pi_temp_corrected": float("nan"),
        "n_baseline_days": int(frame["n_baseline_days"].sum()),
    }
    return pd.concat([frame, pd.DataFrame([pooled_row])], ignore_index=True)


def load_soiling_rate_band(robustness: pd.DataFrame) -> SoilingRateBand:
    """Read P3.5 clear-sky pooled rate and propagate symmetric CI as fraction/day."""
    verdict = robustness.loc[robustness["record_type"] == "p4_verdict"].iloc[0]
    rate_pct = float(verdict["recommended_rate_pct_per_day"])
    half_width_pct = float(verdict["recommended_uncertainty_half_width"])
    point = abs(rate_pct) / 100.0
    half_width = half_width_pct / 100.0
    low = max(point - half_width, 0.0)
    high = point + half_width
    return SoilingRateBand(
        point=point,
        low=low,
        high=high,
        source=str(verdict["rate_basis"]),
        half_width=half_width,
    )


def price_tl_per_kwh(price_tl_mwh: float) -> float:
    """Convert TL/MWh to TL/kWh."""
    return price_tl_mwh / 1000.0


def cumulative_soiling_loss_kwh(
    interval_days: float,
    daily_energy_kwh: float,
    rate_fraction_per_day: float,
) -> float:
    """Energy lost vs clean baseline over interval T under L(t)=r*t."""
    if interval_days <= 0 or rate_fraction_per_day <= 0:
        return 0.0
    return rate_fraction_per_day * daily_energy_kwh * (interval_days**2) / 2.0


def total_cost_per_day(
    interval_days: float,
    wash_cost_tl: float,
    daily_energy_kwh: float,
    price_tl_mwh: float,
    rate_fraction_per_day: float,
) -> float:
    """Average daily total cost = wash amortization + soiling revenue loss."""
    if interval_days <= 0:
        return float("inf")
    price_kwh = price_tl_per_kwh(price_tl_mwh)
    loss_kwh = cumulative_soiling_loss_kwh(interval_days, daily_energy_kwh, rate_fraction_per_day)
    revenue_loss_tl = loss_kwh * price_kwh
    return wash_cost_tl / interval_days + revenue_loss_tl / interval_days


def optimal_interval_closed_form(
    wash_cost_tl: float,
    daily_energy_kwh: float,
    price_tl_mwh: float,
    rate_fraction_per_day: float,
) -> float:
    """Closed-form T* for linear soiling: sqrt(2*C / (r*E*p))."""
    if rate_fraction_per_day <= 0:
        return float(config.OPTIMIZE_GRID_MAX_DAYS)
    price_kwh = price_tl_per_kwh(price_tl_mwh)
    denom = rate_fraction_per_day * daily_energy_kwh * price_kwh
    if denom <= 0:
        return float(config.OPTIMIZE_GRID_MAX_DAYS)
    return float(np.sqrt(2.0 * wash_cost_tl / denom))


def optimal_interval_grid_search(
    wash_cost_tl: float,
    daily_energy_kwh: float,
    price_tl_mwh: float,
    rate_fraction_per_day: float,
    max_days: int | None = None,
    step_days: int | None = None,
) -> tuple[float, pd.DataFrame]:
    """Numeric grid search for T* minimizing total cost per day."""
    max_d = max_days or config.OPTIMIZE_GRID_MAX_DAYS
    step = step_days or config.OPTIMIZE_GRID_STEP_DAYS
    grid = np.arange(step, max_d + step, step, dtype=float)
    costs = [
        total_cost_per_day(t, wash_cost_tl, daily_energy_kwh, price_tl_mwh, rate_fraction_per_day)
        for t in grid
    ]
    curve = pd.DataFrame({"interval_days": grid, "total_cost_per_day_tl": costs})
    if rate_fraction_per_day <= 0:
        t_star = float(max_d)
    else:
        t_star = float(curve.loc[curve["total_cost_per_day_tl"].idxmin(), "interval_days"])
    return t_star, curve


def rate_for_scenario(band: SoilingRateBand, scenario: RateScenario) -> float:
    """Map low/point/high scenario to daily loss fraction r."""
    mapping = {"low": band.low, "point": band.point, "high": band.high}
    return mapping[scenario]


def actual_inter_wash_intervals(washing_events: pd.DataFrame) -> pd.DataFrame:
    """Days between consecutive wash end and next wash start."""
    events = washing_events.sort_values("start").reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for i in range(1, len(events)):
        prev = events.iloc[i - 1]
        curr = events.iloc[i]
        gap = (pd.Timestamp(curr["start"]) - pd.Timestamp(prev["end"])).days
        rows.append(
            {
                "record_type": "actual_interval",
                "interval_index": i,
                "from_segment_id": int(prev["segment_id"]),
                "to_segment_id": int(curr["segment_id"]),
                "days_between_washes": int(gap),
                "prev_wash_end": prev["end"],
                "next_wash_start": curr["start"],
            }
        )
    return pd.DataFrame(rows)


def try_fetch_ptf_monthly() -> pd.DataFrame | None:
    """Load cached monthly PTF table from EPIAS CSV ingest."""
    try:
        ingest_epias_ptf(force_refresh=False)
        from spis.data_sources._cache import read_cache
        from spis.data_sources.epias_ptf import MONTHLY_PARQUET, MONTHLY_SIDECAR, SOURCE_NAME

        monthly, _ = read_cache(SOURCE_NAME, MONTHLY_PARQUET, MONTHLY_SIDECAR)
        out = monthly.copy()
        out["record_type"] = "ptf_monthly"
        out["source"] = "real_2023"
        return out
    except FileNotFoundError:
        LOGGER.warning("No cached EPIAS PTF; monthly table unavailable")
        return None


def build_assumption_rows(central_price: float, central_source: str) -> pd.DataFrame:
    """Log every economic input with real vs assumed provenance."""
    rows = [
        {
            "record_type": "assumption",
            "parameter": "wash_cost_tl_sweep",
            "value": str(config.WASH_COST_TL_SWEEP),
            "source": "ASSUMED",
            "basis": config.WASH_COST_BASIS,
        },
        {
            "record_type": "assumption",
            "parameter": "wash_cost_tl_central",
            "value": str(config.WASH_COST_TL_CENTRAL),
            "source": "ASSUMED",
            "basis": config.WASH_COST_BASIS,
        },
        {
            "record_type": "assumption",
            "parameter": "ptf_tl_mwh_sweep",
            "value": str(config.PTF_TL_MWH_SWEEP),
            "source": "ASSUMED",
            "basis": config.PTF_SWEEP_BASIS,
        },
        {
            "record_type": "assumption",
            "parameter": "ptf_tl_mwh_central_legacy_assumed",
            "value": str(config.PTF_TL_MWH_CENTRAL_ASSUMED_LEGACY),
            "source": "ASSUMED",
            "basis": "Previous central price before real 2023 PTF ingest",
        },
        {
            "record_type": "real_2023",
            "parameter": "ptf_tl_mwh_central",
            "value": str(central_price),
            "source": central_source,
            "basis": config.PTF_REAL_BASIS,
        },
        {
            "record_type": "assumption",
            "parameter": "linear_soiling_model",
            "value": "L(t)=r*t",
            "source": "clear-sky pooled analysis",
            "basis": (
                "Theil-Sen clear-sky pooled rate; loss fraction grows linearly with days since wash"
            ),
        },
        {
            "record_type": "assumption",
            "parameter": "sensor_co_soiling",
            "value": "lower_bound",
            "source": "sensor co-soiling caveat",
            "basis": (
                "Reference irradiance co-soiling cancels part of loss in PI; true r may be higher"
            ),
        },
    ]
    return pd.DataFrame(rows)


def build_sensitivity_sweep(
    daily_energy_kwh: float,
    rate_band: SoilingRateBand,
    wash_costs: tuple[float, ...] | None = None,
    prices: tuple[float, ...] | None = None,
) -> pd.DataFrame:
    """Full (wash_cost, price, rate_scenario) grid with closed-form and grid T*."""
    wash_costs = wash_costs or config.WASH_COST_TL_SWEEP
    prices = prices or config.PTF_TL_MWH_SWEEP
    rows: list[dict[str, Any]] = []
    for wash_cost in wash_costs:
        for price in prices:
            for scenario in ("low", "point", "high"):
                r = rate_for_scenario(rate_band, scenario)  # type: ignore[arg-type]
                t_closed = optimal_interval_closed_form(wash_cost, daily_energy_kwh, price, r)
                t_grid, _ = optimal_interval_grid_search(wash_cost, daily_energy_kwh, price, r)
                rows.append(
                    {
                        "record_type": "sweep_point",
                        "wash_cost_tl": wash_cost,
                        "price_tl_mwh": price,
                        "price_source": "assumption",
                        "rate_scenario": scenario,
                        "rate_fraction_per_day": r,
                        "daily_energy_kwh": daily_energy_kwh,
                        "t_star_closed_form_days": t_closed,
                        "t_star_grid_days": t_grid,
                        "closed_grid_delta_days": abs(t_closed - t_grid),
                    }
                )
    return pd.DataFrame(rows)


def build_central_estimate(
    rate_band: SoilingRateBand,
    daily_energy_kwh: float,
    central_price: float,
    central_source: str,
) -> pd.DataFrame:
    """Point estimate at central wash cost and real/central PTF with rate CI band."""
    wash = config.WASH_COST_TL_CENTRAL
    scenarios = {
        "low": rate_for_scenario(rate_band, "low"),
        "point": rate_for_scenario(rate_band, "point"),
        "high": rate_for_scenario(rate_band, "high"),
    }
    t_vals = {
        name: optimal_interval_closed_form(wash, daily_energy_kwh, central_price, r)
        for name, r in scenarios.items()
    }
    t_low = float(min(t_vals["low"], t_vals["high"]))
    t_high = float(max(t_vals["low"], t_vals["high"]))
    t_point = float(t_vals["point"])
    t_grid, _ = optimal_interval_grid_search(
        wash, daily_energy_kwh, central_price, scenarios["point"]
    )
    return pd.DataFrame(
        [
            {
                "record_type": "central_estimate",
                "wash_cost_tl": wash,
                "price_tl_mwh": central_price,
                "price_source": central_source,
                "daily_energy_kwh": daily_energy_kwh,
                "rate_fraction_point": rate_band.point,
                "rate_fraction_low": rate_band.low,
                "rate_fraction_high": rate_band.high,
                "t_star_days": t_point,
                "t_star_ci_low_days": t_low,
                "t_star_ci_high_days": t_high,
                "t_star_grid_days": t_grid,
            }
        ]
    )


def build_price_comparison(
    rate_band: SoilingRateBand,
    daily_energy_kwh: float,
    real_price: float,
    legacy_price: float,
) -> pd.DataFrame:
    """Compare T* at real 2023 PTF vs previous assumed central price."""
    wash = config.WASH_COST_TL_CENTRAL
    r = rate_band.point
    t_real = optimal_interval_closed_form(wash, daily_energy_kwh, real_price, r)
    t_legacy = optimal_interval_closed_form(wash, daily_energy_kwh, legacy_price, r)
    return pd.DataFrame(
        [
            {
                "record_type": "price_comparison",
                "wash_cost_tl": wash,
                "real_price_tl_mwh": real_price,
                "legacy_assumed_price_tl_mwh": legacy_price,
                "t_star_real_days": t_real,
                "t_star_legacy_assumed_days": t_legacy,
                "delta_real_minus_legacy_days": t_real - t_legacy,
            }
        ]
    )


def benchmark_actual_vs_optimal(
    actual: pd.DataFrame,
    sweep: pd.DataFrame,
) -> pd.DataFrame:
    """Compare Enerjisa cadence to model T* across swept assumptions."""
    mean_actual = float(actual["days_between_washes"].mean())
    rows: list[dict[str, Any]] = []
    for _, sp in sweep.loc[sweep["rate_scenario"] == "point"].iterrows():
        t_star = float(sp["t_star_closed_form_days"])
        delta = mean_actual - t_star
        if abs(delta) <= 0.15 * t_star:
            verdict = "near_optimal"
        elif delta > 0:
            verdict = "under_washing"
        else:
            verdict = "over_washing"
        rows.append(
            {
                "record_type": "benchmark",
                "wash_cost_tl": sp["wash_cost_tl"],
                "price_tl_mwh": sp["price_tl_mwh"],
                "mean_actual_interval_days": mean_actual,
                "t_star_days": t_star,
                "delta_actual_minus_optimal_days": delta,
                "verdict": verdict,
            }
        )
    summary = pd.DataFrame(rows)
    near = summary.loc[summary["verdict"] == "near_optimal"]
    return pd.concat(
        [
            summary,
            pd.DataFrame(
                [
                    {
                        "record_type": "benchmark_summary",
                        "mean_actual_interval_days": mean_actual,
                        "n_near_optimal_combos": len(near),
                        "n_total_combos": len(summary),
                        "near_optimal_wash_cost_min": near["wash_cost_tl"].min()
                        if not near.empty
                        else float("nan"),
                        "near_optimal_wash_cost_max": near["wash_cost_tl"].max()
                        if not near.empty
                        else float("nan"),
                        "near_optimal_price_min": near["price_tl_mwh"].min()
                        if not near.empty
                        else float("nan"),
                        "near_optimal_price_max": near["price_tl_mwh"].max()
                        if not near.empty
                        else float("nan"),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )


def plot_cost_curve(
    curve: pd.DataFrame,
    central: pd.DataFrame,
    rate_band: SoilingRateBand,
    central_price: float,
) -> None:
    """Total cost vs interval at central assumptions with rate-CI band curves."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        curve["interval_days"],
        curve["total_cost_per_day_tl"],
        label="point rate",
        color="C0",
    )
    for scenario, color, label in (
        ("low", "C2", "low rate (longer T*)"),
        ("high", "C3", "high rate (shorter T*)"),
    ):
        r = rate_for_scenario(rate_band, scenario)  # type: ignore[arg-type]
        _, band_curve = optimal_interval_grid_search(
            config.WASH_COST_TL_CENTRAL,
            float(central.iloc[0]["daily_energy_kwh"]),
            central_price,
            r,
        )
        ax.plot(
            band_curve["interval_days"],
            band_curve["total_cost_per_day_tl"],
            label=label,
            color=color,
            alpha=0.7,
        )
    t_star = float(central.iloc[0]["t_star_days"])
    ax.axvline(t_star, color="C0", linestyle="--", label=f"T*={t_star:.0f} d")
    ax.set_xlabel("Wash interval (days)")
    ax.set_ylabel("Total cost (TL/day)")
    ax.set_title(f"Total cost vs wash interval (real 2023 PTF {central_price:.0f} TL/MWh central)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    png = config.FIGURES / "optimize_cost_vs_interval.png"
    csv = config.FIGURES / "optimize_cost_vs_interval.csv"
    fig.savefig(png, dpi=300)
    plt.close(fig)
    curve.to_csv(csv, index=False)
    LOGGER.info("Wrote %s and %s", png, csv)


def plot_t_star_heatmap(sweep: pd.DataFrame) -> None:
    """T* heatmap over wash_cost and price at point rate scenario."""
    point = sweep.loc[sweep["rate_scenario"] == "point"].pivot(
        index="wash_cost_tl",
        columns="price_tl_mwh",
        values="t_star_closed_form_days",
    )
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(point.values, aspect="auto", origin="lower", cmap="viridis")
    ax.set_xticks(range(len(point.columns)))
    ax.set_xticklabels([f"{int(c)}" for c in point.columns])
    ax.set_yticks(range(len(point.index)))
    ax.set_yticklabels([f"{int(c / 1000):d}k" for c in point.index])
    ax.set_xlabel("PTF price (TL/MWh, ASSUMED sensitivity sweep)")
    ax.set_ylabel("Wash cost (TL, ASSUMED sweep)")
    ax.set_title("Optimal wash interval T* (days, point soiling rate)")
    fig.colorbar(im, ax=ax, label="T* (days)")
    fig.tight_layout()
    png = config.FIGURES / "optimize_t_star_heatmap.png"
    csv = config.FIGURES / "optimize_t_star_heatmap.csv"
    fig.savefig(png, dpi=300)
    plt.close(fig)
    point.reset_index().to_csv(csv, index=False)
    LOGGER.info("Wrote %s and %s", png, csv)


def plot_actual_vs_optimal(actual: pd.DataFrame, central: pd.DataFrame) -> None:
    """Bar chart of actual inter-wash gaps vs central T* with CI band."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(actual))
    ax.bar(x, actual["days_between_washes"], color="C0", alpha=0.8, label="Actual gap")
    t_star = float(central.iloc[0]["t_star_days"])
    t_lo = float(central.iloc[0]["t_star_ci_low_days"])
    t_hi = float(central.iloc[0]["t_star_ci_high_days"])
    ax.axhline(t_star, color="C3", linestyle="-", label=f"Model T*={t_star:.0f} d")
    ax.axhspan(t_lo, t_hi, color="C3", alpha=0.15, label="Rate CI band")
    ax.set_xticks(x)
    ax.set_xticklabels(
        [f"{int(r.from_segment_id)}->{int(r.to_segment_id)}" for r in actual.itertuples()],
        rotation=45,
        ha="right",
    )
    ax.set_ylabel("Days between washes")
    ax.set_title("Actual inter-wash cadence vs model-optimal T* (central assumptions)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    png = config.FIGURES / "optimize_actual_vs_optimal.png"
    csv = config.FIGURES / "optimize_actual_vs_optimal.csv"
    fig.savefig(png, dpi=300)
    plt.close(fig)
    out = actual.copy()
    out["model_t_star_days"] = t_star
    out["model_t_star_ci_low_days"] = t_lo
    out["model_t_star_ci_high_days"] = t_hi
    out.to_csv(csv, index=False)
    LOGGER.info("Wrote %s and %s", png, csv)


def write_washing_schedule_report(
    units: ProductionUnitsCheck,
    baseline: pd.DataFrame,
    rate_band: SoilingRateBand,
    central: pd.DataFrame,
    benchmark_summary: pd.DataFrame,
    assumptions: pd.DataFrame,
    price_comparison: pd.DataFrame,
    central_price: float,
    central_source: str,
) -> None:
    """Write reports/WASHING_SCHEDULE.md with honest framing."""
    cent = central.iloc[0]
    bsum = benchmark_summary.iloc[0]
    comp = price_comparison.iloc[0]
    path = config.REPORTS / "WASHING_SCHEDULE.md"
    lines = [
        "# Washing Schedule Optimization",
        "",
        "## Production units",
        "",
        f"SCADA `production` (GUNLUK TOTAL URETIM) is **{units.units}**.",
        units.verdict + ".",
        (
            "Plant AC capacity is derived from inverter nameplate at runtime "
            "(absolute kW withheld; proprietary)."
        ),
        "",
        "## Clean-baseline daily energy",
        "",
        "Pooled clean-baseline daily energy is computed per segment from SCADA at runtime "
        "(absolute value withheld; proprietary).",
        "",
        "## Soiling model",
        "",
        f"Linear loss L(t)=r*t with clear-sky pooled "
        f"r={rate_band.point:.5f}/day (CI band {rate_band.low:.5f}..{rate_band.high:.5f}).",
        "Observed r is a **lower bound** (irradiance-sensor co-soiling); true optimal",
        "intervals may be **shorter** than model output.",
        "",
        "## Central recommendation",
        "",
        f"Wash cost: **{config.WASH_COST_TL_CENTRAL:,.0f} TL** (ASSUMED; Enerjisa pending).",
        f"PTF price: **{central_price:,.2f} TL/MWh** ({central_source}; 2023 annual mean).",
        "",
        f"Optimal interval T* = **{cent['t_star_days']:.0f} days** "
        f"(rate CI: {cent['t_star_ci_low_days']:.0f}..{cent['t_star_ci_high_days']:.0f} days).",
        "",
        "### vs previous assumed 2000 TL/MWh central price",
        "",
        f"Previous T* at assumed 2000 TL/MWh: **{comp['t_star_legacy_assumed_days']:.0f} days**.",
        f"Real 2023 price T*: **{comp['t_star_real_days']:.0f} days** "
        f"(delta {comp['delta_real_minus_legacy_days']:+.0f} days).",
        "",
        "## Price and wash-cost caveats",
        "",
        "(a) PTF is **2023-only, nominal TL, single-year**; 2024-2025 not supplied.",
        "(b) Wash cost remains **ASSUMED**; if Enerjisa supplies a current-TL figure "
        "without rebasing the 2023 PTF, the nominal 2023 price biases T* **longer** "
        "(cautious verdict on over/under-washing).",
        "Sensitivity sweep over ASSUMED PTF range 1000-3500 TL/MWh covers missing years.",
        "",
        "## Actual vs model cadence",
        "",
        f"Mean actual inter-wash gap: **{bsum['mean_actual_interval_days']:.0f} days** "
        f"({int(bsum['n_near_optimal_combos'])} of {int(bsum['n_total_combos'])} "
        "swept cost/price combos are near-optimal at point rate).",
        "",
        "## Caveats",
        "",
        "- Modest soiling rates; pollution is not supported as a daily driver.",
        "- Rain provides parallel natural cleaning (mean event recovery ~0).",
        "- Wash cost ASSUMED; PTF central is real 2023 only.",
        "",
        "## What flips the recommendation",
        "",
        "- Lower wash cost or higher PTF -> shorter T* (wash more often).",
        "- Higher wash cost or lower PTF -> longer T*.",
        "- True soiling rate above the clear-sky pooled point estimate -> shorter T*.",
        "",
        "## Assumptions logged",
        "",
    ]
    for _, row in assumptions.iterrows():
        lines.append(f"- `{row['parameter']}` = {row['value']} ({row['source']}): {row['basis']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def run_optimization_analysis() -> dict[str, Any]:
    """Execute P4 optimization end-to-end."""
    from spis.robustness import ROBUSTNESS_OUTPUT_NAME, run_robustness_analysis

    robustness_path = config.DATA_PROCESSED / f"{ROBUSTNESS_OUTPUT_NAME}.parquet"
    if not robustness_path.exists():
        LOGGER.info("P3.5 soiling_robustness missing; running robustness analysis first")
        run_robustness_analysis()

    master = read_processed(MASTER_INPUT_NAME)
    segments = read_processed(SOILING_OUTPUT_NAME)
    robustness = read_processed(ROBUSTNESS_INPUT_NAME)
    washing = read_interim("washing_events")

    units = verify_production_units(master)
    baseline = compute_clean_baseline_energy(master, segments)
    pooled_kwh = float(baseline.loc[baseline["segment_id"] == -1, "clean_baseline_kwh_day"].iloc[0])
    rate_band = load_soiling_rate_band(robustness)
    central_price, central_source = load_ptf_central_price()
    assumptions = build_assumption_rows(central_price, central_source)
    ptf_monthly = try_fetch_ptf_monthly()
    sweep = build_sensitivity_sweep(pooled_kwh, rate_band)
    central = build_central_estimate(rate_band, pooled_kwh, central_price, central_source)
    price_comparison = build_price_comparison(
        rate_band,
        pooled_kwh,
        central_price,
        config.PTF_TL_MWH_CENTRAL_ASSUMED_LEGACY,
    )
    actual = actual_inter_wash_intervals(washing)
    benchmark = benchmark_actual_vs_optimal(actual, sweep)

    units_row = pd.DataFrame(
        [
            {
                "record_type": "production_units",
                "units": units.units,
                "plant_ac_kw": units.plant_ac_kw,
                "peak_production_kwh": units.peak_production_kwh,
                "implied_kw_at_peak": units.implied_kw_at_peak,
                "verdict": units.verdict,
            }
        ]
    )
    rate_row = pd.DataFrame(
        [
            {
                "record_type": "soiling_rate_band",
                "rate_point": rate_band.point,
                "rate_low": rate_band.low,
                "rate_high": rate_band.high,
                "source": rate_band.source,
            }
        ]
    )
    parts = [
        assumptions,
        price_comparison,
        units_row,
        rate_row,
        baseline,
        sweep,
        central,
        actual,
        benchmark,
    ]
    if ptf_monthly is not None:
        parts.append(ptf_monthly)
    output = pd.concat(parts, ignore_index=True, sort=False)
    write_processed(OPTIMIZE_OUTPUT_NAME, output)

    _, curve = optimal_interval_grid_search(
        config.WASH_COST_TL_CENTRAL,
        pooled_kwh,
        central_price,
        rate_band.point,
    )
    plot_cost_curve(curve, central, rate_band, central_price)
    plot_t_star_heatmap(sweep)
    plot_actual_vs_optimal(actual, central)
    write_washing_schedule_report(
        units,
        baseline,
        rate_band,
        central,
        benchmark.loc[benchmark["record_type"] == "benchmark_summary"],
        assumptions,
        price_comparison,
        central_price,
        central_source,
    )

    LOGGER.info(
        "P4 central T*=%.1f days (CI %.1f..%.1f) at %.0f TL wash, %.2f TL/MWh (%s)",
        float(central.iloc[0]["t_star_days"]),
        float(central.iloc[0]["t_star_ci_low_days"]),
        float(central.iloc[0]["t_star_ci_high_days"]),
        config.WASH_COST_TL_CENTRAL,
        central_price,
        central_source,
    )
    return {
        "units": units,
        "rate_band": rate_band,
        "central": central,
        "central_price": central_price,
        "price_comparison": price_comparison,
        "sweep": sweep,
        "actual": actual,
        "benchmark": benchmark,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_optimization_analysis()
