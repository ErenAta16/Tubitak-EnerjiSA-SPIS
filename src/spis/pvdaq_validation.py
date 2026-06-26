"""P17 utility-scale external validation: PVDAQ system 2107 vs Canakkale."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from spis import config
from spis.clean import (
    MASTER_OUTPUT_NAME,
    add_quality_flags,
    compute_low_irradiation_cutoff,
    join_external,
    join_washing_segments,
)
from spis.data_sources.nasa_power import fetch_nasa_power_daily, validate_nasa_power
from spis.data_sources.open_meteo_aq import fetch_open_meteo_air_quality, validate_open_meteo_aq
from spis.data_sources.pvdaq import (
    MODULE_TEMP_COEFF,
    MODULE_TEMP_COEFF_BASIS,
    load_pvdaq_daily,
)
from spis.external_validation import (
    CANAKKALE_SITE_KEY,
    CANONICAL_CI_METHOD,
    _pollution_summary,
    apply_site_temperature_correction,
    detect_inferred_cleaning_events,
    load_canakkale_baseline,
)
from spis.io import write_processed
from spis.robustness import (
    attach_clearness_index,
    build_daily_residual_frame,
    canonical_clear_sky_pooled,
    compare_clear_sky_slopes,
    pollution_daily_tests,
)
from spis.sites import get_site
from spis.soiling import SOILING_OUTPUT_NAME, build_soiling_segments

LOGGER = logging.getLogger(__name__)

PVDAQ_2107_SITE_KEY = "pvdaq_2107"
PVDAQ_VALIDATION_OUTPUT = "pvdaq_validation"


def _cleaning_params() -> dict[str, float | int]:
    return {
        "rain_mm": config.PVDAQ_INFERRED_CLEANING_RAIN_MM,
        "pi_step_pct": config.PVDAQ_INFERRED_CLEANING_PI_STEP_PCT,
        "min_days_between": config.PVDAQ_INFERRED_CLEANING_MIN_DAYS_BETWEEN,
    }


def build_pvdaq_master(force_refresh: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build PVDAQ 2107 daily master with NASA/CAMS enrichment and inferred cleanings."""
    site = get_site(PVDAQ_2107_SITE_KEY)
    daily, pvdaq_meta = load_pvdaq_daily(
        site.resolved_analysis_start(),
        site.resolved_analysis_end(),
    )

    master = daily.copy()
    master["onsite_rainfall_mm"] = 0.0
    master["is_downtime"] = False
    master["is_curtailment"] = False
    master["is_fault"] = False
    master["is_planned"] = False
    master["downtime_hours"] = 0.0
    master["downtime_reasons"] = ""

    nasa, nasa_meta = fetch_nasa_power_daily(
        site_key=PVDAQ_2107_SITE_KEY,
        force_refresh=force_refresh,
    )
    cams, cams_meta = fetch_open_meteo_air_quality(
        site_key=PVDAQ_2107_SITE_KEY,
        force_refresh=force_refresh,
    )
    validate_nasa_power(nasa)
    validate_open_meteo_aq(cams)
    master = join_external(master, nasa, cams)

    if "nasa_t2m" in master.columns:
        master["weather_temperature_c"] = master["weather_temperature_c"].fillna(master["nasa_t2m"])

    if "nasa_precip_mm" in master.columns:
        master["onsite_rainfall_mm"] = master["nasa_precip_mm"].fillna(0.0)
        master["weather_rainfall_mm"] = master["onsite_rainfall_mm"]

    cleaning = _cleaning_params()
    master = apply_site_temperature_correction(
        master,
        PVDAQ_2107_SITE_KEY,
        module_temp_coeff=MODULE_TEMP_COEFF,
    )

    washing = detect_inferred_cleaning_events(master, **cleaning)
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

    write_processed(MASTER_OUTPUT_NAME, master, site_key=PVDAQ_2107_SITE_KEY)

    metadata = {
        "site_key": PVDAQ_2107_SITE_KEY,
        "pvdaq_meta": pvdaq_meta,
        "nasa_meta": nasa_meta,
        "cams_meta": cams_meta,
        "filter_counts": filter_counts,
        "inferred_cleaning_events": len(washing),
        "cleaning_params": cleaning,
        "module_temp_coeff": MODULE_TEMP_COEFF,
        "module_temp_coeff_basis": MODULE_TEMP_COEFF_BASIS,
        "energy_channel": pvdaq_meta["energy_channel"],
        "analysis_window": pvdaq_meta["analysis_window"],
        "precipitation_source": pvdaq_meta["precipitation_source"],
    }
    return master, metadata


