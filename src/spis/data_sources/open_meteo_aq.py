"""Open-Meteo Air Quality (Copernicus CAMS) client."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

from spis.data_sources._cache import read_cache, write_cache
from spis.sites import DEFAULT_SITE, get_site, site_external_subdir

LOGGER = logging.getLogger(__name__)

OPEN_METEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
AQ_VARIABLES = ("pm10", "pm2_5", "dust", "aerosol_optical_depth")
AQ_UNITS = {
    "pm10": "ug/m3",
    "pm2_5": "ug/m3",
    "dust": "ug/m3",
    "aerosol_optical_depth": "dimensionless",
}
PARQUET_NAME = "daily_cams.parquet"
SIDECAR_NAME = "daily_cams.json"


def _cache_source(site_key: str) -> str:
    return site_external_subdir("open_meteo_aq", site_key)


def fetch_open_meteo_air_quality(
    site_key: str = DEFAULT_SITE,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch or load cached daily-aggregated CAMS air-quality for a site."""
    site = get_site(site_key)
    if site_key == DEFAULT_SITE:
        from spis import config as spis_config

        spis_config.log_plant_coordinate_source()
    cache_src = _cache_source(site_key)

    if not force_refresh:
        for src in (cache_src, "open_meteo_aq") if site_key == DEFAULT_SITE else (cache_src,):
            try:
                frame, metadata = read_cache(src, PARQUET_NAME, SIDECAR_NAME)
                metadata = {
                    **metadata,
                    "site_key": site_key,
                    "provisional": site.coordinates_provisional,
                }
                return frame, metadata
            except FileNotFoundError:
                continue

    params = {
        "latitude": site.lat,
        "longitude": site.lon,
        "hourly": ",".join(AQ_VARIABLES),
        "start_date": site.resolved_analysis_start(),
        "end_date": site.resolved_analysis_end(),
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
    if coverage_start > site.resolved_analysis_start():
        LOGGER.warning(
            "CAMS coverage starts %s (requested %s); leading dates will be null in master join",
            coverage_start,
            site.resolved_analysis_start(),
        )

    metadata = {
        "source": "Open-Meteo Air Quality (Copernicus CAMS)",
        "url": OPEN_METEO_AQ_URL,
        "request_params": params,
        "units": AQ_UNITS,
        "site_key": site_key,
        "provisional": site.coordinates_provisional,
        "coordinates_note": site.coordinates_note,
        "aggregation": "hourly mean -> daily mean",
        "date_span": {"start": coverage_start, "end": coverage_end},
    }
    write_cache(cache_src, PARQUET_NAME, SIDECAR_NAME, daily, metadata)
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
