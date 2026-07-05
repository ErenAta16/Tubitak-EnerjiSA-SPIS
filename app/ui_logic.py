"""Core SPIS dashboard logic for the Streamlit UI (no Streamlit imports)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.models import DashboardSnapshot
from app.theme import format_percent_in_text
from spis import config
from spis.demo_plant import (
    DEMO_PLANT_KEY,
    DEMO_PLANT_NAME,
    demo_artifact_path,
    demo_data_available,
    load_demo_headline_metrics,
)
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
from spis.public_examples import (
    DKASC_KEY,
    DKASC_NAME,
    PUBLIC_EXAMPLE_KEYS,
    PVDAQ_2107_KEY,
    PVDAQ_2107_NAME,
    load_public_headline_metrics,
    public_example_available,
)
from spis.robustness import ROBUSTNESS_OUTPUT_NAME
from spis.sites import DEFAULT_SITE, get_site, site_processed_path
from spis.soiling import MASTER_INPUT_NAME, SOILING_OUTPUT_NAME

REQUIRED_UPLOAD_COLUMNS = ("date", "production", "irradiation")


@dataclass(frozen=True)
class ExampleSiteOption:
    """Selectable built-in example site."""

    label: str
    site_key: str


@dataclass(frozen=True)
class UploadValidation:
    """Result of validating a user upload."""

    ok: bool
    message: str
    frame: pd.DataFrame | None = None


def example_site_available(site_key: str) -> bool:
    """Return True when processed artifacts exist for a built-in example site."""
    if site_key == DEMO_PLANT_KEY:
        return demo_data_available()
    if site_key in PUBLIC_EXAMPLE_KEYS:
        return public_example_available(site_key)
    if site_key == DEFAULT_SITE:
        return (config.DATA_PROCESSED / f"{MASTER_INPUT_NAME}.parquet").exists()
    return False


def list_example_site_options() -> list[ExampleSiteOption]:
    """Return bundled public examples plus any locally available proprietary site."""
    options = [
        ExampleSiteOption(DEMO_PLANT_NAME, DEMO_PLANT_KEY),
        ExampleSiteOption(PVDAQ_2107_NAME, PVDAQ_2107_KEY),
        ExampleSiteOption(DKASC_NAME, DKASC_KEY),
    ]
    if example_site_available(DEFAULT_SITE):
        options.append(ExampleSiteOption("Canakkale Hybrid GES (local)", DEFAULT_SITE))
    return options


def default_example_site_key() -> str:
    """Default example selection for fresh clones."""
    return DEMO_PLANT_KEY


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
            "Expected columns: date, production, irradiation.",
        )
    working = normalized[list(REQUIRED_UPLOAD_COLUMNS)].copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce").dt.normalize()
    working["production"] = pd.to_numeric(working["production"], errors="coerce")
    working["irradiation"] = pd.to_numeric(working["irradiation"], errors="coerce")
    if working["date"].isna().any():
        return UploadValidation(False, "Some date values could not be parsed (use YYYY-MM-DD).")
    if working[["production", "irradiation"]].isna().any().any():
        return UploadValidation(False, "production and irradiation must be numeric on all rows.")
    if (working["production"] < 0).any() or (working["irradiation"] < 0).any():
        return UploadValidation(False, "production and irradiation must be >= 0.")
    if (working["irradiation"] == 0).any():
        return UploadValidation(
            False,
            "Zero irradiation days are not allowed (performance index would divide by zero).",
        )
    working = working.sort_values("date").drop_duplicates("date")
    if len(working) < 30:
        return UploadValidation(
            False,
            f"Only {len(working)} rows after parsing; provide at least 30 daily rows.",
        )
    working["pi"] = working["production"] / working["irradiation"]
    return UploadValidation(True, f"Validated {len(working)} daily rows.", working)


def plain_language_soiling_line(
    rate_pct_per_day: float | None,
    lang: str,
    ci_lower: float | None = None,
    ci_upper: float | None = None,
) -> str:
    """One-line explanation of the headline soiling rate."""
    if rate_pct_per_day is None:
        return "Soiling rate unavailable." if lang == "EN" else "Kirlenme hızı hesaplanamadı."
    if ci_lower is not None and ci_upper is not None and ci_lower <= 0.0 <= ci_upper:
        if lang == "TR":
            return "Güven aralığı sıfırı kesiyor; ölçülebilir bir kirlenme düşüşü gösterilemedi."
        return (
            "The confidence interval crosses zero; no measurable soiling decline was established."
        )
    if rate_pct_per_day >= 0.0:
        if lang == "TR":
            return "Nokta tahmini performans düşüşü göstermiyor."
        return "The point estimate does not show a performance decline."
    drop = abs(rate_pct_per_day)
    if lang == "TR":
        pct = format_percent_in_text(drop, lang)
        return f"Yıkamalar arasında performans günde yaklaşık {pct} düşüyor (açık gökyüzü tahmini)."
    return f"Performance drops about {drop:.2f}% per day between washes (clear-sky estimate)."


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


def load_demo_dashboard_snapshot() -> DashboardSnapshot:
    """Load the bundled synthetic demo plant snapshot."""
    if not demo_data_available():
        return DashboardSnapshot(
            site_key=DEMO_PLANT_KEY,
            site_name=DEMO_PLANT_NAME,
            available=False,
            message="Synthetic demo snapshot missing. Run scripts/generate_demo_plant.py.",
            clear_sky_rate_pct_per_day=None,
            clear_sky_ci_lower=None,
            clear_sky_ci_upper=None,
            pollution_verdict="",
            daily_energy_kwh=None,
            rate_band=None,
            master=None,
        )
    metrics = load_demo_headline_metrics()
    master = pd.read_parquet(demo_artifact_path(MASTER_INPUT_NAME))
    segments = pd.read_parquet(demo_artifact_path(SOILING_OUTPUT_NAME))
    rate = metrics["clear_sky_rate_pct_per_day"]
    return DashboardSnapshot(
        site_key=DEMO_PLANT_KEY,
        site_name=DEMO_PLANT_NAME,
        available=True,
        message=(
            "Synthetic demo plant loaded. The real analysis in the TUBITAK 2209-B report "
            "used real data from Enerjisa Canakkale, DKASC, and PVDAQ 2107."
        ),
        clear_sky_rate_pct_per_day=rate,
        clear_sky_ci_lower=metrics["clear_sky_ci_lower"],
        clear_sky_ci_upper=metrics["clear_sky_ci_upper"],
        pollution_verdict=metrics["pollution_verdict"],
        daily_energy_kwh=metrics["daily_energy_kwh"],
        rate_band=metrics["rate_band"],
        master=master,
        segments=segments,
        plain_language_soiling=plain_language_soiling_line(rate, "EN"),
    )


def load_public_dashboard_snapshot(site_key: str) -> DashboardSnapshot:
    """Load one committed public real-site snapshot without local processed data."""
    site_names = {
        PVDAQ_2107_KEY: PVDAQ_2107_NAME,
        DKASC_KEY: DKASC_NAME,
    }
    messages = {
        PVDAQ_2107_KEY: (
            "Real-site data loaded — NREL PVDAQ 2107, public data (not Enerjisa data)."
        ),
        DKASC_KEY: (
            "Real-site data loaded — DKASC Alice Springs array 14, public data (not Enerjisa data)."
        ),
    }
    if not public_example_available(site_key):
        return DashboardSnapshot(
            site_key=site_key,
            site_name=site_names.get(site_key, site_key),
            available=False,
            message="Bundled public example snapshot is missing.",
            clear_sky_rate_pct_per_day=None,
            clear_sky_ci_lower=None,
            clear_sky_ci_upper=None,
            pollution_verdict="",
            daily_energy_kwh=None,
            rate_band=None,
            master=None,
        )
    metrics = load_public_headline_metrics(site_key)
    rate = metrics["clear_sky_rate_pct_per_day"]
    return DashboardSnapshot(
        site_key=site_key,
        site_name=site_names[site_key],
        available=True,
        message=messages[site_key],
        clear_sky_rate_pct_per_day=rate,
        clear_sky_ci_lower=metrics["clear_sky_ci_lower"],
        clear_sky_ci_upper=metrics["clear_sky_ci_upper"],
        pollution_verdict=metrics["pollution_verdict"],
        daily_energy_kwh=metrics["daily_energy_kwh"],
        rate_band=metrics["rate_band"],
        master=metrics["master"],
        segments=metrics["segments"],
        plain_language_soiling=plain_language_soiling_line(
            rate,
            "EN",
            metrics["clear_sky_ci_lower"],
            metrics["clear_sky_ci_upper"],
        ),
    )


def load_dashboard_snapshot(site_key: str) -> DashboardSnapshot:
    """Load precomputed metrics for a built-in example site."""
    if site_key == DEMO_PLANT_KEY:
        return load_demo_dashboard_snapshot()
    if site_key in PUBLIC_EXAMPLE_KEYS:
        return load_public_dashboard_snapshot(site_key)

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
        rate = float(clear["pooled_rate"])
        return DashboardSnapshot(
            site_key=site_key,
            site_name=site.name,
            available=True,
            message="Canakkale example loaded from local processed SPIS outputs.",
            clear_sky_rate_pct_per_day=rate,
            clear_sky_ci_lower=float(clear["pooled_ci_lower"]),
            clear_sky_ci_upper=float(clear["pooled_ci_upper"]),
            pollution_verdict=pollution,
            daily_energy_kwh=daily_energy,
            rate_band=rate_band,
            master=master,
            segments=segments,
            comparison_table=comparison,
            plain_language_soiling=plain_language_soiling_line(rate, "EN"),
        )

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
        master=master,
        segments=segments,
    )


def load_upload_dashboard_snapshot(frame: pd.DataFrame) -> DashboardSnapshot:
    """Build a dashboard snapshot from an uploaded CSV using SPIS soiling functions."""
    validation = validate_upload_frame(frame)
    if not validation.ok or validation.frame is None:
        return DashboardSnapshot(
            site_key="upload",
            site_name="Uploaded data",
            available=False,
            message=validation.message,
            clear_sky_rate_pct_per_day=None,
            clear_sky_ci_lower=None,
            clear_sky_ci_upper=None,
            pollution_verdict="",
            daily_energy_kwh=None,
            rate_band=None,
            master=None,
            segments=None,
        )
    try:
        from app.upload_analysis import analyze_upload_frame

        analysis = analyze_upload_frame(validation.frame)
    except ValueError as exc:
        return DashboardSnapshot(
            site_key="upload",
            site_name="Uploaded data",
            available=False,
            message=str(exc),
            clear_sky_rate_pct_per_day=None,
            clear_sky_ci_lower=None,
            clear_sky_ci_upper=None,
            pollution_verdict="",
            daily_energy_kwh=None,
            rate_band=None,
            master=None,
            segments=None,
        )
    rate = analysis.clear_sky_rate_pct_per_day
    return DashboardSnapshot(
        site_key="upload",
        site_name="Uploaded data",
        available=True,
        message=validation.message,
        clear_sky_rate_pct_per_day=rate,
        clear_sky_ci_lower=analysis.clear_sky_ci_lower,
        clear_sky_ci_upper=analysis.clear_sky_ci_upper,
        pollution_verdict=analysis.pollution_verdict,
        daily_energy_kwh=analysis.daily_energy_kwh,
        rate_band=analysis.rate_band,
        master=analysis.master,
        segments=analysis.segments,
        plain_language_soiling=plain_language_soiling_line(rate, "EN"),
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
    """Return key PNG figures if they exist locally."""
    names = (
        "soiling_timeline_slopes",
        "external_validation_soiling_rate_comparison",
        "optimize_cost_vs_interval",
    )
    return [
        config.FIGURES / f"{name}.png"
        for name in names
        if (config.FIGURES / f"{name}.png").exists()
    ]


def get_sample_upload_csv_bytes() -> bytes:
    """Expose upload template bytes for the Streamlit download button."""
    from app.upload_analysis import sample_upload_csv_bytes

    return sample_upload_csv_bytes()