def analyze_pvdaq(master: pd.DataFrame) -> dict[str, Any]:
    """Run SPIS soiling + pollution analysis on a PVDAQ master table."""
    cleaning = _cleaning_params()
    washing = detect_inferred_cleaning_events(master, **cleaning)
    segments = build_soiling_segments(master, washing)
    master_clear = attach_clearness_index(master)
    segment_compare = compare_clear_sky_slopes(master_clear, segments)
    clear_pooled = canonical_clear_sky_pooled(segment_compare)
    daily_residual = build_daily_residual_frame(master_clear, segments)
    pollution = pollution_daily_tests(daily_residual)
    pollution_summary = _pollution_summary(pollution)

    ci_lower = clear_pooled["pooled_ci_lower"]
    ci_upper = clear_pooled["pooled_ci_upper"]
    signal_recoverable = (
        pd.notna(ci_lower)
        and pd.notna(ci_upper)
        and ci_lower < 0.0
        and ci_upper < 0.0
    )

    return {
        "site_key": PVDAQ_2107_SITE_KEY,
        "site_label": get_site(PVDAQ_2107_SITE_KEY).name,
        "segments": segments,
        "clear_pooled": clear_pooled,
        "segment_compare": segment_compare,
        "pollution": pollution,
        "pollution_summary": pollution_summary,
        "daily_residual": daily_residual,
        "inferred_cleaning_events": len(washing),
        "signal_recoverable": signal_recoverable,
    }


def utility_comparison_table(
    canakkale: dict[str, Any],
    pvdaq: dict[str, Any],
) -> pd.DataFrame:
    """Headline metrics for Canakkale vs PVDAQ 2107."""
    rows: list[dict[str, Any]] = []
    for block, label in (
        (canakkale, canakkale.get("site_label", "Canakkale Hybrid GES")),
        (pvdaq, pvdaq["site_label"]),
    ):
        clear = block["clear_pooled"]
        poll = block["pollution_summary"]
        rows.append(
            {
                "site": label,
                "site_key": block["site_key"],
                "clear_sky_rate_pct_per_day": clear["pooled_rate"],
                "clear_sky_ci_lower": clear["pooled_ci_lower"],
                "clear_sky_ci_upper": clear["pooled_ci_upper"],
                "ci_method": clear["ci_method"],
                "ci_width_pct_per_day": (
                    float(clear["pooled_ci_upper"] - clear["pooled_ci_lower"])
                    if pd.notna(clear["pooled_ci_lower"])
                    else float("nan")
                ),
                "signal_recoverable": block.get("signal_recoverable", True),
                "pm10_hac_p": poll["pm10_p"],
                "dust_hac_p": poll["dust_p"],
                "pollution_significant": poll["pollution_significant"],
                "inferred_cleaning_events": block.get("inferred_cleaning_events"),
            }
        )
    return pd.DataFrame(rows)


def pvdaq_verdict_text(table: pd.DataFrame, meta: dict[str, Any]) -> str:
    """Plain-language verdict for utility-scale external validation."""
    can = table.loc[table["site_key"] == CANAKKALE_SITE_KEY].iloc[0]
    pv = table.loc[table["site_key"] == PVDAQ_2107_SITE_KEY].iloc[0]

    can_rate = float(can["clear_sky_rate_pct_per_day"])
    can_lo = float(can["clear_sky_ci_lower"])
    can_hi = float(can["clear_sky_ci_upper"])
    pv_rate = float(pv["clear_sky_rate_pct_per_day"])
    pv_lo = float(pv["clear_sky_ci_lower"])
    pv_hi = float(pv["clear_sky_ci_upper"])
    pv_recoverable = bool(pv["signal_recoverable"])
    can_pm10_p = float(can["pm10_hac_p"]) if pd.notna(can["pm10_hac_p"]) else float("nan")
    pv_pm10_p = float(pv["pm10_hac_p"]) if pd.notna(pv["pm10_hac_p"]) else float("nan")

    window = meta["analysis_window"]
    parts = [
        "PVDAQ 2107 (893 kWdc Farm Solar Array, Arbuckle CA, Csa dry-summer agricultural) "
        f"analysis window {window['analysis_start']} .. {window['analysis_end']} "
        f"({window['days_total']} days with adequate 15-min coverage).",
        f"Canakkale clear-sky rate {can_rate:.4f} %/day "
        f"(CI [{can_lo:.4f}, {can_hi:.4f}]); "
        f"PVDAQ {pv_rate:.4f} %/day (CI [{pv_lo:.4f}, {pv_hi:.4f}]).",
    ]

    if pv_recoverable:
        parts.append(
            "Unlike the inconclusive DKASC research arrays, PVDAQ shows a recoverable "
            "negative clear-sky soiling signal (CI entirely below zero) consistent with "
            "seasonal dust accumulation on a utility-scale agricultural plant."
        )
    elif pv_lo < 0.0 < pv_hi:
        parts.append(
            "PVDAQ clear-sky soiling CI spans zero — the utility-scale signal is not "
            "fully recoverable under inferred-cleaning segmentation despite the dry "
            "Csa climate; interpret with cleaning-inference and POA sensor caveats."
        )
    else:
        parts.append(
            "PVDAQ does not show a clearly recoverable negative soiling CI under the "
            "current inferred-cleaning setup; report honestly without overclaiming."
        )

    parts.append(
        f"Pollution HAC: Canakkale PM10 p={can_pm10_p:.3f}, PVDAQ PM10 p={pv_pm10_p:.3f} "
        "(accumulated CAMS spec after segment detrending)."
    )
    parts.append(
        "No operator wash log at PVDAQ; cleanings inferred from NASA precipitation and "
        "PI step recoveries only."
    )
    return " ".join(parts)


