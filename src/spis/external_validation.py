"""P14 external-site validation: DKASC Alice Springs vs Canakkale."""

from __future__ import annotations

import logging
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from spis import config
from spis.clean import (
    MASTER_OUTPUT_NAME,
    add_quality_flags,
    compute_low_irradiation_cutoff,
    join_external,
    join_washing_segments,
)
from spis.data_sources.dkasc import load_dkasc_daily
from spis.data_sources.nasa_power import fetch_nasa_power_daily, validate_nasa_power
from spis.data_sources.open_meteo_aq import fetch_open_meteo_air_quality, validate_open_meteo_aq
from spis.io import read_processed, write_processed
from spis.robustness import (
    ROBUSTNESS_OUTPUT_NAME,
    attach_clearness_index,
    build_daily_residual_frame,
    compare_clear_sky_slopes,
    pollution_daily_tests,
)
from spis.sites import get_site
from spis.soiling import (
    SOILING_OUTPUT_NAME,
    build_soiling_segments,
    fit_segment_slope,
    pooled_soiling_rate,
    segment_clean_days,
)

LOGGER = logging.getLogger(__name__)

ALICE_SPRINGS_SITE_KEY = "alice_springs"
EXTERNAL_VALIDATION_OUTPUT = "external_validation"
CANAKKALE_SITE_KEY = "canakkale"


def detect_inferred_cleaning_events(daily: pd.DataFrame) -> pd.DataFrame:
    """Infer wash-like events from heavy rain and abrupt PI recoveries."""
    frame = daily.sort_values("date").copy()
    frame["pi_rolling_median"] = (
        frame["pi_temp_corrected"]
        .rolling(config.INFERRED_CLEANING_ROLLING_DAYS, min_periods=3)
        .median()
    )
    frame["pi_step_pct"] = (
        100.0
        * (frame["pi_temp_corrected"] - frame["pi_rolling_median"].shift(1))
        / frame["pi_rolling_median"].shift(1)
    )

    rain_col = (
        "onsite_rainfall_mm" if "onsite_rainfall_mm" in frame.columns else "weather_rainfall_mm"
    )
    if rain_col not in frame.columns:
        raise ValueError("No onsite rainfall column available for cleaning inference")

    rain_events = frame.loc[frame[rain_col] >= config.INFERRED_CLEANING_RAIN_MM, "date"].tolist()

    step_events: list[pd.Timestamp] = []
    last_event: pd.Timestamp | None = None
    for _, row in frame.iterrows():
        if pd.isna(row["pi_step_pct"]) or row["pi_step_pct"] < config.INFERRED_CLEANING_PI_STEP_PCT:
            continue
        if (
            last_event is not None
            and (row["date"] - last_event).days < config.INFERRED_CLEANING_MIN_DAYS_BETWEEN
        ):
            continue
        step_events.append(row["date"])
        last_event = row["date"]

    event_rows: list[dict[str, Any]] = []
    for date in rain_events:
        event_rows.append(
            {
                "start": date,
                "end": date,
                "method": "inferred_rain",
                "trigger": "rainfall_mm",
                "trigger_value": float(frame.loc[frame["date"] == date, rain_col].iloc[0]),
            }
        )
    last_event = None
    for date in step_events:
        if (
            last_event is not None
            and (date - last_event).days < config.INFERRED_CLEANING_MIN_DAYS_BETWEEN
        ):
            continue
        event_rows.append(
            {
                "start": date,
                "end": date,
                "method": "inferred_pi_step",
                "trigger": "pi_step_pct",
                "trigger_value": float(frame.loc[frame["date"] == date, "pi_step_pct"].iloc[0]),
            }
        )
        last_event = date

    if not event_rows:
        raise ValueError("No inferred cleaning events detected; cannot build soiling segments")

    events = pd.DataFrame(event_rows).sort_values("start").reset_index(drop=True)
    merged: list[dict[str, Any]] = []
    for _, row in events.iterrows():
        if not merged:
            merged.append(row.to_dict())
            continue
        prev = merged[-1]
        gap_days = (row["start"] - prev["end"]).days
        if gap_days <= config.INFERRED_CLEANING_MERGE_DAYS:
            prev["end"] = max(prev["end"], row["end"])
            prev["method"] = f"{prev['method']}+{row['method']}"
        else:
            merged.append(row.to_dict())

    washing = pd.DataFrame(merged)
    if len(washing) > 1:
        filtered = [washing.iloc[0].to_dict()]
        for _, row in washing.iloc[1:].iterrows():
            prev = filtered[-1]
            if (row["start"] - prev["end"]).days >= config.INFERRED_CLEANING_MIN_DAYS_BETWEEN:
                filtered.append(row.to_dict())
        washing = pd.DataFrame(filtered)
    washing["event_index_by_date"] = range(1, len(washing) + 1)
    LOGGER.info(
        "Inferred %s cleaning events (rain >= %.1f mm or PI step >= %.1f%%)",
        len(washing),
        config.INFERRED_CLEANING_RAIN_MM,
        config.INFERRED_CLEANING_PI_STEP_PCT,
    )
    return washing


