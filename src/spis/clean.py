"""Day-level master table builder with external enrichment and quality flags.

Temperature correction uses a daily NOCT cell-temperature approximation:

    T_cell = T_amb + (NOCT - 20) * (G_proxy / 800)

where ``G_proxy`` converts NASA ALLSKY_SFC_SW_DWN (kWh/m²/day) to an average
daytime plane-of-array irradiance proxy (kWh/m²/day × 1000 / peak_sun_hours).
This is not an instantaneous POA measurement; it is a documented daily proxy for
ranking soiling slopes, not sub-hour cell physics.
"""

from __future__ import annotations

import logging
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from spis import config
from spis.data_sources.nasa_power import fetch_nasa_power_daily, validate_nasa_power
from spis.data_sources.open_meteo_aq import fetch_open_meteo_air_quality, validate_open_meteo_aq
from spis.io import read_interim, write_processed

LOGGER = logging.getLogger(__name__)

MASTER_OUTPUT_NAME = "master_daily"


def _normalize_text(text: str) -> str:
    """Fold Turkish characters to ASCII for tolerant reason matching."""
    folded = str(text).strip()
    for src, dst in {
        "ı": "i",
        "İ": "i",
        "I": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }.items():
        folded = folded.replace(src, dst)
    return folded.lower()


def build_master_spine(irradiance: pd.DataFrame) -> pd.DataFrame:
    """Create a complete daily date spine joined to irradiance metrics."""
    expected = pd.date_range(
        config.IRRADIANCE_START_DATE,
        config.IRRADIANCE_END_DATE,
        freq="D",
    )
    spine = pd.DataFrame({"date": expected})
    merged = spine.merge(irradiance, on="date", how="left", validate="one_to_one")
    if merged[["production", "irradiation", "pi"]].isna().any().any():
        raise ValueError("Master spine join left nulls in core production columns")
    LOGGER.info("Master spine: %s rows, complete daily index", len(merged))
    return merged


def join_downtime_flags(master: pd.DataFrame, downtime_days: pd.DataFrame) -> pd.DataFrame:
    """Aggregate downtime day rows into boolean flags and hour totals."""
    if downtime_days.empty:
        master = master.copy()
        master["is_downtime"] = False
        master["is_curtailment"] = False
        master["is_fault"] = False
        master["is_planned"] = False
        master["downtime_hours"] = 0.0
        master["downtime_reasons"] = ""
        return master

    working = downtime_days.copy()
    norm_reason = working["reason"].map(_normalize_text)
    working["is_curtailment"] = norm_reason.str.contains("kisitlama")
    working["is_fault"] = norm_reason.str.contains("ariza")
    working["is_planned"] = norm_reason.str.contains("planli") | norm_reason.str.contains("yillik")

    grouped = (
        working.groupby("date", as_index=False)
        .agg(
            downtime_hours=("duration_hours", "sum"),
            is_curtailment=("is_curtailment", "any"),
            is_fault=("is_fault", "any"),
            is_planned=("is_planned", "any"),
            downtime_reasons=("reason", lambda values: ";".join(sorted(set(values)))),
        )
        .assign(is_downtime=True)
    )

    merged = master.merge(grouped, on="date", how="left")
    for column in ("is_downtime", "is_curtailment", "is_fault", "is_planned"):
        merged[column] = merged[column].fillna(False).astype(bool)
    merged["downtime_hours"] = merged["downtime_hours"].fillna(0.0)
    merged["downtime_reasons"] = merged["downtime_reasons"].fillna("")
    LOGGER.info(
        "Downtime join: %s downtime days flagged on master spine",
        int(merged["is_downtime"].sum()),
    )
    return merged


