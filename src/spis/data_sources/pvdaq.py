"""PVDAQ system 2107 (Farm Solar Array, Arbuckle CA) loader from public OEDI S3."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from spis import config

LOGGER = logging.getLogger(__name__)

OEDI_BASE = "https://oedi-data-lake.s3.amazonaws.com"
OEDI_PREFIX = "pvdaq/2023-solar-data-prize/2107_OEDI"
PVDAQ_DIR = config.DATA_EXTERNAL / "pvdaq" / "2107"
SYSTEM_ID = 2107
METADATA_KEY = f"{OEDI_PREFIX}/metadata/2107_system_metadata.json"
METADATA_LOCAL = PVDAQ_DIR / "2107_system_metadata.json"
INTERVAL_MINUTES = 15

# Mapped from metadata/2107_system_metadata.json Metrics block (125 channels total).
CHANNEL_MAP: dict[str, str] = {
    "timestamp": "measured_on",
    "ac_power_kw": "meter_revenue_grade_ac_output_meter_149578",
    "poa_wm2": "poa_irradiance_o_149574",
    "ambient_temp_f": "ambient_temperature_o_149575",
}

DATA_FILE_SPECS: tuple[tuple[str, str], ...] = (
    ("meter", f"{OEDI_PREFIX}/data/2107_meter_15m_data.csv"),
    ("meter_2024", f"{OEDI_PREFIX}/data/2107_meter_15m_data_2024.csv"),
    ("irradiance", f"{OEDI_PREFIX}/data/2107_irradiance_data.csv"),
    ("irradiance_2024", f"{OEDI_PREFIX}/data/2107_irradiance_data_2024.csv"),
    ("environment", f"{OEDI_PREFIX}/data/2107_environment_data.csv"),
    ("environment_2024", f"{OEDI_PREFIX}/data/2107_environment_data_2024.csv"),
)

PANEL_CLASS_HYUNDAI_H310 = "Hyundai HiS-M310TI mono-Si fixed tilt (PVDAQ 2107)"
# Assumed from Hyundai mono-Si datasheet class; not verified in PVDAQ metadata.
MODULE_TEMP_COEFF = -0.0041
MODULE_TEMP_COEFF_BASIS = (
    "Assumed -0.41 %/degC from Hyundai HiS-M310TI mono-Si datasheet class; "
    "PVDAQ metadata does not publish a verified coefficient."
)

MIN_DAILY_COVERAGE_FRACTION = 0.5


def _oedi_url(key: str) -> str:
    return f"{OEDI_BASE}/{key}"


def ensure_pvdaq_metadata(force: bool = False) -> Path:
    """Download metadata JSON if missing."""
    if METADATA_LOCAL.exists() and not force:
        return METADATA_LOCAL
    PVDAQ_DIR.mkdir(parents=True, exist_ok=True)
    response = requests.get(_oedi_url(METADATA_KEY), timeout=120)
    response.raise_for_status()
    METADATA_LOCAL.write_text(response.text, encoding="utf-8")
    LOGGER.info("Saved PVDAQ metadata to %s", METADATA_LOCAL)
    return METADATA_LOCAL


def load_pvdaq_metadata(path: Path | None = None) -> dict[str, Any]:
    """Load and return PVDAQ system metadata."""
    meta_path = path or ensure_pvdaq_metadata()
    return json.loads(meta_path.read_text(encoding="utf-8"))


def metadata_site_facts(meta: dict[str, Any]) -> dict[str, Any]:
    """Extract headline site facts verified against metadata JSON."""
    system = meta["System"]
    site = meta["Site"]
    mount = meta["Mount"]["Mount 0"]
    module = meta["Modules"]["Module 0"]
    return {
        "system_id": system["system_id"],
        "public_name": system["public_name"],
        "dc_capacity_kw": system["power(kW DC)"],
        "latitude": site["latitude"],
        "longitude": site["longitude"],
        "location": site["location"],
        "climate_type": site["climate_type"],
        "tilt_deg": mount["tilt"],
        "azimuth_deg": mount["azimuth"],
        "tracking": mount["tracking"],
        "module_manufacturer": module["manufacturer"],
        "module_model": module["model"],
        "module_type": module["type"],
        "metadata_first_timestamp": system["first_timestamp"],
        "metadata_last_timestamp": system["last_timestamp"],
        "number_data_channels": system["number_data_channels"],
    }


def ensure_pvdaq_csv(key: str, force: bool = False) -> Path:
    """Download one PVDAQ CSV from OEDI if missing."""
    local = PVDAQ_DIR / Path(key).name
    if local.exists() and not force:
        return local
    PVDAQ_DIR.mkdir(parents=True, exist_ok=True)
    url = _oedi_url(key)
    LOGGER.info("Downloading PVDAQ %s", local.name)
    with requests.get(url, stream=True, timeout=600) as response:
        response.raise_for_status()
        with local.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    LOGGER.info("Saved %s (%s bytes)", local, local.stat().st_size)
    return local


def ensure_pvdaq_data(force: bool = False) -> dict[str, Path]:
    """Ensure metadata and required CSV slices exist locally."""
    ensure_pvdaq_metadata(force=force)
    paths: dict[str, Path] = {}
    for label, key in DATA_FILE_SPECS:
        paths[label] = ensure_pvdaq_csv(key, force=force)
    return paths


def _read_slice(path: Path, raw_cols: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    rename = {raw: canonical for canonical, raw in CHANNEL_MAP.items() if raw in raw_cols}
    parse_col = CHANNEL_MAP["timestamp"]
    for chunk in pd.read_csv(
        path,
        usecols=raw_cols,
        parse_dates=[parse_col],
        chunksize=500_000,
        low_memory=False,
    ):
        chunk = chunk.rename(columns=rename)
        frames.append(chunk)
    if not frames:
        return pd.DataFrame(columns=list(rename.values()))
    return pd.concat(frames, ignore_index=True)


def _load_stream(paths: list[Path], value_col: str) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    raw = CHANNEL_MAP[value_col]
    cols = [CHANNEL_MAP["timestamp"], raw]
    for path in paths:
        frame = _read_slice(path, cols)
        if not frame.empty:
            parts.append(frame)
    if not parts:
        raise ValueError(f"No PVDAQ rows loaded for {value_col}")
    merged = pd.concat(parts, ignore_index=True)
    merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    return merged


def _aggregate_subdaily(frame: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Aggregate 15-minute rows to daily production or irradiation."""
    dt_hours = INTERVAL_MINUTES / 60.0
    renamed = frame.copy()
    renamed["date"] = renamed["timestamp"].dt.normalize()
    if value_col == "ac_power_kw":
        renamed["interval_value"] = renamed["ac_power_kw"].fillna(0.0) * dt_hours
        agg_col = "interval_value"
    elif value_col == "poa_wm2":
        renamed["interval_value"] = renamed["poa_wm2"].fillna(0.0) * dt_hours
        agg_col = "interval_value"
    elif value_col == "ambient_temp_f":
        renamed["ambient_temp_c"] = (renamed["ambient_temp_f"] - 32.0) * 5.0 / 9.0
        agg_col = "ambient_temp_c"
    else:
        raise ValueError(f"Unsupported aggregation column {value_col}")

    if value_col == "ambient_temp_f":
        daily = renamed.groupby("date", as_index=False).agg(
            weather_temperature_c=(agg_col, "mean"),
            n_intervals=("timestamp", "count"),
        )
    else:
        daily = renamed.groupby("date", as_index=False).agg(
            value=(agg_col, "sum"),
            n_intervals=("timestamp", "count"),
        )
    return daily


