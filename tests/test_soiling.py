"""Unit tests for soiling analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd

from spis import config
from spis.soiling import (
    build_soiling_segments,
    compute_baseline,
    compute_wash_recovery,
    fit_segment_slope,
    prepare_segment_frame,
    rain_free_clean,
)


def _synthetic_master() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    days_since = np.arange(30, dtype=float)
    pi = 2.0 - 0.002 * days_since
    frame = pd.DataFrame(
        {
            "date": dates,
            "pi": pi,
            "pi_temp_corrected": pi,
            "segment_id": 1,
            "days_since_wash": days_since.astype(int),
            "is_clean_observation": True,
            "rain_day": False,
            "pm10": 20.0,
            "dust": 5.0,
            "aerosol_optical_depth": 0.1,
            "washing_method": "brush_solution",
            "is_open_segment": False,
        }
    )
    frame.loc[10, "rain_day"] = True
    return frame


def test_prepare_segment_frame_excludes_segment_zero() -> None:
    master = _synthetic_master()
    master = pd.concat(
        [
            master,
            pd.DataFrame(
                {
                    "date": [pd.Timestamp("2023-01-01")],
                    "pi": [2.0],
                    "pi_temp_corrected": [2.0],
                    "segment_id": [0],
                    "days_since_wash": [pd.NA],
                    "is_clean_observation": [True],
                    "rain_day": [False],
                    "pm10": [20.0],
                    "dust": [5.0],
                    "aerosol_optical_depth": [0.1],
                    "washing_method": [pd.NA],
                    "is_open_segment": [False],
                }
            ),
        ],
        ignore_index=True,
    )
    prepared = prepare_segment_frame(master)
    assert (prepared["segment_id"] > 0).all()
    assert len(prepared) == len(_synthetic_master())


def test_rain_free_clean_excludes_rain_days() -> None:
    clean = _synthetic_master()
    rain_free = rain_free_clean(clean)
    assert len(rain_free) == len(clean) - 1
    assert not rain_free["rain_day"].any()


def test_fit_segment_slope_recovers_negative_rate() -> None:
    clean = _synthetic_master()
    baseline_temp = compute_baseline(clean, "pi_temp_corrected")
    baseline_raw = compute_baseline(clean, "pi")
    fit = fit_segment_slope(clean, baseline_temp, baseline_raw, segment_id=1)
    assert fit.slope_pct_per_day < 0
    assert fit.n_fit == len(rain_free_clean(clean)) - 1  # days_since_wash > 0


def test_low_confidence_flag_below_threshold(monkeypatch) -> None:
    monkeypatch.setattr(config, "SOILING_MIN_CLEAN_DAYS", 100)
    master = _synthetic_master()
    washing = pd.DataFrame(
        {
            "start": [pd.Timestamp("2024-01-01")],
            "end": [pd.Timestamp("2024-01-02")],
            "method": ["brush_solution"],
            "event_index_by_date": [1],
            "segment_id": [1],
        }
    )
    segments = build_soiling_segments(master, washing)
    assert bool(segments.loc[0, "low_confidence"])


def test_recovery_uses_before_after_windows() -> None:
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    master = pd.DataFrame(
        {
            "date": dates,
            "pi_temp_corrected": np.linspace(1.8, 2.0, len(dates)),
            "is_clean_observation": True,
            "rain_day": False,
        }
    )
    washing = pd.DataFrame(
        {
            "start": [pd.Timestamp("2024-01-10")],
            "end": [pd.Timestamp("2024-01-11")],
            "event_index_by_date": [1],
            "method": ["brush_solution"],
            "segment_id": [1],
        }
    )
    recovery = compute_wash_recovery(master, washing, 0)
    assert recovery["recovery_abs"] > 0
    assert recovery["recovery_positive"]
