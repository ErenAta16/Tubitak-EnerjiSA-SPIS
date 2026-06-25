"""Core SPIS dashboard logic for the Streamlit UI (no Streamlit imports)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from spis import config
from spis.external_validation import (
    ALICE_SPRINGS_SITE_KEY,
    EXTERNAL_VALIDATION_OUTPUT,
    load_canakkale_baseline,
)
from spis.io import read_processed
from spis.optimize import (
    SoilingRateBand,
    compute_clean_baseline_energy,
    load_soiling_rate_band,
    optimal_interval_grid_search,
    price_tl_per_kwh,
)
from spis.robustness import ROBUSTNESS_OUTPUT_NAME
from spis.sites import DEFAULT_SITE, get_site, site_processed_path
from spis.soiling import MASTER_INPUT_NAME, SOILING_OUTPUT_NAME

REQUIRED_UPLOAD_COLUMNS = ("date", "production", "irradiation")


@dataclass(frozen=True)
class UploadValidation:
    """Result of validating a user upload."""

    ok: bool
    message: str
    frame: pd.DataFrame | None = None


@dataclass(frozen=True)
class DashboardSnapshot:
    """Bundle of headline metrics for one site."""

    site_key: str
    site_name: str
    available: bool
    message: str
    clear_sky_rate_pct_per_day: float | None
    clear_sky_ci_lower: float | None
    clear_sky_ci_upper: float | None
    pollution_verdict: str
    daily_energy_kwh: float | None
    rate_band: SoilingRateBand | None
    master: pd.DataFrame | None
    comparison_table: pd.DataFrame | None = None


def example_site_available(site_key: str) -> bool:
    """Return True when processed artifacts exist for a built-in example site."""
    if site_key == ALICE_SPRINGS_SITE_KEY:
        return site_processed_path(site_key, MASTER_INPUT_NAME).exists()
    if site_key == DEFAULT_SITE:
        return (config.DATA_PROCESSED / f"{MASTER_INPUT_NAME}.parquet").exists()
    return False


def validate_upload_frame(frame: pd.DataFrame) -> UploadValidation:
    """Validate uploaded daily production + irradiation data."""
    if frame.empty:
        return UploadValidation(False, "Uploaded file is empty.")
    normalized = frame.copy()
    normalized.columns = [str(c).strip().lower() for c in normalized.columns]
    missing = [col for col in REQUIRED_UPLOAD_COLUMNS if col not in normalized.columns]
    if missing:
        return UploadValidation(
            False,
            f"Missing required columns: {', '.join(missing)}. "
            "Expected at least date, production, irradiation.",
        )
    working = normalized[list(REQUIRED_UPLOAD_COLUMNS)].copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce").dt.normalize()
    working["production"] = pd.to_numeric(working["production"], errors="coerce")
    working["irradiation"] = pd.to_numeric(working["irradiation"], errors="coerce")
    if working["date"].isna().any():
        return UploadValidation(False, "Some date values could not be parsed.")
    if working[["production", "irradiation"]].isna().any().any():
        return UploadValidation(False, "production and irradiation must be numeric on all rows.")
    if (working["production"] < 0).any() or (working["irradiation"] < 0).any():
        return UploadValidation(False, "production and irradiation must be >= 0.")
    working = working.sort_values("date").drop_duplicates("date")
    working["pi"] = working["production"] / working["irradiation"].replace(0, pd.NA)
    if working["pi"].isna().any():
        return UploadValidation(False, "Zero irradiation days are not allowed for PI.")
    return UploadValidation(True, f"Validated {len(working)} daily rows.", working)


def _robustness_verdict(site_key: str) -> str:
    path = site_processed_path(site_key, ROBUSTNESS_OUTPUT_NAME)
    if not path.exists():
        return "Pollution test not available (run robustness stage first)."
    robustness = read_processed(ROBUSTNESS_OUTPUT_NAME, site_key=site_key)
    verdict = robustness.loc[robustness["record_type"] == "p4_verdict"]
    if verdict.empty:
        return "Pollution verdict row missing in robustness output."
    return str(verdict.iloc[0].get("pollution_verdict", "No pollution verdict recorded."))


def _load_site_comparison_table() -> pd.DataFrame | None:
    path = site_processed_path(ALICE_SPRINGS_SITE_KEY, EXTERNAL_VALIDATION_OUTPUT)
    if not path.exists():
        return None
    export = read_processed(EXTERNAL_VALIDATION_OUTPUT, site_key=ALICE_SPRINGS_SITE_KEY)
    table = export.loc[export["record_type"] == "site_comparison"]
    return table if not table.empty else None


def load_dashboard_snapshot(site_key: str) -> DashboardSnapshot:
    """Load precomputed metrics for a built-in example site."""
    site = get_site(site_key)
    if not example_site_available(site_key):
        return DashboardSnapshot(
            site_key=site_key,
            site_name=site.name,
            available=False,
            message="Example data not built yet. Run the SPIS pipeline locally first.",
            clear_sky_rate_pct_per_day=None,
            clear_sky_ci_lower=None,
            clear_sky_ci_upper=None,
            pollution_verdict="",
            daily_energy_kwh=None,
            rate_band=None,
            master=None,
        )

    master = read_processed(MASTER_INPUT_NAME, site_key=site_key)
    segments = read_processed(SOILING_OUTPUT_NAME, site_key=site_key)
    baseline_energy = compute_clean_baseline_energy(master, segments)
    daily_energy = float(baseline_energy["clean_baseline_kwh_day"].median())
    comparison = _load_site_comparison_table()

    if site_key == DEFAULT_SITE:
        can = load_canakkale_baseline()
        clear = can["clear_pooled"]
        robustness = read_processed(ROBUSTNESS_OUTPUT_NAME, site_key=site_key)
        rate_band = load_soiling_rate_band(robustness)
        pollution = _robustness_verdict(site_key)
        return DashboardSnapshot(
            site_key=site_key,
            site_name=site.name,
            available=True,
            message="Canakkale example loaded from processed SPIS outputs.",
            clear_sky_rate_pct_per_day=float(clear["pooled_rate"]),
            clear_sky_ci_lower=float(clear["pooled_ci_lower"]),
            clear_sky_ci_upper=float(clear["pooled_ci_upper"]),
            pollution_verdict=pollution,
            daily_energy_kwh=daily_energy,
            rate_band=rate_band,
            master=master,
            comparison_table=comparison,
        )

    if comparison is None:
        return DashboardSnapshot(
            site_key=site_key,
            site_name=site.name,
            available=False,
            message="Run `python -m spis.run --stage external_validation` first.",
            clear_sky_rate_pct_per_day=None,
            clear_sky_ci_lower=None,
            clear_sky_ci_upper=None,
            pollution_verdict="",
            daily_energy_kwh=None,
            rate_band=None,
            master=master,
        )

    alice_row = comparison.loc[comparison["site_key"] == ALICE_SPRINGS_SITE_KEY].iloc[0]
    rate_band = SoilingRateBand(
        point=abs(float(alice_row["clear_sky_pooled_rate_pct_per_day"])) / 100.0,
        low=abs(float(alice_row["clear_sky_ci_lower"])) / 100.0,
        high=abs(float(alice_row["clear_sky_ci_upper"])) / 100.0,
        source="Alice Springs clear-sky pooled (inferred cleanings)",
        half_width=0.0,
    )
    pollution = (
        "CAMS dust/PM10 significantly predicts PI decay residuals."
        if bool(alice_row["pollution_significant"])
        else "Daily CAMS pollution does not significantly predict PI decay residuals."
    )
    return DashboardSnapshot(
        site_key=site_key,
        site_name=site.name,
        available=True,
        message="Alice Springs example loaded from P14 external validation outputs.",
        clear_sky_rate_pct_per_day=float(alice_row["clear_sky_pooled_rate_pct_per_day"]),
        clear_sky_ci_lower=float(alice_row["clear_sky_ci_lower"]),
        clear_sky_ci_upper=float(alice_row["clear_sky_ci_upper"]),
        pollution_verdict=pollution,
        daily_energy_kwh=daily_energy,
        rate_band=rate_band,
        master=master,
        comparison_table=comparison,
    )


def compute_live_optimization(
    wash_cost_tl: float,
    price_tl_mwh: float,
    rate_band: SoilingRateBand,
    daily_energy_kwh: float,
) -> dict[str, Any]:
    """Recompute optimal wash interval and cost curve for UI sliders."""
    t_star, curve = optimal_interval_grid_search(
        wash_cost_tl=wash_cost_tl,
        daily_energy_kwh=daily_energy_kwh,
        price_tl_mwh=price_tl_mwh,
        rate_fraction_per_day=rate_band.point,
    )
    if rate_band.point > 0:
        t_closed = float(
            min(
                config.OPTIMIZE_GRID_MAX_DAYS,
                max(
                    1.0,
                    (
                        2.0
                        * wash_cost_tl
                        / (rate_band.point * daily_energy_kwh * price_tl_per_kwh(price_tl_mwh))
                    )
                    ** 0.5,
                ),
            )
        )
    else:
        t_closed = float(config.OPTIMIZE_GRID_MAX_DAYS)
    return {
        "t_star_days": t_star,
        "t_star_closed_form_days": t_closed,
        "cost_curve": curve,
        "wash_cost_tl": wash_cost_tl,
        "price_tl_mwh": price_tl_mwh,
    }


def build_results_summary_markdown(
    snapshot: DashboardSnapshot, optimization: dict[str, Any]
) -> str:
    """Plain-language summary for download."""
    lines = [
        "# SPIS results summary",
        "",
        f"Site: {snapshot.site_name} ({snapshot.site_key})",
        "",
        "## Soiling",
        "",
    ]
    if snapshot.clear_sky_rate_pct_per_day is not None:
        lines.append(
            f"- Clear-sky pooled rate: {snapshot.clear_sky_rate_pct_per_day:.4f} %/day "
            f"(CI {snapshot.clear_sky_ci_lower:.4f} .. {snapshot.clear_sky_ci_upper:.4f})"
        )
    lines.extend(
        [
            "",
            "## Pollution test",
            "",
            snapshot.pollution_verdict or "Not available.",
            "",
            "## Economic optimizer (live inputs)",
            "",
            f"- Wash cost: {optimization['wash_cost_tl']:.0f} TL",
            f"- Electricity price: {optimization['price_tl_mwh']:.0f} TL/MWh",
            f"- Optimal interval T*: {optimization['t_star_days']:.0f} days",
            "",
        ]
    )
    return "\n".join(lines)


def list_downloadable_figures() -> list[Path]:
    """Return key PNG figures if they exist."""
    names = (
        "soiling_timeline_slopes",
        "external_validation_soiling_rate_comparison",
        "washing_cost_curve_central",
    )
    return [
        config.FIGURES / f"{name}.png"
        for name in names
        if (config.FIGURES / f"{name}.png").exists()
    ]
