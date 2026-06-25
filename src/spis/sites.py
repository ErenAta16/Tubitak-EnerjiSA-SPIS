"""Site registry and path helpers for multi-site SPIS runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spis import config

DEFAULT_SITE = "canakkale"
PANEL_CLASS_JINKO_535 = "Jinko JKM535 bifacial"
PANEL_CLASS_CANADIAN_SOLAR_POLY = "Canadian Solar poly-Si fixed (DKASC array 32, 5.3 kW)"
ALICE_SPRINGS_MODULE_TEMP_COEFF = -0.0041


@dataclass(frozen=True)
class SiteConfig:
    """Configuration for one plant site."""

    key: str
    name: str
    lat: float
    lon: float
    raw_data_dir: Path
    processed_namespace: str
    panel_class: str
    operational_data_available: bool
    coordinates_provisional: bool
    coordinates_note: str
    analysis_start_date: str | None = None
    analysis_end_date: str | None = None
    module_temp_coeff: float | None = None

    def resolved_analysis_start(self) -> str:
        return self.analysis_start_date or config.IRRADIANCE_START_DATE

    def resolved_analysis_end(self) -> str:
        return self.analysis_end_date or config.IRRADIANCE_END_DATE

    def resolved_module_temp_coeff(self) -> float:
        return (
            self.module_temp_coeff
            if self.module_temp_coeff is not None
            else config.MODULE_PMAX_TEMP_COEFF
        )


def _canakkale_site() -> SiteConfig:
    return SiteConfig(
        key="canakkale",
        name="Canakkale Hybrid GES",
        lat=39.86857,
        lon=26.24152,
        raw_data_dir=config.DATA_RAW,
        processed_namespace="canakkale",
        panel_class=PANEL_CLASS_JINKO_535,
        operational_data_available=True,
        coordinates_provisional=False,
        coordinates_note="Confirmed plant coordinates (P2).",
    )


def _alice_springs_site() -> SiteConfig:
    return SiteConfig(
        key="alice_springs",
        name="DKASC Alice Springs (array 32)",
        lat=-23.762,
        lon=133.874,
        raw_data_dir=config.DATA_EXTERNAL / "dkasc",
        processed_namespace="alice_springs",
        panel_class=PANEL_CLASS_CANADIAN_SOLAR_POLY,
        operational_data_available=True,
        coordinates_provisional=False,
        coordinates_note=(
            "DKASC public research array; Canadian Solar 5.3 kW poly-Si fixed tilt. "
            "Washing events inferred from rainfall and PI step-changes (no wash log)."
        ),
        analysis_start_date=config.IRRADIANCE_START_DATE,
        analysis_end_date=config.IRRADIANCE_END_DATE,
        module_temp_coeff=ALICE_SPRINGS_MODULE_TEMP_COEFF,
    )


def _balikesir_site() -> SiteConfig:
    return SiteConfig(
        key="balikesir",
        name="Balikesir RES (provisional)",
        lat=39.748,
        lon=27.996,
        raw_data_dir=config.DATA_RAW / "balikesir",
        processed_namespace="balikesir",
        panel_class=PANEL_CLASS_JINKO_535,
        operational_data_available=False,
        coordinates_provisional=True,
        coordinates_note=(
            "PROVISIONAL placeholder for Balikesir RES area pending KMZ confirmation; "
            "no operational SCADA files present under data/raw/balikesir/."
        ),
    )


SITES: dict[str, SiteConfig] = {
    "canakkale": _canakkale_site(),
    "balikesir": _balikesir_site(),
    "alice_springs": _alice_springs_site(),
}


def get_site(site_key: str = DEFAULT_SITE) -> SiteConfig:
    """Return site configuration or raise."""
    if site_key not in SITES:
        raise KeyError(f"Unknown site {site_key!r}; known: {sorted(SITES)}")
    return SITES[site_key]


def site_processed_dir(site_key: str) -> Path:
    """Directory for processed artifacts; Canakkale keeps legacy flat layout."""
    site = get_site(site_key)
    if site.key == DEFAULT_SITE:
        return config.DATA_PROCESSED
    return config.DATA_PROCESSED / site.processed_namespace


def site_processed_path(site_key: str, name: str) -> Path:
    """Path to a processed parquet artifact for a site."""
    return site_processed_dir(site_key) / f"{name}.parquet"


def site_interim_dir(site_key: str) -> Path:
    """Directory for interim artifacts; Canakkale keeps legacy flat layout."""
    site = get_site(site_key)
    if site.key == DEFAULT_SITE:
        return config.DATA_INTERIM
    return config.DATA_INTERIM / site.processed_namespace


def site_interim_path(site_key: str, name: str) -> Path:
    """Path to an interim parquet artifact for a site."""
    return site_interim_dir(site_key) / f"{name}.parquet"


def site_external_subdir(source: str, site_key: str) -> str:
    """Cache subdirectory under data/external/<source>/ for a site."""
    site = get_site(site_key)
    if site.key == DEFAULT_SITE:
        return source
    return f"{source}/{site.processed_namespace}"


def site_raw_paths(site_key: str) -> dict[str, Path]:
    """Return raw input paths for a site (Canakkale uses legacy flat filenames)."""
    site = get_site(site_key)
    if site.key == DEFAULT_SITE:
        return {
            "irradiance": config.RAW_IRRADIANCE_PRODUCTION,
            "downtime": config.RAW_DOWNTIME_EVENTS,
            "inverter": config.RAW_INVERTER_DAILY,
            "washing": config.RAW_WASHING_DATES,
        }
    raw_dir = site.raw_data_dir
    return {
        "irradiance": raw_dir / "irradiance_production.xlsx",
        "downtime": raw_dir / "downtime_events.xlsx",
        "inverter": raw_dir / "inverter_daily.xlsx",
        "washing": raw_dir / "washing_dates.txt",
    }


def provisional_label(site_key: str) -> str:
    """Human-readable provisional flag for reports."""
    site = get_site(site_key)
    if site.coordinates_provisional or not site.operational_data_available:
        return "PROVISIONAL"
    return "CONFIRMED"
