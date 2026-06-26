"""Synthetic demo plant data for the public Streamlit UI (no Enerjisa data)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from spis import config
from spis.clean import join_washing_segments
from spis.optimize import SoilingRateBand, compute_clean_baseline_energy, load_soiling_rate_band
from spis.robustness import canonical_clear_sky_pooled, compare_clear_sky_slopes
from spis.soiling import MASTER_INPUT_NAME, SOILING_OUTPUT_NAME, build_soiling_segments

LOGGER = logging.getLogger(__name__)

DEMO_PLANT_KEY = "demo_plant"
DEMO_PLANT_NAME = "Demo Plant (synthetic)"
DEMO_PLANT_DIR = config.ROOT / "data" / "examples" / "demo_plant"
ROBUSTNESS_OUTPUT_NAME = "soiling_robustness"
SYNTHETIC_SOILING_RATE_PCT_PER_DAY = -0.15
SYNTHETIC_WASH_INTERVAL_DAYS = 90
SYNTHETIC_N_DAYS = 600
SYNTHETIC_START_DATE = "2023-01-01"
SYNTHETIC_SEED = 42


def demo_artifact_path(name: str) -> Path:
    """Path to a bundled demo parquet artifact."""
    return DEMO_PLANT_DIR / f"{name}.parquet"


def demo_data_available() -> bool:
    """Return True when the committed synthetic snapshot is present."""
    return demo_artifact_path(MASTER_INPUT_NAME).exists()


def _build_synthetic_washing_events(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Periodic synthetic wash events for segment tagging."""
    starts = list(dates[::SYNTHETIC_WASH_INTERVAL_DAYS])
    if not starts:
        starts = [dates[0]]
    rows: list[dict[str, Any]] = []
    for idx, start in enumerate(starts, start=1):
        end = min(start + pd.Timedelta(days=1), dates[-1])
        rows.append(
            {
                "start": start,
                "end": end,
                "method": "brush_solution",
                "event_index_by_date": idx,
                "segment_id": idx,
            }
        )
    return pd.DataFrame(rows)