def join_washing_segments(master: pd.DataFrame, washing: pd.DataFrame) -> pd.DataFrame:
    """Assign wash segment metadata and days_since_wash with explicit edge flags."""
    events = washing.sort_values("start").reset_index(drop=True)
    frame = master.copy()
    first_start = events.iloc[0]["start"]
    last_end = events.iloc[-1]["end"]

    frame["pre_first_wash"] = frame["date"] < first_start
    frame["is_open_segment"] = frame["date"] > last_end
    frame["segment_id"] = pd.NA
    frame["washing_method"] = pd.NA
    frame["days_since_wash"] = pd.NA

    frame.loc[frame["pre_first_wash"], "segment_id"] = 0

    for idx in range(len(events)):
        event = events.iloc[idx]
        segment_id = int(event["event_index_by_date"])
        wash_mask = (frame["date"] >= event["start"]) & (frame["date"] <= event["end"])
        frame.loc[wash_mask, "segment_id"] = segment_id
        frame.loc[wash_mask, "washing_method"] = event["method"]
        frame.loc[wash_mask, "days_since_wash"] = 0

        if idx < len(events) - 1:
            next_start = events.iloc[idx + 1]["start"]
            mask = (frame["date"] > event["end"]) & (frame["date"] < next_start)
        else:
            mask = frame["date"] > event["end"]

        frame.loc[mask, "segment_id"] = segment_id
        frame.loc[mask, "washing_method"] = event["method"]
        frame.loc[mask, "days_since_wash"] = (frame.loc[mask, "date"] - event["end"]).dt.days

    frame["segment_id"] = frame["segment_id"].astype("Int64")
    frame["days_since_wash"] = frame["days_since_wash"].astype("Int64")
    LOGGER.info(
        "Washing join: %s pre-first-wash days, %s open-segment days",
        int(frame["pre_first_wash"].sum()),
        int(frame["is_open_segment"].sum()),
    )
    return frame


def compute_low_irradiation_cutoff(irradiation: pd.Series) -> float:
    """Derive the low-irradiation exclusion threshold from the SCADA distribution."""
    cutoff = float(irradiation.quantile(config.LOW_IRRADIATION_PERCENTILE))
    LOGGER.info(
        "Low-irradiation cutoff: %.3f (%0.0f%% percentile of SCADA irradiation)",
        cutoff,
        config.LOW_IRRADIATION_PERCENTILE * 100,
    )
    return cutoff


def apply_temperature_correction(master: pd.DataFrame) -> pd.DataFrame:
    """Estimate cell temperature via NOCT and compute temperature-corrected PI."""
    frame = master.copy()
    g_proxy = frame["nasa_allsky_kwh_m2"] * 1000.0 / config.NOCT_PEAK_SUN_HOURS
    frame["cell_temp_c"] = frame["nasa_t2m"] + (config.MODULE_NOCT_C - 20.0) * (g_proxy / 800.0)
    delta_t = frame["cell_temp_c"] - config.STC_REF_TEMP_C
    frame["pi_temp_corrected"] = frame["pi"] / (1.0 + config.MODULE_PMAX_TEMP_COEFF * delta_t)
    return frame


def join_external(master: pd.DataFrame, nasa: pd.DataFrame, cams: pd.DataFrame) -> pd.DataFrame:
    """Left-join NASA POWER and CAMS daily features onto the master spine."""
    nasa = nasa.rename(
        columns={
            "t2m": "nasa_t2m",
            "t2m_max": "nasa_t2m_max",
            "ws2m": "nasa_ws2m",
            "prectotcorr": "nasa_precip_mm",
            "allsky_sfc_sw_dwn": "nasa_allsky_kwh_m2",
        }
    )
    merged = master.merge(nasa, on="date", how="left", validate="one_to_one")
    merged = merged.merge(cams, on="date", how="left", validate="one_to_one")
    return merged


def add_quality_flags(master: pd.DataFrame, cutoff: float) -> tuple[pd.DataFrame, dict[str, int]]:
    """Add rain_day, low_irradiation, and is_clean_observation with filter counts."""
    frame = master.copy()
    if "low_irradiation" not in frame.columns:
        frame["low_irradiation"] = frame["irradiation"] < cutoff
    frame["rain_day"] = frame["nasa_precip_mm"] >= config.RAIN_DAY_PRECIP_MM
    frame["is_clean_observation"] = (
        ~frame["is_downtime"]
        & ~frame["is_curtailment"]
        & ~frame["is_fault"]
        & ~frame["low_irradiation"]
        & ~frame["rain_day"]
    )

    total = len(frame)
    clean = int(frame["is_clean_observation"].sum())
    filter_counts = {
        "total_days": total,
        "is_clean_observation": clean,
        "removed_downtime": int(frame["is_downtime"].sum()),
        "removed_curtailment": int(frame["is_curtailment"].sum()),
        "removed_fault": int(frame["is_fault"].sum()),
        "removed_low_irradiation": int(frame["low_irradiation"].sum()),
        "removed_rain_day": int(frame["rain_day"].sum()),
        "removed_any_exclusion": total - clean,
    }
    LOGGER.info("Clean observation filter counts: %s", filter_counts)
    return frame, filter_counts