def append_pvdaq_to_external_validation_report(
    table: pd.DataFrame,
    verdict: str,
    meta: dict[str, Any],
) -> None:
    """Append PVDAQ 2107 section to reports/EXTERNAL_VALIDATION.md."""
    path = config.REPORTS / "EXTERNAL_VALIDATION.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "## PVDAQ 2107 utility-scale validation" in existing:
        existing = existing.split("## PVDAQ 2107 utility-scale validation")[0].rstrip()

    lines = [
        "",
        "## PVDAQ 2107 utility-scale validation",
        "",
        verdict,
        "",
        f"CI method: `{CANONICAL_CI_METHOD}` (same as Canakkale P4).",
        "",
        "### Canakkale vs PVDAQ 2107",
        "",
        "| Site | Clear-sky rate (%/day) | 95% CI | CI width | Recoverable signal? | "
        "PM10 p | Dust p | Inferred cleanings |",
        "|---|---:|---|---:|---|---:|---:|---:|",
    ]
    for _, row in table.iterrows():
        recoverable = "yes" if row.get("signal_recoverable") else "no"
        cleanings = (
            ""
            if pd.isna(row.get("inferred_cleaning_events"))
            else str(int(row["inferred_cleaning_events"]))
        )
        ci_w = row.get("ci_width_pct_per_day", float("nan"))
        lines.append(
            f"| {row['site']} | {row['clear_sky_rate_pct_per_day']:.4f} | "
            f"[{row['clear_sky_ci_lower']:.4f}, {row['clear_sky_ci_upper']:.4f}] | "
            f"{ci_w:.4f} | {recoverable} | {row['pm10_hac_p']} | {row['dust_hac_p']} | "
            f"{cleanings} |"
        )

    lines.extend(
        [
            "",
            "### PVDAQ data access and channels",
            "",
            "- OEDI bucket: `oedi-data-lake`, prefix `pvdaq/2023-solar-data-prize/2107_OEDI/`",
            f"- System: {meta['pvdaq_meta']['site_facts']['public_name']} "
            f"({meta['pvdaq_meta']['site_facts']['dc_capacity_kw']} kWdc), "
            f"{meta['pvdaq_meta']['site_facts']['location']}, climate "
            f"{meta['pvdaq_meta']['site_facts']['climate_type']}.",
            f"- Energy: {meta['energy_channel']['selection_reason']}",
            f"- Precipitation: {meta['precipitation_source']}",
            f"- Module temp coeff: {meta['module_temp_coeff_basis']}",
            f"- Inferred cleaning (no wash log): rain >= "
            f"{meta['cleaning_params']['rain_mm']:.0f} mm, PI step >= "
            f"{meta['cleaning_params']['pi_step_pct']:.0f}%, min gap "
            f"{meta['cleaning_params']['min_days_between']} days.",
        ]
    )
    path.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Updated %s with PVDAQ section", path)


def run_pvdaq_validation(force_refresh: bool = False) -> dict[str, Any]:
    """Execute P17 Phase A utility-scale validation."""
    master, meta = build_pvdaq_master(force_refresh=force_refresh)
    pvdaq = analyze_pvdaq(master)
    canakkale = load_canakkale_baseline()
    canakkale["site_label"] = "Canakkale Hybrid GES"
    canakkale["signal_recoverable"] = True
    canakkale["inferred_cleaning_events"] = None

    table = utility_comparison_table(canakkale, pvdaq)
    verdict = pvdaq_verdict_text(table, meta)

    export = table.copy()
    export["record_type"] = "utility_comparison"
    export_rows = [export, pvdaq["pollution"].assign(record_type="pvdaq_pollution")]
    write_processed(
        PVDAQ_VALIDATION_OUTPUT,
        pd.concat(export_rows, ignore_index=True, sort=False),
        site_key=PVDAQ_2107_SITE_KEY,
    )
    write_processed(SOILING_OUTPUT_NAME, pvdaq["segments"], site_key=PVDAQ_2107_SITE_KEY)
    append_pvdaq_to_external_validation_report(table, verdict, meta)

    return {
        "table": table,
        "verdict": verdict,
        "meta": meta,
        "pvdaq": pvdaq,
        "canakkale": canakkale,
        "master": master,
    }
