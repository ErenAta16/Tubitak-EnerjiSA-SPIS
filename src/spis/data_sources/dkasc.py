"""DKASC Alice Springs array CSV loader with programmatic header mapping."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from spis import config

LOGGER = logging.getLogger(__name__)

DKASC_DIR = config.DATA_EXTERNAL / "dkasc"
DKASC_EXPORT_API = "https://solarcentre.spinifexvalley.com.au/export-sources-details"
DKASC_LOCATION_ID = 1
MEASUREMENT_INTERVAL_MINUTES = 5

COLUMN_SPECS: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "time", "date_time", "datetime"),
    "active_power_kw": ("active_power", "active power"),
    "active_energy_cumulative": (
        "active_energy_delivered_received",
        "active energy delivered",
    ),
    "ghi_wm2": ("global_horizontal_radiation", "global horizontal"),
    "weather_temperature_c": ("weather_temperature_celsius", "weather_temperature"),
    "weather_humidity_pct": ("weather_relative_humidity", "relative_humidity"),
    "weather_wind_speed": ("wind_speed",),
    "weather_rainfall_mm": ("weather_daily_rainfall", "daily_rainfall", "rainfall"),
}


@dataclass(frozen=True)
class DkascArraySpec:
    """One DKASC Alice Springs research array export."""

    source_id: int
    array_number: str
    label: str
    filename: str
    module_temp_coeff: float
    module_temp_coeff_basis: str
    tilt_type: str = "fixed"


# Fixed-tilt silicon arrays with long records (P16 external validation scope).
VALIDATION_ARRAYS: tuple[DkascArraySpec, ...] = (
    DkascArraySpec(
        source_id=92,
        array_number="13",
        label="Trina 5.3 kW mono-Si fixed tilt (array 13, M6 B Phase)",
        filename="92-Site_DKA-M6_B-Phase.csv",
        module_temp_coeff=-0.0041,
        module_temp_coeff_basis=(
            "Assumed -0.41 %/degC from Trina mono-Si datasheet class; "
            "DKASC metadata does not publish a verified coefficient."
        ),
    ),
    DkascArraySpec(
        source_id=71,
        array_number="18",
        label="SunPower 5.2 kW mono-Si fixed tilt (array 18, M2 C Phase)",
        filename="71-Site_DKA-M2_C-Phase.csv",
        module_temp_coeff=-0.0038,
        module_temp_coeff_basis=(
            "Assumed -0.38 %/degC from SunPower mono-Si datasheet class; "
            "DKASC metadata does not publish a verified coefficient."
        ),
    ),
    DkascArraySpec(
        source_id=90,
        array_number="14",
        label="Kyocera 5.4 kW poly-Si fixed tilt (array 14, M3 A Phase)",
        filename="90-Site_DKA-M3_A-Phase.csv",
        module_temp_coeff=-0.0045,
        module_temp_coeff_basis=(
            "Assumed -0.45 %/degC from Kyocera poly-Si datasheet class; "
            "DKASC metadata does not publish a verified coefficient."
        ),
    ),
    DkascArraySpec(
        source_id=214,
        array_number="32",
        label="Canadian Solar 5.3 kW poly-Si fixed tilt (array 32, M18 B Phase II)",
        filename="214-Site_DKA-M18_B-Phase_II.csv",
        module_temp_coeff=-0.0041,
        module_temp_coeff_basis=(
            "Assumed -0.41 %/degC from Canadian Solar poly module datasheet class "
            "(CS6K-style); DKASC metadata does not publish a verified coefficient."
        ),
    ),
)

DEFAULT_ARRAY = VALIDATION_ARRAYS[0]
DEFAULT_ARRAY_CSV = DKASC_DIR / DEFAULT_ARRAY.filename
DEFAULT_ARRAY_SOURCE_ID = DEFAULT_ARRAY.source_id
DEFAULT_ARRAY_LABEL = DEFAULT_ARRAY.label


def get_validation_array(source_id: int) -> DkascArraySpec:
    """Return a validation array spec by export source id."""
    for spec in VALIDATION_ARRAYS:
        if spec.source_id == source_id:
            return spec
    raise KeyError(f"Unknown DKASC validation array source_id={source_id}")


def _normalize_header(name: str) -> str:
    folded = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower())
    return folded.strip("_")


def map_dkasc_columns(columns: list[str]) -> dict[str, str]:
    """Map raw CSV headers to canonical names; raise if required columns missing."""
    normalized = {_normalize_header(col): col for col in columns}
    mapping: dict[str, str] = {}
    missing: list[str] = []

    for canonical, candidates in COLUMN_SPECS.items():
        matched = None
        for candidate in candidates:
            if candidate in normalized:
                matched = normalized[candidate]
                break
        if matched is None:
            if canonical in {"timestamp", "active_power_kw", "ghi_wm2"}:
                missing.append(canonical)
            continue
        mapping[canonical] = matched

    if missing:
        raise ValueError(
            f"DKASC CSV missing required columns {missing}; headers={list(columns)[:20]}"
        )
    return mapping


def _export_url(source_id: int) -> str:
    response = requests.get(
        DKASC_EXPORT_API,
        params={"location_id": DKASC_LOCATION_ID},
        timeout=120,
    )
    response.raise_for_status()
    details = response.json()["file_details"][str(source_id)]
    return str(details[0])


def ensure_dkasc_csv(array: DkascArraySpec | None = None, force: bool = False) -> Path:
    """Download a DKASC CSV when missing locally."""
    spec = array or DEFAULT_ARRAY
    csv_path = DKASC_DIR / spec.filename
    if csv_path.exists() and not force:
        return csv_path

    DKASC_DIR.mkdir(parents=True, exist_ok=True)
    url = _export_url(spec.source_id)
    LOGGER.info("Downloading DKASC array %s from %s", spec.array_number, url)
    with requests.get(url, stream=True, timeout=600) as response:
        response.raise_for_status()
        with csv_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    LOGGER.info("Saved DKASC CSV to %s", csv_path)
    return csv_path


def discover_dkasc_csv(path: Path | None = None, array: DkascArraySpec | None = None) -> Path:
    """Return the configured DKASC CSV path or the first validation *.csv in dkasc/."""
    if path is not None:
        if not path.exists():
            raise FileNotFoundError(f"DKASC CSV not found: {path}")
        return path
    spec = array or DEFAULT_ARRAY
    candidate = DKASC_DIR / spec.filename
    if candidate.exists():
        return candidate
    for item in VALIDATION_ARRAYS:
        alt = DKASC_DIR / item.filename
        if alt.exists():
            return alt
    raise FileNotFoundError(
        "No DKASC CSV under data/external/dkasc/. Run ensure_dkasc_csv() or download "
        "fixed-tilt arrays from https://dkasolarcentre.com.au/download?location=alice-springs"
    )


def introspect_dkasc_csv(
    path: Path | None = None,
    array: DkascArraySpec | None = None,
) -> dict[str, Any]:
    """Read the header row and return the resolved column mapping."""
    spec = array or DEFAULT_ARRAY
    csv_path = discover_dkasc_csv(path, array=spec)
    header = pd.read_csv(csv_path, nrows=0).columns.tolist()
    mapping = map_dkasc_columns(header)
    return {
        "csv_path": str(csv_path),
        "raw_headers": header,
        "column_mapping": mapping,
        "array_label": spec.label,
        "array_number": spec.array_number,
        "source_id": spec.source_id,
        "module_temp_coeff": spec.module_temp_coeff,
        "module_temp_coeff_basis": spec.module_temp_coeff_basis,
    }


def _coerce_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def select_energy_channel(daily: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    """Choose daily production channel for PI; prefer inverter cumulative counter when valid."""
    meta: dict[str, Any] = {
        "power_integration_col": "production_power",
        "counter_col": "production_counter",
    }
    if "production_counter" not in daily.columns:
        meta.update(
            {
                "selected_channel": "power_integration",
                "selection_reason": (
                    "Active_Energy_Delivered_Received column absent; "
                    "integrated Active_Power used."
                ),
                "median_power_to_counter_ratio": None,
            }
        )
        return "power_integration", meta

    valid = daily.loc[
        (daily["production_power"] > 0)
        & (daily["production_counter"] > 0)
        & daily["irradiation"].notna()
    ].copy()
    ratio = valid["production_power"] / valid["production_counter"]
    median_ratio = float(ratio.median()) if not ratio.empty else float("nan")
    counter_fraction = float((daily["production_counter"] > 0).mean())
    meta["median_power_to_counter_ratio"] = median_ratio
    meta["counter_positive_fraction"] = counter_fraction

    counter_ok = (
        counter_fraction >= config.DKASC_COUNTER_VALID_FRACTION
        and pd.notna(median_ratio)
        and config.DKASC_COUNTER_RATIO_MIN <= median_ratio <= config.DKASC_COUNTER_RATIO_MAX
    )
    if counter_ok:
        meta.update(
            {
                "selected_channel": "cumulative_counter",
                "selection_reason": (
                    "Inverter cumulative Active_Energy_Delivered_Received daily difference "
                    f"used (median power/counter ratio {median_ratio:.4f}; "
                    f"{counter_fraction:.1%} days with positive counter)."
                ),
            }
        )
        return "cumulative_counter", meta

    meta.update(
        {
            "selected_channel": "power_integration",
            "selection_reason": (
                "Integrated Active_Power used because counter failed validity checks "
                f"(median ratio {median_ratio:.4f}, positive fraction {counter_fraction:.1%})."
            ),
        }
    )
    return "power_integration", meta


def _aggregate_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one 5-minute chunk to daily rows (canonical column names)."""
    renamed = chunk.copy()
    for col in (
        "active_power_kw",
        "active_energy_cumulative",
        "ghi_wm2",
        "weather_temperature_c",
        "weather_humidity_pct",
        "weather_wind_speed",
        "weather_rainfall_mm",
    ):
        if col in renamed.columns:
            renamed[col] = _coerce_numeric(renamed[col])
    renamed["date"] = renamed["timestamp"].dt.normalize()
    dt_hours = MEASUREMENT_INTERVAL_MINUTES / 60.0
    renamed["energy_kwh_interval"] = renamed["active_power_kw"].fillna(0.0) * dt_hours
    renamed["ghi_wh_interval"] = renamed["ghi_wm2"].fillna(0.0) * dt_hours

    agg_spec: dict[str, tuple[str, str]] = {
        "production_power": ("energy_kwh_interval", "sum"),
        "irradiation": ("ghi_wh_interval", "sum"),
        "weather_rainfall_mm": ("weather_rainfall_mm", "max"),
        "n_intervals": ("energy_kwh_interval", "count"),
    }
    for optional_col in ("weather_temperature_c", "weather_humidity_pct", "weather_wind_speed"):
        if optional_col in renamed.columns:
            agg_spec[optional_col] = (optional_col, "mean")
    if "active_energy_cumulative" in renamed.columns:
        agg_spec["energy_counter_min"] = ("active_energy_cumulative", "min")
        agg_spec["energy_counter_max"] = ("active_energy_cumulative", "max")

    daily = renamed.groupby("date", as_index=False).agg(
        **{name: pd.NamedAgg(column=col, aggfunc=func) for name, (col, func) in agg_spec.items()}
    )
    if {"energy_counter_min", "energy_counter_max"}.issubset(daily.columns):
        daily["production_counter"] = daily["energy_counter_max"] - daily["energy_counter_min"]
    return daily


