"""Unit tests for P3.5 soiling robustness analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd

from spis.robustness import (
    hac_regression,
    high_clearness_mask,
    identify_rain_events,
    quantify_rain_recovery,
)


def test_high_clearness_mask_selects_by_threshold() -> None:
    frame = pd.DataFrame({"clearness_index": [0.5, 0.75, 0.9, pd.NA]})
    mask = high_clearness_mask(frame)
    assert mask.tolist() == [False, True, True, False]


def test_hac_standard_errors_wider_than_naive_on_autocorrelated_data() -> None:
    rng = np.random.default_rng(42)
    n = 200
    shock = rng.normal(size=n)
    errors = np.zeros(n)
    for idx in range(1, n):
        errors[idx] = 0.85 * errors[idx - 1] + shock[idx]
    x = np.cumsum(rng.normal(size=n))
    y = 0.4 * x + errors
    frame = pd.DataFrame({"x_accumulated": x, "pi_residual": y})
    result = hac_regression(frame, "pi_residual", ["x_accumulated"])
    coef = result["coefficients"]["x_accumulated"]
    assert coef["hac_se"] > coef["naive_se"]


def test_identify_rain_events_groups_consecutive_days() -> None:
    dates = pd.date_range("2024-01-01", periods=7, freq="D")
    master = pd.DataFrame(
        {
            "date": dates,
            "nasa_precip_mm": [0, 2, 3, 0, 0, 1, 0],
        }
    )
    events = identify_rain_events(master)
    assert len(events) == 2


def test_rain_recovery_uses_before_after_windows() -> None:
    dates = pd.date_range("2024-06-01", periods=10, freq="D")
    pi = [2.0, 2.0, 2.0, 1.8, 1.7, 5.0, 5.0, 2.2, 2.3, 2.4]
    master = pd.DataFrame(
        {
            "date": dates,
            "nasa_precip_mm": [0, 0, 0, 2, 2, 0, 0, 0, 0, 0],
            "pi_temp_corrected": pi,
            "is_clean_observation": True,
            "rain_day": [False, False, False, True, True, False, False, False, False, False],
        }
    )
    stats = quantify_rain_recovery(master)
    assert stats["n_quantified"] >= 1
