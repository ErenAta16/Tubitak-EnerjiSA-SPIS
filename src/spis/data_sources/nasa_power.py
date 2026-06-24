"""NASA POWER daily point API client."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

from spis import config
from spis.data_sources._cache import read_cache, write_cache
from spis.sites import DEFAULT_SITE, get_site, site_external_subdir

LOGGER = logging.getLogger(__name__)

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_PARAMETERS = (
    "T2M",
    "T2M_MAX",
    "WS2M",
    "PRECTOTCORR",
    "ALLSKY_SFC_SW_DWN",
    "CLRSKY_SFC_SW_DWN",
)
NASA_UNITS = {
    "T2M": "degC",
    "T2M_MAX": "degC",
    "WS2M": "m/s",
    "PRECTOTCORR": "mm/day",
    "ALLSKY_SFC_SW_DWN": "kWh/m2/day",
    "CLRSKY_SFC_SW_DWN": "kWh/m2/day",
}
PARQUET_NAME = "daily_point.parquet"
SIDECAR_NAME = "daily_point.json"


def _cache_source(site_key: str) -> str:
    return site_external_subdir("nasa_power", site_key)


def fetch_nasa_power_daily(
    site_key: str = DEFAULT_SITE,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch or load cached NASA POWER daily weather for a site location."""
    site = get_site(site_key)
    cache_src = _cache_source(site_key)

    if not force_refresh:
        for src in (cache_src, "nasa_power") if site_key == DEFAULT_SITE else (cache_src,):
            try:
                frame, metadata = read_cache(src, PARQUET_NAME, SIDECAR_NAME)
                if "clrsky_sfc_sw_dwn" not in frame.columns:
                    LOGGER.info("Cached NASA POWER missing CLRSKY; refreshing pull")
                    break
                metadata = {
                    **metadata,
                    "site_key": site_key,
                    "provisional": site.coordinates_provisional,
                }
                return frame, metadata
            except FileNotFoundError:
                continue

    params = {
        "parameters": ",".join(NASA_PARAMETERS),
        "community": "RE",
        "longitude": site.lon,
        "latitude": site.lat,
        "start": config.IRRADIANCE_START_DATE.replace("-", ""),
        "end": config.IRRADIANCE_END_DATE.replace("-", ""),
        "format": "JSON",
    }
    response = requests.get(NASA_POWER_URL, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    parameter_data = payload["properties"]["parameter"]

    dates = sorted(parameter_data["T2M"].keys())
    rows: list[dict[str, Any]] = []
    for date_key in dates:
        row: dict[str, Any] = {"date": pd.Timestamp(date_key)}
        for param in NASA_PARAMETERS:
            value = parameter_data[param][date_key]
            row[param.lower()] = float(value) if value != -999 else pd.NA
        rows.append(row)

    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.sort_values("date").reset_index(drop=True)

    if frame.empty:
        raise ValueError("NASA POWER pull returned no rows")

    metadata = {
        "source": "NASA POWER daily point",
        "url": NASA_POWER_URL,
        "request_params": params,
        "units": NASA_UNITS,
        "site_key": site_key,
        "provisional": site.coordinates_provisional,
        "coordinates_note": site.coordinates_note,
        "date_span": {
            "start": str(frame["date"].min().date()),
            "end": str(frame["date"].max().date()),
        },
    }
    write_cache(cache_src, PARQUET_NAME, SIDECAR_NAME, frame, metadata)
    return frame, metadata


def validate_nasa_power(frame: pd.DataFrame) -> None:
    """Assert NASA POWER pull is non-empty and physically plausible."""
    expected = set(p.lower() for p in NASA_PARAMETERS)
    missing = expected.difference(frame.columns)
    if missing:
        raise ValueError(f"NASA POWER frame missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("NASA POWER frame is empty")
    if (frame["allsky_sfc_sw_dwn"] < 0).any():
        raise ValueError("NASA ALLSKY_SFC_SW_DWN contains negative values")
    if (frame["t2m"] < -30).any() or (frame["t2m"] > 50).any():
        raise ValueError("NASA T2M outside plausible ambient range")
