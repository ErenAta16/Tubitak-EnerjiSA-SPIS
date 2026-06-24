"""Single source of truth for paths, plant constants, and analysis tunables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

ROOT: Path = _ROOT
DATA_RAW: Path = ROOT / "data" / "raw"
DATA_INTERIM: Path = ROOT / "data" / "interim"
DATA_PROCESSED: Path = ROOT / "data" / "processed"
DATA_EXTERNAL: Path = ROOT / "data" / "external"
REPORTS: Path = ROOT / "reports"
FIGURES: Path = REPORTS / "figures"

RAW_IRRADIANCE_PRODUCTION: Path = DATA_RAW / "Canakkale_Uretim_isinim_verileri.xlsx"
RAW_DOWNTIME_EVENTS: Path = DATA_RAW / "Canakkale_Hibrit_GES_Duruslar.xlsx"
RAW_INVERTER_DAILY: Path = DATA_RAW / "Canakkale-1_Hibrit_GES_gunluk_inverter_uretimi.xlsx"
RAW_WASHING_DATES: Path = DATA_RAW / "Panel_yikama_tarihleri.txt"

MODULE_PMAX_TEMP_COEFF: float = -0.0035
MODULE_NOCT_C: float = 45.0
STC_REF_TEMP_C: float = 25.0
INVERTER_AC_KVA: float = 250.0
INVERTER_COUNT: int = 11
FEEDERS: tuple[str, ...] = ("EFLATUN", "HIPOKRAT")
PLANT_LAT: float = 39.86857
PLANT_LON: float = 26.24152

# Derived at clean time from LOW_IRRADIATION_PERCENTILE; snapshot ~1125 Wh/m2/day (P2).
LOW_IRRADIATION_CUTOFF: float | None = None
LOW_IRRADIATION_PERCENTILE: float = 0.05
RAIN_DAY_PRECIP_MM: float = 1.0
NOCT_PEAK_SUN_HOURS: float = 6.0
SCADA_IRRADIATION_UNITS: str = "Wh/m2/day"
RANDOM_STATE: int = 42

IRRADIANCE_START_DATE: str = "2023-01-01"
IRRADIANCE_END_DATE: str = "2025-10-22"
INVERTER_COMMISSIONING_END_DATE: str = "2025-01-22"

SHEET_IRRADIANCE_SUBSTRING: str = "Hibrit GES"
SHEET_DOWNTIME_SUBSTRING: str = "Duru"
SHEET_INVERTER_SUBSTRING: str = "ANAKKALE 1"


@dataclass(frozen=True)
class SpisConfig:
    """Typed bundle of project paths and constants for clean imports."""

    root: Path
    data_raw: Path
    data_interim: Path
    data_processed: Path
    data_external: Path
    reports: Path
    figures: Path
    raw_irradiance_production: Path
    raw_downtime_events: Path
    raw_inverter_daily: Path
    raw_washing_dates: Path
    module_pmax_temp_coeff: float
    module_noct_c: float
    stc_ref_temp_c: float
    inverter_ac_kva: float
    inverter_count: int
    feeders: tuple[str, ...]
    plant_lat: float
    plant_lon: float
    low_irradiation_cutoff: float | None
    random_state: int


config = SpisConfig(
    root=ROOT,
    data_raw=DATA_RAW,
    data_interim=DATA_INTERIM,
    data_processed=DATA_PROCESSED,
    data_external=DATA_EXTERNAL,
    reports=REPORTS,
    figures=FIGURES,
    raw_irradiance_production=RAW_IRRADIANCE_PRODUCTION,
    raw_downtime_events=RAW_DOWNTIME_EVENTS,
    raw_inverter_daily=RAW_INVERTER_DAILY,
    raw_washing_dates=RAW_WASHING_DATES,
    module_pmax_temp_coeff=MODULE_PMAX_TEMP_COEFF,
    module_noct_c=MODULE_NOCT_C,
    stc_ref_temp_c=STC_REF_TEMP_C,
    inverter_ac_kva=INVERTER_AC_KVA,
    inverter_count=INVERTER_COUNT,
    feeders=FEEDERS,
    plant_lat=PLANT_LAT,
    plant_lon=PLANT_LON,
    low_irradiation_cutoff=LOW_IRRADIATION_CUTOFF,
    random_state=RANDOM_STATE,
)