def select_energy_channel(power_daily: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    """PVDAQ meter reports interval-mean kW; daily energy is integrated power."""
    meta = {
        "selected_channel": "integrated_ac_power",
        "selection_reason": (
            "Revenue-grade AC meter channel meter_revenue_grade_ac_output_meter_149578 "
            "is interval-mean kW (metadata units=kW, aggregation=avg); no cumulative "
            "energy counter is exposed in the prize export slices."
        ),
        "median_power_to_counter_ratio": None,
    }
    return "integrated_ac_power", meta


def resolve_analysis_window(
    daily: pd.DataFrame,
    *,
    requested_start: str | None = None,
    requested_end: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Pick analysis dates where meter, POA, and ambient coverage are adequate."""
    expected_intervals = 24 * 60 / INTERVAL_MINUTES
    coverage = daily["n_intervals"] / expected_intervals
    good = daily.loc[
        (daily["production"] > 0)
        & (daily["irradiation"] > 0)
        & (coverage >= MIN_DAILY_COVERAGE_FRACTION)
    ].copy()
    if good.empty:
        raise ValueError("No PVDAQ days meet minimum production/irradiation/coverage criteria")

    start = pd.Timestamp(requested_start) if requested_start else good["date"].min()
    end = pd.Timestamp(requested_end) if requested_end else good["date"].max()
    window = good.loc[(good["date"] >= start) & (good["date"] <= end)].copy()
    if window.empty:
        raise ValueError(f"No PVDAQ days in requested window {start.date()} .. {end.date()}")

    info = {
        "analysis_start": str(window["date"].min().date()),
        "analysis_end": str(window["date"].max().date()),
        "days_total": int(len(window)),
        "median_interval_coverage": float((window["n_intervals"] / expected_intervals).median()),
        "selection_rule": (
            f"Days require production>0, irradiation>0, and >={MIN_DAILY_COVERAGE_FRACTION:.0%} "
            f"of {int(expected_intervals)} expected 15-min intervals."
        ),
    }
    return info["analysis_start"], info["analysis_end"], info


def load_pvdaq_daily(
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load PVDAQ 2107 15-min CSV slices and return a daily master-ready table."""
    paths = ensure_pvdaq_data()
    meta = load_pvdaq_metadata()
    facts = metadata_site_facts(meta)

    power = _load_stream([paths["meter"], paths["meter_2024"]], "ac_power_kw")
    poa = _load_stream([paths["irradiance"], paths["irradiance_2024"]], "poa_wm2")
    ambient = _load_stream([paths["environment"], paths["environment_2024"]], "ambient_temp_f")

    power_daily = _aggregate_subdaily(power, "ac_power_kw").rename(columns={"value": "production"})
    poa_daily = _aggregate_subdaily(poa, "poa_wm2").rename(columns={"value": "irradiation"})
    temp_daily = _aggregate_subdaily(ambient, "ambient_temp_f")

    daily = power_daily.merge(poa_daily[["date", "irradiation"]], on="date", how="outer")
    daily = daily.merge(temp_daily[["date", "weather_temperature_c"]], on="date", how="outer")
    daily["n_intervals"] = daily["n_intervals"].fillna(0)
    daily = daily.sort_values("date").reset_index(drop=True)

    channel, channel_meta = select_energy_channel(daily)
    win_start, win_end, window_info = resolve_analysis_window(
        daily,
        requested_start=start_date,
        requested_end=end_date,
    )
    daily = daily.loc[(daily["date"] >= win_start) & (daily["date"] <= win_end)].copy()
    daily = daily.loc[(daily["production"] > 0) & (daily["irradiation"] > 0)].copy()
    if daily.empty:
        raise ValueError("No valid PVDAQ daily rows after window filter")

    daily["pi"] = daily["production"] / daily["irradiation"]

    sidecar = {
        "system_id": SYSTEM_ID,
        "site_facts": facts,
        "column_mapping": CHANNEL_MAP,
        "channels_used": {
            "ac_power_kw": CHANNEL_MAP["ac_power_kw"],
            "poa_wm2": CHANNEL_MAP["poa_wm2"],
            "ambient_temp_f": CHANNEL_MAP["ambient_temp_f"],
        },
        "energy_channel": channel_meta,
        "analysis_window": window_info,
        "module_temp_coeff": MODULE_TEMP_COEFF,
        "module_temp_coeff_basis": MODULE_TEMP_COEFF_BASIS,
        "measurement_interval_minutes": INTERVAL_MINUTES,
        "production_units": "kWh/day (integrated revenue-grade AC kW, 15-min)",
        "irradiation_units": "Wh/m2/day (integrated POA W/m2, 15-min)",
        "precipitation_source": "NASA POWER PRECTOTCORR (no onsite rain gauge in prize export)",
        "module_temperature_source": (
            "No module temperature channel in metadata; cell temperature estimated "
            "from onsite ambient (F→C) via NOCT proxy like Canakkale."
        ),
        "rows_daily": len(daily),
        "pull_date": datetime.utcnow().strftime("%Y-%m-%d"),
    }
    sidecar_path = PVDAQ_DIR / "2107_daily_sidecar.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2, default=str), encoding="utf-8")
    LOGGER.info(
        "Loaded PVDAQ 2107 daily frame: %s rows (%s .. %s)",
        len(daily),
        daily["date"].min().date(),
        daily["date"].max().date(),
    )
    return daily, sidecar


def introspect_pvdaq_channels() -> dict[str, Any]:
    """Return metadata-backed channel mapping for reports and tests."""
    meta = load_pvdaq_metadata()
    return {
        "metadata_path": str(METADATA_LOCAL),
        "site_facts": metadata_site_facts(meta),
        "column_mapping": CHANNEL_MAP,
        "data_files": [Path(key).name for _, key in DATA_FILE_SPECS],
    }
