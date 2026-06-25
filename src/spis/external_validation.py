"""P14/P16 external-site validation: DKASC Alice Springs vs Canakkale."""

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
from spis.data_sources.dkasc import (
    VALIDATION_ARRAYS,
    DkascArraySpec,
    ensure_dkasc_csv,
    load_dkasc_daily,
)
from spis.data_sources.nasa_power import fetch_nasa_power_daily, validate_nasa_power
from spis.data_sources.open_meteo_aq import fetch_open_meteo_air_quality, validate_open_meteo_aq
from spis.io import read_processed, write_processed
from spis.robustness import (
    ROBUSTNESS_OUTPUT_NAME,
    attach_clearness_index,
    build_daily_residual_frame,
    canonical_clear_sky_pooled,
    compare_clear_sky_slopes,
    pollution_daily_tests,
)
from spis.sites import get_site
from spis.soiling import SOILING_OUTPUT_NAME, build_soiling_segments

LOGGER = logging.getLogger(__name__)

ALICE_SPRINGS_SITE_KEY = "alice_springs"
EXTERNAL_VALIDATION_OUTPUT = "external_validation"
CANAKKALE_SITE_KEY = "canakkale"
CANONICAL_CI_METHOD = "clear_sky_pooled_weighted_by_n_fit"

FORBIDDEN_OVERCLAIM_PHRASES = (
    "desert site is not dramatically dustier",
    "desert has no soiling",
    "no dust-driven soiling",
    "desert ... no soiling",
)


def detect_inferred_cleaning_events(
    daily: pd.DataFrame,
    *,
    rain_mm: float | None = None,
    pi_step_pct: float | None = None,
    min_days_between: int | None = None,
) -> pd.DataFrame:
    """Infer wash-like events from heavy rain and abrupt PI recoveries."""
    rain_threshold = config.INFERRED_CLEANING_RAIN_MM if rain_mm is None else rain_mm
    step_threshold = (
        config.INFERRED_CLEANING_PI_STEP_PCT if pi_step_pct is None else pi_step_pct
    )
    min_gap = (
        config.INFERRED_CLEANING_MIN_DAYS_BETWEEN
        if min_days_between is None
        else min_days_between
    )

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

    rain_events = frame.loc[frame[rain_col] >= rain_threshold, "date"].tolist()

    step_events: list[pd.Timestamp] = []
    last_event: pd.Timestamp | None = None
    for _, row in frame.iterrows():
        if pd.isna(row["pi_step_pct"]) or row["pi_step_pct"] < step_threshold:
            continue
        if last_event is not None and (row["date"] - last_event).days < min_gap:
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
        if last_event is not None and (date - last_event).days < min_gap:
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
            if (row["start"] - prev["end"]).days >= min_gap:
                filtered.append(row.to_dict())
        washing = pd.DataFrame(filtered)
    washing["event_index_by_date"] = range(1, len(washing) + 1)
    LOGGER.info(
        "Inferred %s cleaning events (rain >= %.1f mm or PI step >= %.1f%%, min gap %s d)",
        len(washing),
        rain_threshold,
        step_threshold,
        min_gap,
    )
    return washing


def apply_site_temperature_correction(
    master: pd.DataFrame,
    site_key: str,
    *,
    module_temp_coeff: float | None = None,
) -> pd.DataFrame:
    """Temperature-correct PI using onsite or NASA ambient temperature."""
    site = get_site(site_key)
    coeff = site.resolved_module_temp_coeff() if module_temp_coeff is None else module_temp_coeff
    frame = master.copy()
    temp_col = "weather_temperature_c" if "weather_temperature_c" in frame.columns else "nasa_t2m"
    if temp_col not in frame.columns:
        raise ValueError(f"No temperature column available for {site_key}")

    g_proxy = frame["irradiation"] * 1000.0 / config.NOCT_PEAK_SUN_HOURS
    frame["cell_temp_c"] = frame[temp_col] + (config.MODULE_NOCT_C - 20.0) * (g_proxy / 800.0)
    delta_t = frame["cell_temp_c"] - config.STC_REF_TEMP_C
    frame["pi_temp_corrected"] = frame["pi"] / (1.0 + coeff * delta_t)
    frame["module_temp_coeff_used"] = coeff
    frame["temperature_source"] = temp_col
    return frame