def apply_site_temperature_correction(master: pd.DataFrame, site_key: str) -> pd.DataFrame:
    """Temperature-correct PI using onsite or NASA ambient temperature."""
    site = get_site(site_key)
    frame = master.copy()
    temp_col = "weather_temperature_c" if "weather_temperature_c" in frame.columns else "nasa_t2m"
    if temp_col not in frame.columns:
        raise ValueError(f"No temperature column available for {site_key}")

    g_proxy = frame["irradiation"] * 1000.0 / config.NOCT_PEAK_SUN_HOURS
    frame["cell_temp_c"] = frame[temp_col] + (config.MODULE_NOCT_C - 20.0) * (g_proxy / 800.0)
    delta_t = frame["cell_temp_c"] - config.STC_REF_TEMP_C
    coeff = site.resolved_module_temp_coeff()
    frame["pi_temp_corrected"] = frame["pi"] / (1.0 + coeff * delta_t)
    frame["module_temp_coeff_used"] = coeff
    frame["temperature_source"] = temp_col
    return frame


def build_alice_springs_master(force_refresh: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build Alice Springs master table from DKASC CSV plus external enrichment."""
    site = get_site(ALICE_SPRINGS_SITE_KEY)
    daily, dkasc_meta = load_dkasc_daily(
        site.resolved_analysis_start(),
        site.resolved_analysis_end(),
    )

    master = daily.rename(columns={"weather_rainfall_mm": "onsite_rainfall_mm"}).copy()
    master["is_downtime"] = False
    master["is_curtailment"] = False
    master["is_fault"] = False
    master["is_planned"] = False
    master["downtime_hours"] = 0.0
    master["downtime_reasons"] = ""

    nasa, nasa_meta = fetch_nasa_power_daily(
        site_key=ALICE_SPRINGS_SITE_KEY,
        force_refresh=force_refresh,
    )
    cams, cams_meta = fetch_open_meteo_air_quality(
        site_key=ALICE_SPRINGS_SITE_KEY,
        force_refresh=force_refresh,
    )
    validate_nasa_power(nasa)
    validate_open_meteo_aq(cams)
    master = join_external(master, nasa, cams)
    master = apply_site_temperature_correction(master, ALICE_SPRINGS_SITE_KEY)

    washing = detect_inferred_cleaning_events(master)
    master = join_washing_segments(master, washing)

    cutoff = compute_low_irradiation_cutoff(master["irradiation"])
    master, filter_counts = add_quality_flags(master, cutoff)
    master["rain_day"] = master["onsite_rainfall_mm"] >= config.RAIN_DAY_PRECIP_MM
    master["is_clean_observation"] = (
        ~master["is_downtime"]
        & ~master["is_curtailment"]
        & ~master["is_fault"]
        & ~master["low_irradiation"]
        & ~master["rain_day"]
    )

    write_processed(MASTER_OUTPUT_NAME, master, site_key=ALICE_SPRINGS_SITE_KEY)

    metadata = {
        "site_key": ALICE_SPRINGS_SITE_KEY,
        "dkasc_meta": dkasc_meta,
        "nasa_meta": nasa_meta,
        "cams_meta": cams_meta,
        "filter_counts": filter_counts,
        "inferred_cleaning_events": len(washing),
        "module_temp_coeff": site.resolved_module_temp_coeff(),
        "module_temp_coeff_basis": (
            "Assumed -0.41 %/degC from Canadian Solar poly module datasheet class "
            "(CS6K-style); DKASC metadata does not publish a verified coefficient."
        ),
    }
    return master, metadata


def _clear_sky_pooled_rate(master: pd.DataFrame, segments: pd.DataFrame) -> dict[str, float]:
    """Pooled Theil-Sen rate on high-clearness rain-free days (P3.5 spec)."""
    master_clear = attach_clearness_index(master)
    rows: list[dict[str, float]] = []
    for _, seg in segments.iterrows():
        sid = int(seg["segment_id"])
        if seg.get("low_confidence", False):
            continue
        clean = segment_clean_days(master_clear, sid)
        clear_mask = master_clear.loc[clean.index, "clearness_index"] >= config.CLEARNESS_INDEX_MIN
        baseline_temp = float(seg["baseline_pi_temp_corrected"])
        baseline_raw = float(seg["baseline_pi_raw"])
        fit = fit_segment_slope(clean, baseline_temp, baseline_raw, sid, day_mask=clear_mask)
        if pd.isna(fit.slope_pct_per_day) or fit.n_fit < 2:
            continue
        rows.append(
            {
                "segment_id": sid,
                "soiling_rate_pct_per_day": fit.slope_pct_per_day,
                "soiling_rate_ci_lower": fit.ci_lower,
                "soiling_rate_ci_upper": fit.ci_upper,
                "n_fit_rain_free": fit.n_fit,
            }
        )
    if not rows:
        return {
            "pooled_rate": float("nan"),
            "pooled_ci_lower": float("nan"),
            "pooled_ci_upper": float("nan"),
            "n_segments": 0.0,
        }
    frame = pd.DataFrame(rows)
    weights = frame["n_fit_rain_free"].to_numpy(dtype=float)
    rates = frame["soiling_rate_pct_per_day"].to_numpy(dtype=float)
    pooled = float(np.average(rates, weights=weights))
    var = float(np.average((rates - pooled) ** 2, weights=weights))
    se = float(np.sqrt(var / len(frame)))
    return {
        "pooled_rate": pooled,
        "pooled_ci_lower": pooled - 1.96 * se,
        "pooled_ci_upper": pooled + 1.96 * se,
        "n_segments": float(len(frame)),
    }


def _pollution_summary(pollution: pd.DataFrame) -> dict[str, Any]:
    pm10 = pollution.loc[pollution["record_type"] == "pollution_pm10"]
    dust = pollution.loc[pollution["record_type"] == "pollution_dust"]
    row_pm10 = pm10.iloc[0] if not pm10.empty else None
    row_dust = dust.iloc[0] if not dust.empty else None

    def _sig(row: pd.Series | None) -> bool:
        if row is None:
            return False
        p_val = row.get("p_value")
        coef = row.get("coef")
        return pd.notna(p_val) and pd.notna(coef) and float(p_val) < 0.05 and float(coef) < 0

    pm10_sig = _sig(row_pm10)
    dust_sig = _sig(row_dust)
    if pm10_sig or dust_sig:
        verdict = (
            "Daily accumulated CAMS pollution significantly predicts PI decay residuals "
            "after segment trend removal (HAC p<0.05, negative coefficient)."
        )
    else:
        verdict = (
            "Daily accumulated CAMS pollution does NOT significantly predict PI decay "
            "residuals (HAC p>=0.05 or wrong sign), matching the Canakkale null pattern."
        )
    return {
        "pm10_coef": None if row_pm10 is None else row_pm10.get("coef"),
        "pm10_p": None if row_pm10 is None else row_pm10.get("p_value"),
        "pm10_n": None if row_pm10 is None else row_pm10.get("n_obs"),
        "dust_coef": None if row_dust is None else row_dust.get("coef"),
        "dust_p": None if row_dust is None else row_dust.get("p_value"),
        "dust_n": None if row_dust is None else row_dust.get("n_obs"),
        "pollution_significant": pm10_sig or dust_sig,
        "pollution_verdict": verdict,
    }


def _analyze_site(site_key: str, master: pd.DataFrame | None = None) -> dict[str, Any]:
    if master is None:
        master = read_processed(MASTER_OUTPUT_NAME, site_key=site_key)

    if site_key == ALICE_SPRINGS_SITE_KEY:
        washing = detect_inferred_cleaning_events(master)
    else:
        from spis.io import read_interim

        washing = read_interim("washing_events", site_key=site_key)

    segments = build_soiling_segments(master, washing)
    pooled = pooled_soiling_rate(segments)
    master_clear = attach_clearness_index(master)
    clear_pooled = _clear_sky_pooled_rate(master_clear, segments)
    segment_compare = compare_clear_sky_slopes(master_clear, segments)
    daily_residual = build_daily_residual_frame(master_clear, segments)
    pollution = pollution_daily_tests(daily_residual)
    pollution_summary = _pollution_summary(pollution)

    return {
        "site_key": site_key,
        "segments": segments,
        "pooled": pooled,
        "clear_pooled": clear_pooled,
        "segment_compare": segment_compare,
        "pollution": pollution,
        "pollution_summary": pollution_summary,
        "daily_residual_n": len(daily_residual),
    }


def load_canakkale_baseline() -> dict[str, Any]:
    """Load existing Canakkale soiling/robustness outputs without recomputing P3-P3.5."""
    segments = read_processed(SOILING_OUTPUT_NAME, site_key=CANAKKALE_SITE_KEY)
    pooled = pooled_soiling_rate(segments)
    robustness = read_processed(ROBUSTNESS_OUTPUT_NAME, site_key=CANAKKALE_SITE_KEY)
    pollution = robustness.loc[robustness["record_type"].astype(str).str.startswith("pollution")]
    pollution_summary = _pollution_summary(pollution)

    clear_rows = robustness.loc[robustness["record_type"] == "segment_comparison"]
    if clear_rows.empty:
        clear_pooled = {
            "pooled_rate": float("nan"),
            "pooled_ci_lower": float("nan"),
            "pooled_ci_upper": float("nan"),
            "n_segments": 0.0,
        }
    else:
        valid = clear_rows.dropna(subset=["clear_rate_pct_per_day", "clear_n_fit"])
        renamed = valid.rename(
            columns={
                "clear_rate_pct_per_day": "soiling_rate_pct_per_day",
                "clear_ci_lower": "soiling_rate_ci_lower",
                "clear_ci_upper": "soiling_rate_ci_upper",
                "clear_n_fit": "n_fit_rain_free",
            }
        )
        renamed["low_confidence"] = False
        clear_pooled = pooled_soiling_rate(renamed)

    return {
        "site_key": CANAKKALE_SITE_KEY,
        "segments": segments,
        "pooled": pooled,
        "clear_pooled": clear_pooled,
        "pollution_summary": pollution_summary,
    }


def comparison_table(canakkale: dict[str, Any], alice: dict[str, Any]) -> pd.DataFrame:
    """Side-by-side headline metrics for the two sites."""
    rows = []
    for label, block in (("Canakkale Hybrid GES", canakkale), ("DKASC Alice Springs", alice)):
        rows.append(
            {
                "site": label,
                "site_key": block["site_key"],
                "pooled_soiling_rate_pct_per_day": block["pooled"]["pooled_rate"],
                "pooled_ci_lower": block["pooled"]["pooled_ci_lower"],
                "pooled_ci_upper": block["pooled"]["pooled_ci_upper"],
                "clear_sky_pooled_rate_pct_per_day": block["clear_pooled"]["pooled_rate"],
                "clear_sky_ci_lower": block["clear_pooled"]["pooled_ci_lower"],
                "clear_sky_ci_upper": block["clear_pooled"]["pooled_ci_upper"],
                "pm10_hac_coef": block["pollution_summary"]["pm10_coef"],
                "pm10_hac_p": block["pollution_summary"]["pm10_p"],
                "dust_hac_coef": block["pollution_summary"]["dust_coef"],
                "dust_hac_p": block["pollution_summary"]["dust_p"],
                "pollution_significant": block["pollution_summary"]["pollution_significant"],
            }
        )
    return pd.DataFrame(rows)


def honest_verdict(table: pd.DataFrame, alice_meta: dict[str, Any]) -> str:
    """Plain-language synthesis of the generalization test."""
    can = table.loc[table["site_key"] == CANAKKALE_SITE_KEY].iloc[0]
    ali = table.loc[table["site_key"] == ALICE_SPRINGS_SITE_KEY].iloc[0]

    can_rate = float(can["clear_sky_pooled_rate_pct_per_day"])
    ali_rate = float(ali["clear_sky_pooled_rate_pct_per_day"])
    can_poll = bool(can["pollution_significant"])
    ali_poll = bool(ali["pollution_significant"])

    rate_text = (
        f"Clear-sky pooled soiling rate: Canakkale {can_rate:.4f} %/day "
        f"(CI {can['clear_sky_ci_lower']:.4f} .. {can['clear_sky_ci_upper']:.4f}) vs "
        f"Alice Springs {ali_rate:.4f} %/day "
        f"(CI {ali['clear_sky_ci_lower']:.4f} .. {ali['clear_sky_ci_upper']:.4f})."
    )

    if ali_rate < can_rate and abs(ali_rate) > abs(can_rate) * 1.5:
        rate_compare = (
            "Alice Springs shows a stronger negative PI drift between inferred cleanings "
            "than Canakkale, consistent with a dustier desert climate."
        )
    elif abs(ali_rate) <= abs(can_rate) * 1.2:
        rate_compare = (
            "Alice Springs does not show materially faster soiling than Canakkale once "
            "clear-sky filtering is applied; the desert site is not dramatically dustier "
            "in this ~5 kW research array."
        )
    else:
        rate_compare = (
            "Alice Springs soiling rate differs from Canakkale but not in a simple "
            "'desert is faster' direction; interpret with the cleaning-inference caveat."
        )

    if ali_poll and not can_poll:
        poll_text = (
            "Unlike Canakkale, Alice Springs shows a statistically significant daily CAMS "
            "dust/PM10 link to PI decay residuals. This supports the SPIS method detecting "
            "pollution-linked soiling where the environment is dust-dominated, and reinforces "
            "that Canakkale's null is a site characteristic rather than a method failure."
        )
    elif not ali_poll and not can_poll:
        poll_text = (
            "Neither site shows a significant daily CAMS pollution–PI decay link after trend "
            "removal. The generalization test does not validate a dust-driver hypothesis at "
            "grid scale even in central Australia; both sites appear dominated by other "
            "soiling/recovery dynamics at this temporal resolution."
        )
    elif ali_poll and can_poll:
        poll_text = (
            "Both sites show significant CAMS pollution coefficients; pollution may contribute "
            "at both locations, contrary to the Canakkale-only null headline."
        )
    else:
        poll_text = (
            "Pollution significance differs between sites, but Alice Springs does not show "
            "the expected stronger dust signal; Canakkale's null remains credible."
        )

    cleaning_note = (
        f"Alice Springs used {alice_meta['inferred_cleaning_events']} inferred cleaning events "
        f"(rain >= {config.INFERRED_CLEANING_RAIN_MM:.0f} mm and/or PI step >= "
        f"{config.INFERRED_CLEANING_PI_STEP_PCT:.0f}% vs rolling median); rates are approximate."
    )
    return " ".join([rate_text, rate_compare, poll_text, cleaning_note])


def _save_figure(stem: str, fig: plt.Figure, data: pd.DataFrame) -> None:
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    png = config.FIGURES / f"{stem}.png"
    csv = config.FIGURES / f"{stem}.csv"
    fig.savefig(png, dpi=300, bbox_inches="tight")
    plt.close(fig)
    data.to_csv(csv, index=False)
    LOGGER.info("Saved figure %s", png)


def save_external_validation_figures(
    table: pd.DataFrame,
    alice: dict[str, Any],
) -> None:
    """Comparison bar chart and dust-vs-residual scatter."""
    plot_table = table.copy()
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(plot_table))
    ax.bar(
        x - 0.15,
        plot_table["clear_sky_pooled_rate_pct_per_day"],
        width=0.3,
        label="Clear-sky pooled",
    )
    ax.errorbar(
        x - 0.15,
        plot_table["clear_sky_pooled_rate_pct_per_day"],
        yerr=[
            plot_table["clear_sky_pooled_rate_pct_per_day"] - plot_table["clear_sky_ci_lower"],
            plot_table["clear_sky_ci_upper"] - plot_table["clear_sky_pooled_rate_pct_per_day"],
        ],
        fmt="none",
        ecolor="black",
        capsize=4,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(["Canakkale", "Alice Springs"])
    ax.axhline(0, color="0.5", linewidth=0.8)
    ax.set_ylabel("Soiling rate (%/day)")
    ax.set_title("Clear-sky pooled soiling rate — Canakkale vs Alice Springs")
    ax.legend()
    fig.tight_layout()
    _save_figure("external_validation_soiling_rate_comparison", fig, plot_table)

    residual = alice.get("daily_residual")
    if residual is None:
        return
    data = residual.dropna(subset=["pi_residual", "dust_accumulated"]).copy()
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(data["dust_accumulated"], data["pi_residual"], s=10, alpha=0.35)
    ax.set_xlabel("Accumulated CAMS dust since inferred cleaning (ug/m3-days)")
    ax.set_ylabel("PI residual (temp corrected)")
    ax.set_title(f"Alice Springs daily residual vs accumulated dust (n={len(data)})")
    fig.tight_layout()
    _save_figure(
        "external_validation_alice_dust_vs_residual",
        fig,
        data[["date", "dust_accumulated", "pi_residual"]],
    )


def write_external_validation_report(
    table: pd.DataFrame,
    verdict: str,
    alice_meta: dict[str, Any],
    dkasc_meta: dict[str, Any],
) -> None:
    """Write reports/EXTERNAL_VALIDATION.md."""
    path = config.REPORTS / "EXTERNAL_VALIDATION.md"
    lines = [
        "# External validation — DKASC Alice Springs vs Canakkale",
        "",
        "## Verdict",
        "",
        verdict,
        "",
        "## Comparison table",
        "",
        "| Site | Clear-sky rate (%/day) | 95% CI | PM10 HAC coef | PM10 p | "
        "Dust HAC coef | Dust p | Pollution sig.? |",
        "|---|---:|---|---:|---:|---:|---:|---|",
    ]
    for _, row in table.iterrows():
        lines.append(
            f"| {row['site']} | {row['clear_sky_pooled_rate_pct_per_day']:.4f} | "
            f"[{row['clear_sky_ci_lower']:.4f}, {row['clear_sky_ci_upper']:.4f}] | "
            f"{row['pm10_hac_coef']} | {row['pm10_hac_p']} | {row['dust_hac_coef']} | "
            f"{row['dust_hac_p']} | {'yes' if row['pollution_significant'] else 'no'} |"
        )

    lines.extend(
        [
            "",
            "## Cleaning-inference caveat (Alice Springs)",
            "",
            "No operator wash log exists at DKASC. Cleaning events were inferred from:",
            f"- Rainfall >= {config.INFERRED_CLEANING_RAIN_MM:.0f} mm/day "
            "(onsite Weather_Daily_Rainfall), and",
            f"- Abrupt PI recoveries >= {config.INFERRED_CLEANING_PI_STEP_PCT:.0f}% above a "
            f"{config.INFERRED_CLEANING_ROLLING_DAYS}-day rolling median.",
            f"Events within {config.INFERRED_CLEANING_MERGE_DAYS} days were merged. "
            "Segment soiling rates are therefore approximate and not directly comparable to "
            "Canakkale's logged brush/robot washes.",
            "",
            "## kW-scale research-array caveat",
            "",
            f"Data source: {dkasc_meta['array_label']} "
            "(~5.3 kW AC research array, not a utility plant). "
            "Single-array noise, inverter clipping, and reference-sensor co-soiling can differ "
            "from Canakkale Hybrid GES (~2750 kW AC). Results test method generalization, "
            "not commercial fleet performance.",
            "",
            "## DKASC column mapping (verified from header)",
            "",
        ]
    )
    for canonical, raw in dkasc_meta["column_mapping"].items():
        lines.append(f"- `{canonical}` -> `{raw}`")
    lines.extend(
        [
            "",
            "## Temperature coefficient assumption",
            "",
            alice_meta["module_temp_coeff_basis"],
            "",
            f"Analysis window: {get_site(ALICE_SPRINGS_SITE_KEY).resolved_analysis_start()} .. "
            f"{get_site(ALICE_SPRINGS_SITE_KEY).resolved_analysis_end()} (aligned with Canakkale).",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def run_external_validation(force_refresh: bool = False) -> dict[str, Any]:
    """Execute P14 external validation end-to-end."""
    master, alice_meta = build_alice_springs_master(force_refresh=force_refresh)
    alice = _analyze_site(ALICE_SPRINGS_SITE_KEY, master=master)
    alice["daily_residual"] = build_daily_residual_frame(
        attach_clearness_index(master),
        alice["segments"],
    )
    write_processed(SOILING_OUTPUT_NAME, alice["segments"], site_key=ALICE_SPRINGS_SITE_KEY)

    canakkale = load_canakkale_baseline()
    table = comparison_table(canakkale, alice)
    verdict = honest_verdict(table, alice_meta)

    export = table.copy()
    export["record_type"] = "site_comparison"
    export_rows = [export]
    export_rows.append(alice["pollution"].assign(record_type="alice_pollution"))
    write_processed(
        EXTERNAL_VALIDATION_OUTPUT,
        pd.concat(export_rows, ignore_index=True, sort=False),
        site_key=ALICE_SPRINGS_SITE_KEY,
    )

    write_external_validation_report(
        table,
        verdict,
        alice_meta,
        alice_meta["dkasc_meta"],
    )
    save_external_validation_figures(table, alice)

    return {
        "table": table,
        "verdict": verdict,
        "alice_meta": alice_meta,
        "alice": alice,
        "canakkale": canakkale,
    }
