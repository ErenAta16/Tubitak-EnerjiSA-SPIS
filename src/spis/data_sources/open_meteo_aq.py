"""Open-Meteo Air Quality (Copernicus CAMS) client."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

from spis import config
from spis.data_sources._cache import read_cache, write_cache

LOGGER = logging.getLogger(__name__)

OPEN_METEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
AQ_VARIABLES = ("pm10", "pm2_5", "dust", "aerosol_optical_depth")
AQ_UNITS = {
    "pm10": "ug/m3",
    "pm2_5": "ug/m3",
    "dust": "ug/m3",
    "aerosol_optical_depth": "dimensionless",
}


def fetch_open_meteo_air_quality(
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch or load cached daily-aggregated CAMS air-quality for the plant location."""
    if not force_refresh:
        try:
            return read_cache("open_meteo_aq", "daily_cams.parquet", "daily_cams.json")
        except FileNotFoundError:
            pass

    params = {
        "latitude": config.PLANT_LAT,
        "longitude": config.PLANT_LON,
        "hourly": ",".join(AQ_VARIABLES),
        "start_date": config.IRRADIANCE_START_DATE,
        "end_date": config.IRRADIANCE_END_DATE,
    }
    response = requests.get(OPEN_METEO_AQ_URL, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    hourly = pd.DataFrame(payload["hourly"])
    hourly["time"] = pd.to_datetime(hourly["time"])
    hourly["date"] = hourly["time"].dt.normalize()
    daily = hourly.groupby("date", as_index=False)[list(AQ_VARIABLES)].mean(numeric_only=True)
    daily = daily.sort_values("date").reset_index(drop=True)

    if daily.empty:
        raise ValueError("Open-Meteo air quality pull returned no rows")

    coverage_start = str(daily["date"].min().date())
    coverage_end = str(daily["date"].max().date())
    if coverage_start > config.IRRADIANCE_START_DATE:
        LOGGER.warning(
            "CAMS coverage starts %s (requested %s); leading dates will be null in master join",
            coverage_start,
            config.IRRADIANCE_START_DATE,
        )

    metadata = {
        "source": "Open-Meteo Air Quality (Copernicus CAMS)",
        "url": OPEN_METEO_AQ_URL,
        "request_params": params,
        "units": AQ_UNITS,
        "aggregation": "hourly mean -> daily mean",
        "date_span": {"start": coverage_start, "end": coverage_end},
    }
    write_cache("open_meteo_aq", "daily_cams.parquet", "daily_cams.json", daily, metadata)
    return daily, metadata


def validate_open_meteo_aq(frame: pd.DataFrame) -> None:
    """Assert CAMS pull is non-empty with expected pollution columns."""
    missing = set(AQ_VARIABLES).difference(frame.columns)
    if missing:
        raise ValueError(f"CAMS frame missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("CAMS frame is empty")
    if (frame["pm10"] < 0).any():
        raise ValueError("CAMS pm10 contains negative values")
    if (frame["aerosol_optical_depth"] < 0).any():
        raise ValueError("CAMS aerosol_optical_depth contains negative values")
