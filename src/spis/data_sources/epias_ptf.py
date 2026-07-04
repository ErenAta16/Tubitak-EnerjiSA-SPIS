"""EPIAS day-ahead PTF CSV ingest (hourly TL/MWh, Turkish locale)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from spis import config
from spis.data_sources._cache import read_cache, write_cache

LOGGER = logging.getLogger(__name__)

SOURCE_NAME = "epias_ptf"
HOURLY_PARQUET = "ptf_hourly.parquet"
HOURLY_SIDECAR = "ptf_hourly.json"
MONTHLY_PARQUET = "ptf_monthly.parquet"
MONTHLY_SIDECAR = "ptf_monthly.json"
ANNUAL_PARQUET = "ptf_annual.parquet"
ANNUAL_SIDECAR = "ptf_annual.json"
CSV_GLOB = "Piyasa_Takas_Fiyati-*.csv"


def parse_turkish_number(value: str | float) -> float:
    """Parse Turkish-formatted numbers (dot thousands, comma decimal)."""
    if isinstance(value, float | int):
        return float(value)
    text = str(value).strip()
    if not text:
        raise ValueError("Empty numeric string")
    return float(text.replace(".", "").replace(",", "."))


def locate_ptf_csv(directory: Path | None = None) -> Path:
    """Find the PTF CSV under data/external/epias_ptf/."""
    root = directory or config.DATA_EXTERNAL / SOURCE_NAME
    matches = sorted(root.glob(CSV_GLOB))
    if not matches:
        raise FileNotFoundError(
            f"No PTF CSV matching {CSV_GLOB} under {root}. Drop the EPIAS export there and re-run."
        )
    return matches[0]


def load_ptf_hourly(csv_path: Path | None = None) -> pd.DataFrame:
    """Parse hourly PTF CSV; keep 2023 rows only."""
    path = csv_path or locate_ptf_csv()
    raw = pd.read_csv(path, sep=";", encoding="utf-8-sig")
    expected = {"Tarih", "Saat", "PTF (TL/MWh)"}
    if not expected.issubset(raw.columns):
        raise ValueError(f"Unexpected PTF columns: {list(raw.columns)}")

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["Tarih"], format="%d.%m.%Y"),
            "hour": raw["Saat"].astype(str).str.strip(),
            "ptf_tl_mwh": raw["PTF (TL/MWh)"].map(parse_turkish_number),
        }
    )
    before = len(frame)
    frame = frame.loc[frame["date"].dt.year == 2023].copy()
    dropped = before - len(frame)
    if dropped:
        LOGGER.info("Dropped %s PTF rows outside calendar year 2023", dropped)
    if frame.empty:
        raise ValueError("No 2023 PTF rows after filtering")
    if (frame["ptf_tl_mwh"] < 0).any():
        raise ValueError("Negative PTF values encountered")
    frame = frame.sort_values(["date", "hour"]).reset_index(drop=True)
    LOGGER.info(
        "Parsed PTF hourly: %s rows for 2023 from %s",
        len(frame),
        path.name,
    )
    return frame


def aggregate_ptf_monthly(hourly: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean PTF (TL/MWh) for 2023."""
    monthly = (
        hourly.assign(month=hourly["date"].dt.to_period("M").dt.to_timestamp())
        .groupby("month", as_index=False)
        .agg(
            ptf_tl_mwh_mean=("ptf_tl_mwh", "mean"),
            n_hours=("ptf_tl_mwh", "count"),
        )
    )
    monthly["year"] = monthly["month"].dt.year
    return monthly


def aggregate_ptf_annual(hourly: pd.DataFrame) -> pd.DataFrame:
    """Annual mean PTF (TL/MWh) for 2023."""
    annual = pd.DataFrame(
        [
            {
                "year": 2023,
                "ptf_tl_mwh_mean": float(hourly["ptf_tl_mwh"].mean()),
                "n_hours": len(hourly),
                "coverage_note": "2023 only; 2024-2025 not supplied",
            }
        ]
    )
    return annual


def ingest_epias_ptf(force_refresh: bool = False) -> dict[str, Any]:
    """Parse CSV, cache hourly/monthly/annual tables, return headline stats."""
    if not force_refresh:
        try:
            annual, meta = read_cache(SOURCE_NAME, ANNUAL_PARQUET, ANNUAL_SIDECAR)
            return {
                "annual_mean_tl_mwh": float(annual.iloc[0]["ptf_tl_mwh_mean"]),
                "year": int(annual.iloc[0]["year"]),
                "source": "cache",
                "metadata": meta,
            }
        except FileNotFoundError:
            pass

    csv_path = locate_ptf_csv()
    hourly = load_ptf_hourly(csv_path)
    monthly = aggregate_ptf_monthly(hourly)
    annual = aggregate_ptf_annual(hourly)
    metadata = {
        "source_file": csv_path.name,
        "url": "EPIAS transparency export (user-supplied CSV)",
        "units": "TL/MWh",
        "year_coverage": "2023 only",
    }
    write_cache(SOURCE_NAME, HOURLY_PARQUET, HOURLY_SIDECAR, hourly, metadata)
    write_cache(SOURCE_NAME, MONTHLY_PARQUET, MONTHLY_SIDECAR, monthly, metadata)
    write_cache(SOURCE_NAME, ANNUAL_PARQUET, ANNUAL_SIDECAR, annual, metadata)
    mean = float(annual.iloc[0]["ptf_tl_mwh_mean"])
    LOGGER.info("2023 annual-mean PTF: %.2f TL/MWh", mean)
    return {
        "annual_mean_tl_mwh": mean,
        "year": 2023,
        "source": "csv",
        "metadata": metadata,
    }


def load_ptf_central_price() -> tuple[float, str]:
    """Return central PTF price (TL/MWh) and provenance tag."""
    stats = ingest_epias_ptf(force_refresh=False)
    return float(stats["annual_mean_tl_mwh"]), "real_2023"