def build_synthetic_master(
    *,
    n_days: int = SYNTHETIC_N_DAYS,
    start_date: str = SYNTHETIC_START_DATE,
    seed: int = SYNTHETIC_SEED,
    soiling_rate_pct_per_day: float = SYNTHETIC_SOILING_RATE_PCT_PER_DAY,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate a synthetic daily master table and washing events."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, periods=n_days, freq="D")
    day_of_year = dates.dayofyear.to_numpy()
    irradiation = 4500.0 + 800.0 * np.sin(2.0 * np.pi * (day_of_year - 80.0) / 365.0)
    irradiation = irradiation + rng.normal(0.0, 120.0, n_days)
    irradiation = np.clip(irradiation, 1200.0, None)

    washing = _build_synthetic_washing_events(dates)
    wash_lookup = washing.set_index("start")["event_index_by_date"].to_dict()
    wash_starts = sorted(wash_lookup)

    pi_values: list[float] = []
    days_since: list[int] = []
    last_wash = dates[0]
    pi_after_wash = 0.86
    for date in dates:
        while len(wash_starts) > 1 and date >= wash_starts[1]:
            last_wash = wash_starts[1]
            wash_starts = wash_starts[1:]
            pi_after_wash = 0.86 + rng.normal(0.0, 0.005)
        dsw = int((date - last_wash).days)
        trend = 1.0 + (soiling_rate_pct_per_day / 100.0) * dsw
        noise = 1.0 + rng.normal(0.0, 0.004)
        pi_values.append(pi_after_wash * trend * noise)
        days_since.append(dsw)

    frame = pd.DataFrame(
        {
            "date": dates,
            "production": pi_values * irradiation,
            "irradiation": irradiation,
            "pi": pi_values,
        }
    )
    frame["pi_temp_corrected"] = frame["pi"]
    frame["is_downtime"] = False
    frame["is_curtailment"] = False
    frame["is_fault"] = False
    frame["is_planned"] = False
    frame["downtime_hours"] = 0.0
    frame["downtime_reasons"] = ""
    frame["nasa_t2m"] = 12.0 + 8.0 * np.sin(2.0 * np.pi * (day_of_year - 30.0) / 365.0)
    frame["nasa_allsky_kwh_m2"] = irradiation / 1000.0
    frame["nasa_precip_mm"] = rng.uniform(0.0, 0.4, n_days)
    frame["pm10"] = 20.0 + rng.normal(0.0, 4.0, n_days).cumsum() * 0.01
    frame["pm2_5"] = frame["pm10"] * 0.5
    frame["dust"] = frame["pm10"] * 0.7
    frame["aerosol_optical_depth"] = 0.12 + rng.normal(0.0, 0.01, n_days)
    clearness = 0.78 + rng.uniform(0.0, 0.18, n_days)
    cloudy = rng.random(n_days) < 0.12
    clearness[cloudy] = rng.uniform(0.45, 0.68, cloudy.sum())
    frame["clearness_index"] = clearness
    frame["nasa_clrsky_kwh_m2"] = frame["nasa_allsky_kwh_m2"] / frame["clearness_index"]

    cutoff = float(frame["irradiation"].quantile(config.LOW_IRRADIATION_PERCENTILE))
    frame["low_irradiation"] = frame["irradiation"] < cutoff
    frame["rain_day"] = frame["nasa_precip_mm"] >= config.RAIN_DAY_PRECIP_MM
    frame["is_clean_observation"] = (
        ~frame["low_irradiation"] & ~frame["rain_day"] & ~frame["is_downtime"]
    )
    frame = join_washing_segments(frame, washing)
    return frame, washing


def build_demo_robustness_snapshot(
    master: pd.DataFrame, segments: pd.DataFrame, clear_pooled: dict[str, float]
) -> pd.DataFrame:
    """Minimal robustness table for the demo UI (pollution verdict is illustrative)."""
    half = float(clear_pooled["ci_half_width"])
    return pd.DataFrame(
        [
            {
                "record_type": "p4_verdict",
                "recommended_rate_pct_per_day": clear_pooled["pooled_rate"],
                "recommended_uncertainty_half_width": half,
                "rate_basis": "Synthetic demo clear-sky pooled Theil-Sen",
                "pollution_verdict": (
                    "Synthetic pollution series has no designed causal link to PI; "
                    "daily HAC p>0.05 (demo only)."
                ),
            }
        ]
    )


def generate_demo_plant_artifacts(
    *,
    output_dir: Path | None = None,
    n_days: int = SYNTHETIC_N_DAYS,
    seed: int = SYNTHETIC_SEED,
) -> dict[str, Path]:
    """Build and write synthetic demo parquets deterministically."""
    out_dir = output_dir or DEMO_PLANT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    master, washing = build_synthetic_master(n_days=n_days, seed=seed)
    segments = build_soiling_segments(master, washing)
    segment_compare = compare_clear_sky_slopes(master, segments)
    clear_pooled = canonical_clear_sky_pooled(segment_compare)
    robustness = build_demo_robustness_snapshot(master, segments, clear_pooled)

    paths = {
        MASTER_INPUT_NAME: out_dir / f"{MASTER_INPUT_NAME}.parquet",
        SOILING_OUTPUT_NAME: out_dir / f"{SOILING_OUTPUT_NAME}.parquet",
        ROBUSTNESS_OUTPUT_NAME: out_dir / f"{ROBUSTNESS_OUTPUT_NAME}.parquet",
    }
    master.to_parquet(paths[MASTER_INPUT_NAME], index=False)
    segments.to_parquet(paths[SOILING_OUTPUT_NAME], index=False)
    robustness.to_parquet(paths[ROBUSTNESS_OUTPUT_NAME], index=False)
    LOGGER.info(
        "Wrote synthetic demo plant (%s days) to %s; pooled rate %.4f %%/day",
        len(master),
        out_dir,
        clear_pooled["pooled_rate"],
    )
    return paths


def load_demo_rate_band() -> SoilingRateBand:
    """Load optimizer rate band from bundled demo robustness snapshot."""
    robustness = pd.read_parquet(demo_artifact_path(ROBUSTNESS_OUTPUT_NAME))
    return load_soiling_rate_band(robustness)


def load_demo_daily_energy() -> float:
    """Median clean-baseline daily energy from synthetic demo segments."""
    master = pd.read_parquet(demo_artifact_path(MASTER_INPUT_NAME))
    segments = pd.read_parquet(demo_artifact_path(SOILING_OUTPUT_NAME))
    baseline = compute_clean_baseline_energy(master, segments)
    return float(baseline["clean_baseline_kwh_day"].median())


def load_demo_headline_metrics() -> dict[str, Any]:
    """Return headline metrics for the demo dashboard."""
    robustness = pd.read_parquet(demo_artifact_path(ROBUSTNESS_OUTPUT_NAME))
    verdict = robustness.loc[robustness["record_type"] == "p4_verdict"].iloc[0]
    half = float(verdict["recommended_uncertainty_half_width"])
    rate = float(verdict["recommended_rate_pct_per_day"])
    return {
        "clear_sky_rate_pct_per_day": rate,
        "clear_sky_ci_lower": rate - half,
        "clear_sky_ci_upper": rate + half,
        "pollution_verdict": str(verdict["pollution_verdict"]),
        "daily_energy_kwh": load_demo_daily_energy(),
        "rate_band": load_demo_rate_band(),
    }
