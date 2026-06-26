"""Upload-mode analysis for the Streamlit UI using core SPIS soiling functions."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from spis import config
from spis.clean import join_washing_segments
from spis.demo_plant import build_demo_robustness_snapshot
from spis.optimize import SoilingRateBand, compute_clean_baseline_energy, load_soiling_rate_band
from spis.robustness import canonical_clear_sky_pooled, compare_clear_sky_slopes
from spis.soiling import build_soiling_segments

UPLOAD_WASH_INTERVAL_DAYS = 85


def build_upload_washing_events(dates: pd.Series) -> pd.DataFrame:
    """Infer periodic wash boundaries for upload-only daily CSV data."""
    ordered = pd.to_datetime(dates).sort_values().drop_duplicates()
    if ordered.empty:
        raise ValueError("Upload frame has no dates.")
    starts = list(ordered.iloc[::UPLOAD_WASH_INTERVAL_DAYS])
    if ordered.iloc[0] not in starts:
        starts = [ordered.iloc[0], *starts]
    rows: list[dict[str, Any]] = []
    for idx, start in enumerate(starts, start=1):
        end = min(start + pd.Timedelta(days=1), ordered.iloc[-1])
        rows.append(
            {
                "start": start,
                "end": end,
                "method": "inferred_upload",
                "event_index_by_date": idx,
                "segment_id": idx,
            }
        )
    return pd.DataFrame(rows)


def prepare_upload_master(frame: pd.DataFrame) -> pd.DataFrame:
    """Build a master-like table from validated upload columns."""
    working = frame.sort_values("date").copy()
    working["pi"] = working["production"] / working["irradiation"]
    working["pi_temp_corrected"] = working["pi"]
    working["is_downtime"] = False
    working["is_curtailment"] = False
    working["is_fault"] = False
    working["is_planned"] = False
    working["downtime_hours"] = 0.0
    working["downtime_reasons"] = ""
    working["nasa_allsky_kwh_m2"] = working["irradiation"] / 1000.0
    rolling_max = working["irradiation"].rolling(21, min_periods=7).max()
    working["clearness_index"] = (working["irradiation"] / rolling_max).clip(0.4, 1.05)
    working["nasa_clrsky_kwh_m2"] = working["nasa_allsky_kwh_m2"] / working["clearness_index"]
    working["nasa_precip_mm"] = 0.0
    working["pm10"] = pd.NA
    working["pm2_5"] = pd.NA
    working["dust"] = pd.NA
    working["aerosol_optical_depth"] = pd.NA
    cutoff = float(working["irradiation"].quantile(config.LOW_IRRADIATION_PERCENTILE))
    working["low_irradiation"] = working["irradiation"] < cutoff
    working["rain_day"] = False
    working["is_clean_observation"] = ~working["low_irradiation"] & ~working["rain_day"]
    washing = build_upload_washing_events(working["date"])
    return join_washing_segments(working, washing)


def analyze_upload_frame(frame: pd.DataFrame) -> dict[str, Any]:
    """Compute clear-sky soiling metrics and optimizer inputs from upload CSV."""
    master = prepare_upload_master(frame)
    washing = build_upload_washing_events(master["date"])
    segments = build_soiling_segments(master, washing)
    if segments.empty:
        raise ValueError(
            "Could not fit soiling segments from the upload. "
            "Provide at least ~120 daily rows with stable production and irradiation."
        )
    segment_compare = compare_clear_sky_slopes(master, segments)
    clear_pooled = canonical_clear_sky_pooled(segment_compare)
    if np.isnan(clear_pooled["pooled_rate"]):
        raise ValueError(
            "Clear-sky soiling fit failed. Check for long gaps, zero irradiation, "
            "or too few clean days between inferred washes."
        )
    robustness = build_demo_robustness_snapshot(master, segments, clear_pooled)
    robustness.loc[0, "pollution_verdict"] = (
        "Upload CSV has no pollution columns; daily HAC pollution test was not run."
    )
    rate_band = load_soiling_rate_band(robustness)
    baseline = compute_clean_baseline_energy(master, segments)
    daily_energy = float(baseline["clean_baseline_kwh_day"].median())
    half = float(clear_pooled["ci_half_width"])
    rate = float(clear_pooled["pooled_rate"])
    return {
        "master": master,
        "clear_sky_rate_pct_per_day": rate,
        "clear_sky_ci_lower": rate - half,
        "clear_sky_ci_upper": rate + half,
        "pollution_verdict": str(robustness.iloc[0]["pollution_verdict"]),
        "daily_energy_kwh": daily_energy,
        "rate_band": rate_band,
    }


def sample_upload_csv_bytes() -> bytes:
    """Return a small template CSV users can download."""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", periods=120, freq="D")
    irradiation = 4000 + rng.normal(0, 200, len(dates))
    production = irradiation * (0.84 + rng.normal(0, 0.01, len(dates)))
    frame = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "production": np.round(production, 1),
            "irradiation": np.round(irradiation, 1),
        }
    )
    return frame.to_csv(index=False).encode("utf-8")
