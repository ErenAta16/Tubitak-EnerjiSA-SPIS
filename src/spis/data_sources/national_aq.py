"""Turkish national air-quality station data (sim.csb.gov.tr / havaizleme.gov.tr)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import requests
import urllib3

from spis import config
from spis.data_sources._cache import read_cache, write_cache

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOGGER = logging.getLogger(__name__)

SOURCE_NAME = "national_aq"
BASE_URL = "https://sim.csb.gov.tr"
DOWNLOAD_FORM = f"{BASE_URL}/STN/STN_Report/StationDataDownloadNew"
DOWNLOAD_DATA = f"{BASE_URL}/STN/STN_Report/StationDataDownloadNewData"
STATIONS_API = f"{BASE_URL}/Services/GetAirQualityStations?type=0"
PARQUET_NAME = "daily_ground.parquet"
SIDECAR_NAME = "daily_ground.json"
DATE_FMT = "%d.%m.%Y %H:%M"
PARAM_PM10 = "PM10"
PARAM_PM25 = "PM25"
UNITS = {"pm10": "ug/m3", "pm2_5": "ug/m3"}


@dataclass(frozen=True)
class NationalStation:
    """Ground-station metadata tied to an SPIS site key."""

    site_key: str
    station_code: str
    station_name: str
    city: str
    town: str


STATIONS: tuple[NationalStation, ...] = (
    NationalStation(
        site_key="canakkale",
        station_code="TR170141",
        station_name="Canakkale (UHKIA Merkez)",
        city="Canakkale",
        town="Merkez",
    ),
    NationalStation(
        site_key="balikesir",
        station_code="TR100241",
        station_name="Balikesir - Bandirma-MTHM",
        city="Balikesir",
        town="Bandirma",
    ),
)


def get_national_station(site_key: str) -> NationalStation:
    """Return configured ground station for a site key."""
    for station in STATIONS:
        if station.site_key == site_key:
            return station
    raise KeyError(f"No national AQ station configured for site {site_key!r}")


def _session_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
    }


def _fetch_verification_token(session: requests.Session) -> str:
    response = session.get(
        DOWNLOAD_FORM,
        headers=_session_headers(DOWNLOAD_FORM),
        verify=False,
        timeout=60,
    )
    response.raise_for_status()
    match = re.search(
        r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"',
        response.text,
    )
    if not match:
        raise RuntimeError(
            "Could not parse anti-forgery token from StationDataDownloadNew form; "
            "portal layout may have changed."
        )
    return match.group(1)


def _resolve_station_uuid(session: requests.Session, station_code: str) -> str:
    response = session.get(
        STATIONS_API,
        headers={
            **_session_headers(f"{BASE_URL}/Services/AirQuality"),
            "Accept": "application/json",
        },
        verify=False,
        timeout=60,
    )
    response.raise_for_status()
    for station in response.json()["objects"]:
        if station.get("Code") == station_code:
            return str(station["id"])
    raise ValueError(f"Station code {station_code!r} not found in national registry")


def _download_parameter(
    session: requests.Session,
    station_uuid: str,
    parameter: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    token = _fetch_verification_token(session)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").strftime(DATE_FMT)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23).strftime(DATE_FMT)
    response = session.post(
        DOWNLOAD_DATA,
        headers=_session_headers(DOWNLOAD_FORM),
        data={
            "__RequestVerificationToken": token,
            "StationType": "1",
            "StationIds": station_uuid,
            "StartDateTime": start_dt,
            "EndDateTime": end_dt,
            "DataPeriods": "T1440",
            "Parameters": parameter,
            "SourceType": "0",
            "AreaType": "0",
        },
        verify=False,
        timeout=180,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("Result"):
        raise ValueError(f"National AQ download failed for {parameter}: {payload}")
    rows = payload.get("Object", {}).get("Data")
    if rows is None:
        raise ValueError(f"National AQ download returned no Data block for {parameter}")
    return rows


def _normalize_rows(
    pm10_rows: list[dict[str, Any]],
    pm25_rows: list[dict[str, Any]],
    station: NationalStation,
    station_uuid: str,
) -> pd.DataFrame:
    pm10 = pd.DataFrame(pm10_rows)
    pm25 = pd.DataFrame(pm25_rows)
    if pm10.empty:
        raise ValueError(f"No PM10 rows returned for {station.station_code}")

    pm10 = pm10.rename(columns={"ReadTime": "date", "PM10": "pm10"})
    pm10["date"] = pd.to_datetime(pm10["date"]).dt.normalize()
    frame = pm10[["date", "pm10"]].copy()
    if pm25_rows:
        pm25 = pd.DataFrame(pm25_rows)
        pm25 = pm25.rename(columns={"ReadTime": "date", "PM25": "pm2_5"})
        pm25["date"] = pd.to_datetime(pm25["date"]).dt.normalize()
        frame = frame.merge(pm25[["date", "pm2_5"]], on="date", how="outer")
    else:
        frame["pm2_5"] = pd.NA
    frame = frame.sort_values("date").reset_index(drop=True)
    frame["site_key"] = station.site_key
    frame["station_code"] = station.station_code
    frame["station_name"] = station.station_name
    frame["station_uuid"] = station_uuid
    frame["source"] = "Turkish National AQ (sim.csb.gov.tr StationDataDownloadNewData)"

    if (frame["pm10"].dropna() < 0).any() or (frame["pm2_5"].dropna() < 0).any():
        raise ValueError("Negative ground PM values encountered")
    return frame


def fetch_national_aq_daily(
    site_key: str,
    force_refresh: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch or load cached daily ground PM10/PM2.5 for a configured site station."""
    station = get_national_station(site_key)
    start = start_date or config.IRRADIANCE_START_DATE
    end = end_date or config.IRRADIANCE_END_DATE
    cache_src = f"{SOURCE_NAME}/{site_key}"

    if not force_refresh:
        try:
            frame, metadata = read_cache(cache_src, PARQUET_NAME, SIDECAR_NAME)
            validate_national_aq(frame)
            return frame, metadata
        except FileNotFoundError:
            pass

    session = requests.Session()
    station_uuid = _resolve_station_uuid(session, station.station_code)
    pm10_rows = _download_parameter(session, station_uuid, PARAM_PM10, start, end)
    try:
        pm25_rows = _download_parameter(session, station_uuid, PARAM_PM25, start, end)
    except ValueError as exc:
        LOGGER.warning(
            "PM25 unavailable for %s (%s): %s; continuing with PM10 only",
            station.station_code,
            site_key,
            exc,
        )
        pm25_rows = []
    frame = _normalize_rows(pm10_rows, pm25_rows, station, station_uuid)
    validate_national_aq(frame)

    metadata = {
        "source": "Turkish National Air Quality Monitoring Network",
        "portal": BASE_URL,
        "endpoint": DOWNLOAD_DATA,
        "station_code": station.station_code,
        "station_name": station.station_name,
        "station_uuid": station_uuid,
        "site_key": site_key,
        "request_window": {"start": start, "end": end},
        "aggregation": "daily (T1440)",
        "units": UNITS,
        "parameters": [PARAM_PM10, PARAM_PM25],
    }
    write_cache(cache_src, PARQUET_NAME, SIDECAR_NAME, frame, metadata)
    return frame, metadata


def validate_national_aq(frame: pd.DataFrame) -> None:
    """Assert ground AQ frame has expected columns and non-empty PM10 coverage."""
    required = {"date", "pm10", "pm2_5", "site_key", "station_code"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"National AQ frame missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("National AQ frame is empty")
    if frame["pm10"].notna().sum() == 0:
        raise ValueError("National AQ PM10 column is entirely null")