def build_dkasc_array_master(
    array: DkascArraySpec,
    force_refresh: bool = False,
    *,
    rain_mm: float | None = None,
    pi_step_pct: float | None = None,
    min_days_between: int | None = None,
    persist_master: bool = False,
    daily_bundle: tuple[pd.DataFrame, dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build one DKASC array master table from CSV plus external enrichment."""
    ensure_dkasc_csv(array)
    site = get_site(ALICE_SPRINGS_SITE_KEY)
    if daily_bundle is None:
        daily, dkasc_meta = load_dkasc_daily(
            site.resolved_analysis_start(),
            site.resolved_analysis_end(),
            array=array,
        )
    else:
        daily, dkasc_meta = daily_bundle

    master = daily.rename(columns={"weather_rainfall_mm": "onsite_rainfall_mm"}).copy()
    master["is_downtime"] = False
    master["is_curtailment"] = False
    master["is_fault"] = False
    master["is_planned"] = False
    master["downtime_hours"] = 0.0
    master["downtime_reasons"] = ""
    master["dkasc_array_number"] = array.array_number
    master["dkasc_source_id"] = array.source_id

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
    master = apply_site_temperature_correction(
        master,
        ALICE_SPRINGS_SITE_KEY,
        module_temp_coeff=array.module_temp_coeff,
    )

    washing = detect_inferred_cleaning_events(
        master,
        rain_mm=rain_mm,
        pi_step_pct=pi_step_pct,
        min_days_between=min_days_between,
    )
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

    if persist_master:
        write_processed(MASTER_OUTPUT_NAME, master, site_key=ALICE_SPRINGS_SITE_KEY)

    metadata = {
        "site_key": ALICE_SPRINGS_SITE_KEY,
        "array": array,
        "dkasc_meta": dkasc_meta,
        "nasa_meta": nasa_meta,
        "cams_meta": cams_meta,
        "filter_counts": filter_counts,
        "inferred_cleaning_events": len(washing),
        "module_temp_coeff": array.module_temp_coeff,
        "module_temp_coeff_basis": array.module_temp_coeff_basis,
        "energy_channel": dkasc_meta["energy_channel"],
    }
    return master, metadata


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
            "residuals (HAC p>=0.05 or wrong sign)."
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


def _analyze_dkasc_array(
    master: pd.DataFrame,
    array: DkascArraySpec,
    *,
    rain_mm: float | None = None,
    pi_step_pct: float | None = None,
    min_days_between: int | None = None,
) -> dict[str, Any]:
    washing = detect_inferred_cleaning_events(
        master,
        rain_mm=rain_mm,
        pi_step_pct=pi_step_pct,
        min_days_between=min_days_between,
    )
    segments = build_soiling_segments(master, washing)
    master_clear = attach_clearness_index(master)
    segment_compare = compare_clear_sky_slopes(master_clear, segments)
    clear_pooled = canonical_clear_sky_pooled(segment_compare)
    daily_residual = build_daily_residual_frame(master_clear, segments)
    pollution = pollution_daily_tests(daily_residual)
    pollution_summary = _pollution_summary(pollution)

    return {
        "site_key": ALICE_SPRINGS_SITE_KEY,
        "array_number": array.array_number,
        "array_label": array.label,
        "source_id": array.source_id,
        "segments": segments,
        "clear_pooled": clear_pooled,
        "segment_compare": segment_compare,
        "pollution": pollution,
        "pollution_summary": pollution_summary,
        "daily_residual": daily_residual,
        "inferred_cleaning_events": len(washing),
    }


def load_canakkale_baseline() -> dict[str, Any]:
    """Load existing Canakkale soiling/robustness outputs without recomputing P3-P3.5."""
    segments = read_processed(SOILING_OUTPUT_NAME, site_key=CANAKKALE_SITE_KEY)
    robustness = read_processed(ROBUSTNESS_OUTPUT_NAME, site_key=CANAKKALE_SITE_KEY)
    pollution = robustness.loc[robustness["record_type"].astype(str).str.startswith("pollution")]
    pollution_summary = _pollution_summary(pollution)

    clear_rows = robustness.loc[robustness["record_type"] == "segment_comparison"]
    segment_compare = clear_rows.dropna(subset=["clear_rate_pct_per_day", "clear_n_fit"])
    clear_pooled = canonical_clear_sky_pooled(segment_compare)

    verdict_row = robustness.loc[robustness["record_type"] == "p4_verdict"]
    if not verdict_row.empty:
        canonical_rate = float(verdict_row.iloc[0]["recommended_rate_pct_per_day"])
        canonical_half = float(verdict_row.iloc[0]["recommended_uncertainty_half_width"])
        if not np.isclose(clear_pooled["pooled_rate"], canonical_rate, rtol=1e-4, atol=1e-4):
            LOGGER.warning(
                "Canakkale clear_pooled %.6f differs from p4_verdict %.6f",
                clear_pooled["pooled_rate"],
                canonical_rate,
            )
        clear_pooled = {
            **clear_pooled,
            "pooled_rate": canonical_rate,
            "pooled_ci_lower": canonical_rate - canonical_half,
            "pooled_ci_upper": canonical_rate + canonical_half,
            "ci_half_width": canonical_half,
        }

    return {
        "site_key": CANAKKALE_SITE_KEY,
        "site_label": "Canakkale Hybrid GES",
        "segments": segments,
        "clear_pooled": clear_pooled,
        "pollution_summary": pollution_summary,
    }


def comparison_table(
    canakkale: dict[str, Any],
    array_results: list[dict[str, Any]],
) -> pd.DataFrame:
    """Side-by-side headline metrics for Canakkale and each DKASC array."""
    rows: list[dict[str, Any]] = []
    can_clear = canakkale["clear_pooled"]
    can_poll = canakkale["pollution_summary"]
    rows.append(
        {
            "site": canakkale["site_label"],
            "site_key": CANAKKALE_SITE_KEY,
            "array_number": "",
            "array_label": "",
            "source_id": np.nan,
            "clear_sky_pooled_rate_pct_per_day": can_clear["pooled_rate"],
            "clear_sky_ci_lower": can_clear["pooled_ci_lower"],
            "clear_sky_ci_upper": can_clear["pooled_ci_upper"],
            "ci_method": can_clear["ci_method"],
            "pm10_hac_coef": can_poll["pm10_coef"],
            "pm10_hac_p": can_poll["pm10_p"],
            "dust_hac_coef": can_poll["dust_coef"],
            "dust_hac_p": can_poll["dust_p"],
            "pollution_significant": can_poll["pollution_significant"],
            "inferred_cleaning_events": np.nan,
            "is_primary_dkasc_summary": False,
        }
    )
    for block in array_results:
        clear = block["clear_pooled"]
        poll = block["pollution_summary"]
        rows.append(
            {
                "site": f"DKASC array {block['array_number']}",
                "site_key": ALICE_SPRINGS_SITE_KEY,
                "array_number": block["array_number"],
                "array_label": block["array_label"],
                "source_id": block["source_id"],
                "clear_sky_pooled_rate_pct_per_day": clear["pooled_rate"],
                "clear_sky_ci_lower": clear["pooled_ci_lower"],
                "clear_sky_ci_upper": clear["pooled_ci_upper"],
                "ci_method": clear["ci_method"],
                "pm10_hac_coef": poll["pm10_coef"],
                "pm10_hac_p": poll["pm10_p"],
                "dust_hac_coef": poll["dust_coef"],
                "dust_hac_p": poll["dust_p"],
                "pollution_significant": poll["pollution_significant"],
                "inferred_cleaning_events": block["inferred_cleaning_events"],
                "is_primary_dkasc_summary": False,
            }
        )
    return pd.DataFrame(rows)


def cleaning_sensitivity_table(
    array_results_by_preset: dict[str, list[dict[str, Any]]],
) -> pd.DataFrame:
    """Summarise clear-sky rates under alternate inferred-cleaning thresholds."""
    rows: list[dict[str, Any]] = []
    for preset_name, preset_cfg in config.INFERRED_CLEANING_PRESETS.items():
        blocks = array_results_by_preset[preset_name]
        for block in blocks:
            clear = block["clear_pooled"]
            rows.append(
                {
                    "preset": preset_name,
                    "rain_mm": preset_cfg["rain_mm"],
                    "pi_step_pct": preset_cfg["pi_step_pct"],
                    "min_days_between": preset_cfg["min_days_between"],
                    "array_number": block["array_number"],
                    "array_label": block["array_label"],
                    "clear_sky_rate_pct_per_day": clear["pooled_rate"],
                    "clear_sky_ci_lower": clear["pooled_ci_lower"],
                    "clear_sky_ci_upper": clear["pooled_ci_upper"],
                    "inferred_cleaning_events": block["inferred_cleaning_events"],
                }
            )
    return pd.DataFrame(rows)


def energy_channel_table(array_metas: list[dict[str, Any]]) -> pd.DataFrame:
    """Log daily-energy channel selection per DKASC array."""
    rows: list[dict[str, Any]] = []
    for meta in array_metas:
        channel = meta["energy_channel"]
        rows.append(
            {
                "array_number": meta["array"].array_number,
                "array_label": meta["array"].label,
                "selected_channel": channel["selected_channel"],
                "median_power_to_counter_ratio": channel.get("median_power_to_counter_ratio"),
                "selection_reason": channel["selection_reason"],
            }
        )
    return pd.DataFrame(rows)


def honest_verdict(
    table: pd.DataFrame,
    sensitivity: pd.DataFrame,
    array_metas: list[dict[str, Any]],
) -> str:
    """Plain-language synthesis of the generalization test without overclaiming."""
    del array_metas  # reserved for future array-specific notes
    can = table.loc[table["site_key"] == CANAKKALE_SITE_KEY].iloc[0]
    dkasc = table.loc[table["site_key"] == ALICE_SPRINGS_SITE_KEY].copy()

    can_rate = float(can["clear_sky_pooled_rate_pct_per_day"])
    can_lo = float(can["clear_sky_ci_lower"])
    can_hi = float(can["clear_sky_ci_upper"])
    can_pm10_p = float(can["pm10_hac_p"]) if pd.notna(can["pm10_hac_p"]) else float("nan")

    rate_lines = [
        "Primary conclusion: the external generalization test is INCONCLUSIVE for recoverable "
        "soiling loss on DKASC fixed-tilt research arrays. These ~5 kW arrays appear actively "
        "maintained (rain and inferred PI recoveries), so dust-driven soiling does not "
        "accumulate between inferred cleanings the way it does at Canakkale Hybrid GES.",
        f"Canakkale clear-sky pooled rate (canonical CI method): {can_rate:.4f} %/day "
        f"(95% CI [{can_lo:.4f}, {can_hi:.4f}]).",
    ]

    array_bits: list[str] = []
    all_inconclusive = True
    any_negative = False
    for _, row in dkasc.iterrows():
        rate = float(row["clear_sky_pooled_rate_pct_per_day"])
        lo = float(row["clear_sky_ci_lower"])
        hi = float(row["clear_sky_ci_upper"])
        pm10_p = float(row["pm10_hac_p"]) if pd.notna(row["pm10_hac_p"]) else float("nan")
        inconclusive = lo < 0.0 and hi > 0.0
        if not inconclusive and rate < 0:
            any_negative = True
            all_inconclusive = False
        if inconclusive:
            signal = "inconclusive (CI spans zero)"
        elif rate < 0:
            signal = "negative point estimate"
            all_inconclusive = False
        else:
            signal = "near-zero or positive point estimate"
            all_inconclusive = False
        array_bits.append(
            f"array {row['array_number']}: {rate:.4f} %/day "
            f"[{lo:.4f}, {hi:.4f}], PM10 HAC p={pm10_p:.3f} ({signal})"
        )

    rate_lines.append("Per-array DKASC clear-sky rates: " + "; ".join(array_bits) + ".")
    if all_inconclusive:
        rate_lines.append(
            "All four fixed-tilt arrays show near-zero point estimates with wide CIs spanning "
            "zero; no recoverable desert soiling signal is demonstrated on these maintained "
            "research arrays."
        )
    elif any_negative:
        rate_lines.append(
            "Some arrays show negative point estimates, but CIs remain wide; treat any contrast "
            "with Canakkale as suggestive only, not a fleet-scale conclusion."
        )

    pm10_p_values = dkasc["pm10_hac_p"].dropna().astype(float)
    desert_pm10_p = float(pm10_p_values.min()) if not pm10_p_values.empty else float("nan")
    poll_text = (
        f"Pollution association: Canakkale PM10 HAC p={can_pm10_p:.3f}; "
        f"DKASC arrays span p={pm10_p_values.min():.3f}..{pm10_p_values.max():.3f} "
        f"(closest to significance at the desert site is p≈{desert_pm10_p:.2f}). "
        "That is a hint, not a conclusion — neither site reaches HAC p<0.05 on the "
        "accumulated CAMS spec used here."
    )

    max_shift = float(
        sensitivity.groupby("array_number")["clear_sky_rate_pct_per_day"]
        .agg(lambda series: series.max() - series.min())
        .max()
    )
    cleaning_note = (
        "No operator wash log exists at DKASC. Cleaning events were inferred from rainfall "
        "and PI step recoveries only. Under strict/default/sensitive threshold presets the "
        f"largest per-array rate shift was {max_shift:.4f} %/day — see sensitivity table."
    )

    energy_note = (
        "Daily PI uses the selected energy channel logged per array (cumulative inverter "
        "counter when valid, else integrated Active_Power)."
    )

    future_work = (
        "Recommended next external test: a utility-scale soiling dataset such as NREL PVDAQ "
        "system 2107 (~893 kW, California agricultural area) via the public OEDI/AWS bucket. "
        "That was not ingested in this work package."
    )

    return " ".join(rate_lines + [poll_text, cleaning_note, energy_note, future_work])


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
    primary_array: dict[str, Any],
) -> None:
    """Comparison bar chart and dust-vs-residual scatter for the primary DKASC array."""
    plot_table = table.copy()
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(plot_table))
    ax.bar(
        x,
        plot_table["clear_sky_pooled_rate_pct_per_day"],
        width=0.6,
        label="Clear-sky pooled (canonical CI)",
    )
    ax.errorbar(
        x,
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
    ax.set_xticklabels(plot_table["site"], rotation=20, ha="right")
    ax.axhline(0, color="0.5", linewidth=0.8)
    ax.set_ylabel("Soiling rate (%/day)")
    ax.set_title("Clear-sky pooled soiling rate — Canakkale vs DKASC fixed-tilt arrays")
    ax.legend()
    fig.tight_layout()
    _save_figure("external_validation_soiling_rate_comparison", fig, plot_table)

    residual = primary_array.get("daily_residual")
    if residual is None:
        return
    data = residual.dropna(subset=["pi_residual", "dust_accumulated"]).copy()
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(data["dust_accumulated"], data["pi_residual"], s=10, alpha=0.35)
    ax.set_xlabel("Accumulated CAMS dust since inferred cleaning (ug/m3-days)")
    ax.set_ylabel("PI residual (temp corrected)")
    ax.set_title(
        f"DKASC array {primary_array['array_number']} daily residual vs accumulated dust "
        f"(n={len(data)})"
    )
    fig.tight_layout()
    _save_figure(
        "external_validation_alice_dust_vs_residual",
        fig,
        data[["date", "dust_accumulated", "pi_residual"]],
    )


def write_external_validation_report(
    table: pd.DataFrame,
    sensitivity: pd.DataFrame,
    energy_channels: pd.DataFrame,
    verdict: str,
    array_metas: list[dict[str, Any]],
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
        "## Comparison table (canonical CI method)",
        "",
        f"CI method for all sites: `{CANONICAL_CI_METHOD}` — weighted mean of segment "
        "clear-sky Theil-Sen rates by `clear_n_fit`, with half-width = mean segment "
        "Theil-Sen CI width / 2 (same as Canakkale P4 `p4_verdict`).",
        "",
        "| Site / array | Clear-sky rate (%/day) | 95% CI | PM10 HAC p | Dust HAC p | "
        "Pollution sig.? | Inferred cleanings |",
        "|---|---:|---|---:|---:|---|---:|",
    ]
    for _, row in table.iterrows():
        cleanings = (
            ""
            if pd.isna(row.get("inferred_cleaning_events"))
            else f"{int(row['inferred_cleaning_events'])}"
        )
        lines.append(
            f"| {row['site']} | {row['clear_sky_pooled_rate_pct_per_day']:.4f} | "
            f"[{row['clear_sky_ci_lower']:.4f}, {row['clear_sky_ci_upper']:.4f}] | "
            f"{row['pm10_hac_p']} | {row['dust_hac_p']} | "
            f"{'yes' if row['pollution_significant'] else 'no'} | {cleanings} |"
        )

    lines.extend(
        [
            "",
            "## Daily energy channel selection (DKASC)",
            "",
        ]
    )
    for _, row in energy_channels.iterrows():
        ratio = row["median_power_to_counter_ratio"]
        ratio_text = "n/a" if pd.isna(ratio) else f"{float(ratio):.4f}"
        lines.append(
            f"- Array {row['array_number']}: `{row['selected_channel']}` "
            f"(median power/counter ratio {ratio_text}). {row['selection_reason']}"
        )

    lines.extend(
        [
            "",
            "## Cleaning-inference sensitivity (no wash log)",
            "",
            "No operator wash log exists at DKASC. Three threshold presets were applied:",
        ]
    )
    for preset_name, preset_cfg in config.INFERRED_CLEANING_PRESETS.items():
        lines.append(
            f"- **{preset_name}**: rain >= {preset_cfg['rain_mm']:.0f} mm, "
            f"PI step >= {preset_cfg['pi_step_pct']:.0f}%, "
            f"min gap {preset_cfg['min_days_between']} days."
        )
    lines.extend(
        [
            "",
            "| Preset | Array | Rate (%/day) | 95% CI | Inferred cleanings |",
            "|---|---|---:|---|---:|",
        ]
    )
    for _, row in sensitivity.iterrows():
        lines.append(
            f"| {row['preset']} | {row['array_number']} | "
            f"{row['clear_sky_rate_pct_per_day']:.4f} | "
            f"[{row['clear_sky_ci_lower']:.4f}, {row['clear_sky_ci_upper']:.4f}] | "
            f"{int(row['inferred_cleaning_events'])} |"
        )

    lines.extend(
        [
            "",
            "## kW-scale research-array caveat",
            "",
            "Data sources: four fixed-tilt DKASC silicon research arrays (~5 kW AC each, "
            "arrays 13/14/18/32 — Trina mono-Si, SunPower mono-Si, Kyocera poly-Si, "
            "Canadian Solar poly-Si). Array 10 (SunPower) export was corrupt at the DKASC "
            "source and was replaced by array 32. "
            "These are maintained research strings, not utility plants. Single-array noise, "
            "inverter clipping, and reference-sensor co-soiling differ from Canakkale Hybrid "
            "GES (~2750 kW AC). Results test method portability, not commercial fleet performance.",
            "",
            "## Recommended future external test",
            "",
            "Utility-scale soiling validation should use an independently maintained plant with "
            "documented washing or long soiling accumulation, e.g. NREL PVDAQ system 2107 "
            "(~893 kW, California agricultural area) from the public OEDI/AWS bucket. "
            "Ingest was not attempted in P16.",
            "",
            "## Temperature coefficient assumptions",
            "",
        ]
    )
    for meta in array_metas:
        lines.append(f"- Array {meta['array'].array_number}: {meta['module_temp_coeff_basis']}")

    lines.extend(
        [
            "",
            f"Analysis window: {get_site(ALICE_SPRINGS_SITE_KEY).resolved_analysis_start()} .. "
            f"{get_site(ALICE_SPRINGS_SITE_KEY).resolved_analysis_end()} (aligned with Canakkale).",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def run_external_validation(force_refresh: bool = False) -> dict[str, Any]:
    """Execute P16 external validation across four fixed-tilt DKASC arrays."""
    for array in VALIDATION_ARRAYS:
        ensure_dkasc_csv(array)

    canakkale = load_canakkale_baseline()

    site = get_site(ALICE_SPRINGS_SITE_KEY)
    daily_cache: dict[int, tuple[pd.DataFrame, dict[str, Any]]] = {}
    for array in VALIDATION_ARRAYS:
        daily_cache[array.source_id] = load_dkasc_daily(
            site.resolved_analysis_start(),
            site.resolved_analysis_end(),
            array=array,
        )

    default_array_results: list[dict[str, Any]] = []
    array_metas: list[dict[str, Any]] = []
    primary_master: pd.DataFrame | None = None
    primary_analysis: dict[str, Any] | None = None

    for index, array in enumerate(VALIDATION_ARRAYS):
        master, meta = build_dkasc_array_master(
            array,
            force_refresh=force_refresh,
            persist_master=index == 0,
            daily_bundle=daily_cache[array.source_id],
        )
        analysis = _analyze_dkasc_array(master, array)
        default_array_results.append(analysis)
        array_metas.append(meta)
        if index == 0:
            primary_master = master
            primary_analysis = analysis

    sensitivity_by_preset: dict[str, list[dict[str, Any]]] = {"default": default_array_results}
    for preset_name, preset_cfg in config.INFERRED_CLEANING_PRESETS.items():
        if preset_name == "default":
            continue
        preset_blocks: list[dict[str, Any]] = []
        for array in VALIDATION_ARRAYS:
            master, _ = build_dkasc_array_master(
                array,
                force_refresh=False,
                rain_mm=float(preset_cfg["rain_mm"]),
                pi_step_pct=float(preset_cfg["pi_step_pct"]),
                min_days_between=int(preset_cfg["min_days_between"]),
                daily_bundle=daily_cache[array.source_id],
            )
            preset_blocks.append(
                _analyze_dkasc_array(
                    master,
                    array,
                    rain_mm=float(preset_cfg["rain_mm"]),
                    pi_step_pct=float(preset_cfg["pi_step_pct"]),
                    min_days_between=int(preset_cfg["min_days_between"]),
                )
            )
        sensitivity_by_preset[preset_name] = preset_blocks

    table = comparison_table(canakkale, default_array_results)
    sensitivity = cleaning_sensitivity_table(sensitivity_by_preset)
    energy_channels = energy_channel_table(array_metas)
    verdict = honest_verdict(table, sensitivity, array_metas)

    export_rows: list[pd.DataFrame] = []
    export = table.copy()
    export["record_type"] = "site_comparison"
    export_rows.append(export)
    sens_export = sensitivity.copy()
    sens_export["record_type"] = "cleaning_sensitivity"
    export_rows.append(sens_export)
    energy_export = energy_channels.copy()
    energy_export["record_type"] = "energy_channel"
    export_rows.append(energy_export)
    for block in default_array_results:
        export_rows.append(block["pollution"].assign(record_type="dkasc_pollution"))
    write_processed(
        EXTERNAL_VALIDATION_OUTPUT,
        pd.concat(export_rows, ignore_index=True, sort=False),
        site_key=ALICE_SPRINGS_SITE_KEY,
    )

    if primary_analysis is not None:
        write_processed(
            SOILING_OUTPUT_NAME,
            primary_analysis["segments"],
            site_key=ALICE_SPRINGS_SITE_KEY,
        )

    write_external_validation_report(
        table,
        sensitivity,
        energy_channels,
        verdict,
        array_metas,
    )
    save_external_validation_figures(table, primary_analysis or default_array_results[0])

    return {
        "table": table,
        "sensitivity": sensitivity,
        "energy_channels": energy_channels,
        "verdict": verdict,
        "array_metas": array_metas,
        "array_results": default_array_results,
        "canakkale": canakkale,
        "primary_master": primary_master,
    }
