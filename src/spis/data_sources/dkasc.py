"""DKASC Alice Springs array CSV loader with programmatic header mapping."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from spis import config

LOGGER = logging.getLogger(__name__)

DKASC_DIR = config.DATA_EXTERNAL / "dkasc"
DEFAULT_ARRAY_CSV = DKASC_DIR / "214-Site_DKA-M18_B-Phase_II.csv"
DEFAULT_ARRAY_SOURCE_ID = 214
DEFAULT_ARRAY_LABEL = "Canadian Solar 5.3 kW poly-Si fixed tilt (DKASC array 32, M18 B Phase II)"
SIDECAR_NAME = "214-Site_DKA-M18_B-Phase_II.json"
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


def discover_dkasc_csv(path: Path | None = None) -> Path:
    """Return the configured DKASC CSV path or the first *.csv in dkasc/."""
    if path is not None:
        if not path.exists():
            raise FileNotFoundError(f"DKASC CSV not found: {path}")
        return path
    if DEFAULT_ARRAY_CSV.exists():
        return DEFAULT_ARRAY_CSV
    candidates = sorted(DKASC_DIR.glob("*.csv"))
    if not candidates:
        raise FileNotFoundError(
            "No DKASC CSV under data/external/dkasc/. Download array 214 "
            "(Canadian Solar 5.3 kW, DKASC array 32) from "
            "https://dkasolarcentre.com.au/download?location=alice-springs "
            "and save as data/external/dkasc/214-Site_DKA-M18_B-Phase_II.csv"
        )
    return candidates[0]


def introspect_dkasc_csv(path: Path | None = None) -> dict[str, Any]:
    """Read the header row and return the resolved column mapping."""
    csv_path = discover_dkasc_csv(path)
    header = pd.read_csv(csv_path, nrows=0).columns.tolist()
    mapping = map_dkasc_columns(header)
    return {
        "csv_path": str(csv_path),
        "raw_headers": header,
        "column_mapping": mapping,
        "array_label": DEFAULT_ARRAY_LABEL,
        "source_id": DEFAULT_ARRAY_SOURCE_ID,
    }


def _coerce_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


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
        "production": ("energy_kwh_interval", "sum"),
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
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load DKASC 5-minute CSV and return a daily production/irradiation table."""
    csv_path = discover_dkasc_csv(path)
    meta = introspect_dkasc_csv(csv_path)
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
            "production": float(group["production"].sum()),
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

    invalid = daily.loc[(daily["production"] <= 0) | (daily["irradiation"] <= 0)]
    if not invalid.empty:
        LOGGER.warning(
            "Dropping %s DKASC days with non-positive production/irradiation",
            len(invalid),
        )
        daily = daily.loc[(daily["production"] > 0) & (daily["irradiation"] > 0)].copy()
    if daily.empty:
        raise ValueError("No valid DKASC daily rows after positive production/irradiation filter")

    daily["pi"] = daily["production"] / daily["irradiation"]

    if "production_counter" in daily.columns:
        daily["pi_counter_check"] = daily["production_counter"] / daily["irradiation"]
        median_ratio = float(
            (daily["production"] / daily["production_counter"]).median(skipna=True)
        )
        if not np.isclose(median_ratio, 1.0, rtol=0.05):
            LOGGER.warning(
                "Power integration vs cumulative counter median ratio %.4f (expected ~1)",
                median_ratio,
            )

    sidecar = {
        **meta,
        "start_date": start_date,
        "end_date": end_date,
        "pull_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "source_url": "https://solarcentre.spinifexvalley.com.au/export/214-Site_DKA-M18_B-Phase_II.csv",
        "measurement_interval_minutes": MEASUREMENT_INTERVAL_MINUTES,
        "production_units": "kWh/day (integrated Active_Power kW)",
        "irradiation_units": "Wh/m2/day (integrated Global_Horizontal_Radiation W/m2)",
        "rows_daily": len(daily),
    }
    DKASC_DIR.mkdir(parents=True, exist_ok=True)
    (DKASC_DIR / SIDECAR_NAME).write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    LOGGER.info(
        "Loaded DKASC daily frame: %s rows (%s .. %s) from %s",
        len(daily),
        daily["date"].min().date(),
        daily["date"].max().date(),
        csv_path.name,
    )
    return daily, sidecar