def document_scada_nasa_units(master: pd.DataFrame) -> dict[str, float]:
    """Cross-check SCADA irradiation magnitude against NASA ALLSKY_SFC_SW_DWN."""
    valid = master.dropna(subset=["irradiation", "nasa_allsky_kwh_m2"])
    scada_as_kwh = valid["irradiation"] / 1000.0
    ratio = (scada_as_kwh / valid["nasa_allsky_kwh_m2"]).median()
    stats = {
        "scada_irradiation_median": float(valid["irradiation"].median()),
        "nasa_allsky_median_kwh_m2": float(valid["nasa_allsky_kwh_m2"].median()),
        "median_ratio_scada_wh_over_nasa_kwh": float(ratio),
    }
    LOGGER.info(
        "SCADA-vs-NASA units check: SCADA median %.1f, NASA %.2f kWh/m2/day, "
        "ratio (SCADA/1000)/NASA median %.3f -> SCADA likely %s",
        stats["scada_irradiation_median"],
        stats["nasa_allsky_median_kwh_m2"],
        stats["median_ratio_scada_wh_over_nasa_kwh"],
        config.SCADA_IRRADIATION_UNITS,
    )
    return stats


def save_temp_correction_figure(master: pd.DataFrame) -> None:
    """Save a comparison of raw vs temperature-corrected PI rolling means."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    plot_frame = master.sort_values("date").copy()
    plot_frame["pi_14d"] = plot_frame["pi"].rolling(14, min_periods=7).mean()
    plot_frame["pi_temp_corrected_14d"] = (
        plot_frame["pi_temp_corrected"].rolling(14, min_periods=7).mean()
    )

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(plot_frame["date"], plot_frame["pi_14d"], label="PI 14d mean")
    ax.plot(
        plot_frame["date"],
        plot_frame["pi_temp_corrected_14d"],
        label="PI temp-corrected 14d mean",
    )
    ax.set_title("Raw vs temperature-corrected PI (14-day rolling mean)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Performance index")
    ax.legend()
    fig.tight_layout()

    png_path = config.FIGURES / "pi_temp_correction_comparison.png"
    csv_path = config.FIGURES / "pi_temp_correction_comparison.csv"
    fig.savefig(png_path, dpi=300)
    plt.close(fig)
    plot_frame[["date", "pi", "pi_temp_corrected", "pi_14d", "pi_temp_corrected_14d"]].to_csv(
        csv_path, index=False
    )
    LOGGER.info("Saved temperature correction figure to %s", png_path)


def build_master_table() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the analysis-ready day-level master table from P1 interim artifacts."""
    irradiance = read_interim("irradiance_daily")
    downtime_days = read_interim("downtime_days")
    washing = read_interim("washing_events")

    nasa, nasa_meta = fetch_nasa_power_daily()
    cams, cams_meta = fetch_open_meteo_air_quality()
    validate_nasa_power(nasa)
    validate_open_meteo_aq(cams)

    master = build_master_spine(irradiance)
    master = join_downtime_flags(master, downtime_days)
    master = join_external(master, nasa, cams)
    master = join_washing_segments(master, washing)

    cutoff = compute_low_irradiation_cutoff(master["irradiation"])
    master = apply_temperature_correction(master)
    master, filter_counts = add_quality_flags(master, cutoff)
    unit_stats = document_scada_nasa_units(master)
    save_temp_correction_figure(master)

    write_processed(MASTER_OUTPUT_NAME, master)

    metadata = {
        "rows": len(master),
        "low_irradiation_cutoff": cutoff,
        "filter_counts": filter_counts,
        "unit_cross_check": unit_stats,
        "nasa_meta": nasa_meta,
        "cams_meta": cams_meta,
    }
    return master, metadata
