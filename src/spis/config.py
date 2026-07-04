"""Single source of truth for paths, plant constants, and analysis tunables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

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

# Canakkale coordinates: precise values belong in local .env (not committed).
PLANT_LAT_COARSE_DEFAULT: float = 39.9
PLANT_LON_COARSE_DEFAULT: float = 26.2


def _load_env_file() -> None:
    """Load KEY=VALUE pairs from .env into os.environ when not already set."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_plant_coordinates() -> tuple[float, float, str]:
    """Return plant lat/lon and source label (env or coarse_default)."""
    lat_raw = os.environ.get("PLANT_LAT", "").strip()
    lon_raw = os.environ.get("PLANT_LON", "").strip()
    if lat_raw and lon_raw:
        return float(lat_raw), float(lon_raw), "env"
    if lat_raw or lon_raw:
        raise ValueError("Set both PLANT_LAT and PLANT_LON in .env, or leave both unset.")
    return PLANT_LAT_COARSE_DEFAULT, PLANT_LON_COARSE_DEFAULT, "coarse_default"


_load_env_file()
PLANT_LAT, PLANT_LON, PLANT_COORD_SOURCE = _resolve_plant_coordinates()


def log_plant_coordinate_source() -> None:
    """Log which coordinate source is active for Canakkale external pulls."""
    if PLANT_COORD_SOURCE == "env":
        LOGGER.info(
            "Canakkale coordinates from PLANT_LAT/PLANT_LON (.env): lat=%.5f, lon=%.5f",
            PLANT_LAT,
            PLANT_LON,
        )
        return
    LOGGER.info(
        "Canakkale coordinates using coarse public default (set PLANT_LAT/PLANT_LON "
        "in .env for precise location): lat=%.1f, lon=%.1f",
        PLANT_LAT,
        PLANT_LON,
    )


# Derived at clean time from LOW_IRRADIATION_PERCENTILE; snapshot ~1125 Wh/m2/day (P2).
LOW_IRRADIATION_CUTOFF: float | None = None
LOW_IRRADIATION_PERCENTILE: float = 0.05
RAIN_DAY_PRECIP_MM: float = 1.0
NOCT_PEAK_SUN_HOURS: float = 6.0
SCADA_IRRADIATION_UNITS: str = "Wh/m2/day"
RANDOM_STATE: int = 42

SOILING_BASELINE_CLEAN_DAYS: int = 3
SOILING_RECOVERY_WINDOW_DAYS: int = 3
SOILING_MIN_CLEAN_DAYS: int = 10
SOILING_BOOTSTRAP_SAMPLES: int = 200

CLEARNESS_INDEX_MIN: float = 0.7
RAIN_EVENT_PRECIP_MM: float = 1.0
RAIN_RECOVERY_WINDOW_DAYS: int = 3
HAC_MAX_LAGS: int = 7
BLOCK_BOOTSTRAP_SAMPLES: int = 200

# P14/P16 inferred cleaning at sites without wash logs (DKASC Alice Springs).
INFERRED_CLEANING_RAIN_MM: float = 10.0
INFERRED_CLEANING_PI_STEP_PCT: float = 5.0
INFERRED_CLEANING_ROLLING_DAYS: int = 7
INFERRED_CLEANING_MERGE_DAYS: int = 3
INFERRED_CLEANING_MIN_DAYS_BETWEEN: int = 14

INFERRED_CLEANING_PRESETS: dict[str, dict[str, float | int]] = {
    "strict": {
        "rain_mm": 15.0,
        "pi_step_pct": 7.0,
        "min_days_between": 21,
    },
    "default": {
        "rain_mm": INFERRED_CLEANING_RAIN_MM,
        "pi_step_pct": INFERRED_CLEANING_PI_STEP_PCT,
        "min_days_between": INFERRED_CLEANING_MIN_DAYS_BETWEEN,
    },
    "sensitive": {
        "rain_mm": 5.0,
        "pi_step_pct": 3.0,
        "min_days_between": 7,
    },
}

# Prefer cumulative counter when daily register is positive and within this ratio band.
DKASC_COUNTER_RATIO_MIN: float = 0.85
DKASC_COUNTER_RATIO_MAX: float = 1.15
DKASC_COUNTER_VALID_FRACTION: float = 0.95

# P17 PVDAQ 2107: tighter inferred cleaning (NASA winter rain otherwise over-segments).
PVDAQ_INFERRED_CLEANING_RAIN_MM: float = 25.0
PVDAQ_INFERRED_CLEANING_PI_STEP_PCT: float = 7.0
PVDAQ_INFERRED_CLEANING_MIN_DAYS_BETWEEN: int = 30

# P4 washing optimization (ASSUMED until Enerjisa/EPIAS supply real values).
PRODUCTION_UNITS: str = "kWh/day"
PLANT_AC_CAPACITY_KW: float = INVERTER_AC_KVA * INVERTER_COUNT
WASH_COST_TL_SWEEP: tuple[float, ...] = (50_000.0, 100_000.0, 150_000.0, 200_000.0, 300_000.0)
WASH_COST_TL_CENTRAL: float = 150_000.0
WASH_COST_BASIS: str = (
    "ASSUMED plausible range for full-plant brush/robot wash (TBD from Enerjisa); "
    "50k-300k TL spans a plausible TL/kW_AC range for nominal plant AC capacity."
)
PTF_TL_MWH_SWEEP: tuple[float, ...] = (1000.0, 1500.0, 2000.0, 2500.0, 3000.0, 3500.0)
PTF_TL_MWH_CENTRAL_ASSUMED_LEGACY: float = 2000.0
PTF_SWEEP_BASIS: str = (
    "ASSUMED sensitivity range for 2024-2025 when only 2023 PTF CSV is available; "
    "sweep grid points are not realized prices."
)
PTF_REAL_BASIS: str = (
    "REAL 2023 annual-mean PTF from EPIAS CSV in data/external/epias_ptf/; "
    "2023-only nominal TL; 2024-2025 not supplied. If wash cost is later given "
    "in current TL without rebasing, the 2023 nominal price biases T* longer."
)
EPIAS_PTF_DIR: Path = DATA_EXTERNAL / "epias_ptf"
OPTIMIZE_GRID_MAX_DAYS: int = 365
OPTIMIZE_GRID_STEP_DAYS: int = 1
OPTIMIZE_CLOSED_FORM_TOLERANCE_DAYS: float = 1.0

# P5 machine-learning layer.
ML_TEST_FRACTION: float = 0.2
ML_CV_SPLITS: int = 5
ML_PERMUTATION_REPEATS: int = 10
ML_MODEL_FILENAME: str = "ml_model.joblib"
ML_FEATURES_FILENAME: str = "ml_feature_list.json"
ML_METRICS_OUTPUT_NAME: str = "ml_model_metrics"
ML_RF_PARAM_GRID: dict[str, list] = {
    "n_estimators": [100, 200],
    "max_depth": [5, 10, None],
    "min_samples_leaf": [1, 3, 5],
}
ML_LEAKAGE_FORBIDDEN: frozenset[str] = frozenset(
    {
        "production",
        "irradiation",
        "pi",
        "pi_temp_corrected",
        "eflatun_production",
        "hipokrat_production",
        "soiling_ratio",
    }
)

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

# Multi-site registry (path helpers in spis.sites).
from spis.sites import SITES, SiteConfig, get_site  # noqa: E402, F401