def load_dkasc_daily(
    start_date: str,
    end_date: str,
    path: Path | None = None,
    array: DkascArraySpec | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load DKASC 5-minute CSV and return a daily production/irradiation table."""
    spec = array or DEFAULT_ARRAY
    csv_path = discover_dkasc_csv(path, array=spec)
    meta = introspect_dkasc_csv(csv_path, array=spec)
    mapping = meta["column_mapping"]

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    daily_parts: list[pd.DataFrame] = []
    usecols = list(dict.fromkeys(mapping.values()))
    for chunk in pd.read_csv(
        csv_path,
        usecols=usecols,
        parse_dates=[mapping["timestamp"]],
        chunksize=250_000,
        low_memory=False,
    ):
        chunk = chunk.rename(columns={raw: canonical for canonical, raw in mapping.items()})
        chunk = chunk.loc[(chunk["timestamp"] >= start_ts) & (chunk["timestamp"] <= end_ts)]
        if chunk.empty:
            continue
        daily_parts.append(_aggregate_chunk(chunk))

    if not daily_parts:
        raise ValueError(f"No DKASC rows in window {start_date} .. {end_date} for {csv_path.name}")

    partial = pd.concat(daily_parts, ignore_index=True)

    def _weighted_mean(group: pd.DataFrame, value_col: str) -> float:
        weights = group["n_intervals"].to_numpy(dtype=float)
        values = group[value_col].to_numpy(dtype=float)
        if weights.sum() <= 0:
            return float(np.nanmean(values))
        return float(np.average(values, weights=weights))

    rows: list[dict[str, Any]] = []
    for date, group in partial.groupby("date"):
        row: dict[str, Any] = {
            "date": date,
            "production_power": float(group["production_power"].sum()),
            "irradiation": float(group["irradiation"].sum()),
            "weather_rainfall_mm": float(group["weather_rainfall_mm"].max()),
        }
        for col in ("weather_temperature_c", "weather_humidity_pct", "weather_wind_speed"):
            if col in group.columns:
                row[col] = _weighted_mean(group, col)
        if "energy_counter_min" in group.columns:
            row["production_counter"] = float(
                group["energy_counter_max"].max() - group["energy_counter_min"].min()
            )
        rows.append(row)
    daily = pd.DataFrame(rows)
    daily = daily.sort_values("date").reset_index(drop=True)
    daily = daily.loc[
        (daily["date"] >= start_ts.normalize()) & (daily["date"] <= end_ts.normalize())
    ]

    channel, channel_meta = select_energy_channel(daily)
    daily["production"] = daily["production_power"]
    if channel == "cumulative_counter":
        daily["production"] = daily["production_counter"]

    invalid = daily.loc[(daily["production"] <= 0) | (daily["irradiation"] <= 0)]
    if not invalid.empty:
        LOGGER.warning(
            "Dropping %s DKASC days with non-positive production/irradiation (%s)",
            len(invalid),
            spec.array_number,
        )
        daily = daily.loc[(daily["production"] > 0) & (daily["irradiation"] > 0)].copy()
    if daily.empty:
        raise ValueError("No valid DKASC daily rows after positive production/irradiation filter")

    daily["pi"] = daily["production"] / daily["irradiation"]
    daily["pi_power_check"] = daily["production_power"] / daily["irradiation"]
    if "production_counter" in daily.columns:
        daily["pi_counter_check"] = daily["production_counter"] / daily["irradiation"]

    sidecar_name = f"{spec.source_id}-{spec.filename.replace('.csv', '')}.json"
    sidecar = {
        **meta,
        "start_date": start_date,
        "end_date": end_date,
        "pull_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "source_url": f"https://solarcentre.spinifexvalley.com.au/export/{spec.filename}",
        "measurement_interval_minutes": MEASUREMENT_INTERVAL_MINUTES,
        "energy_channel": channel_meta,
        "production_units": (
            "kWh/day (Active_Energy counter diff)"
            if channel == "cumulative_counter"
            else "kWh/day (integrated Active_Power kW)"
        ),
        "irradiation_units": "Wh/m2/day (integrated Global_Horizontal_Radiation W/m2)",
        "rows_daily": len(daily),
    }
    DKASC_DIR.mkdir(parents=True, exist_ok=True)
    (DKASC_DIR / sidecar_name).write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    LOGGER.info(
        "Loaded DKASC array %s daily frame: %s rows (%s .. %s) channel=%s",
        spec.array_number,
        len(daily),
        daily["date"].min().date(),
        daily["date"].max().date(),
        channel,
    )
    return daily, sidecar
