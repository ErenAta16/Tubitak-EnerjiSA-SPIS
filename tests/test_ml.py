"""Unit tests for P5 machine-learning pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from spis import config
from spis.ml import (
    FEATURE_COLUMNS,
    assert_no_leakage,
    build_modelling_frame,
    permutation_importance_with_ci,
    prepare_xy,
    time_based_split,
)


def _synthetic_master(n: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    frame = pd.DataFrame(
        {
            "date": dates,
            "production": np.linspace(10000, 9000, n),
            "irradiation": np.full(n, 5000.0),
            "pi": np.linspace(2.0, 1.8, n),
            "pi_temp_corrected": np.linspace(2.0, 1.7, n),
            "is_clean_observation": True,
            "pre_first_wash": False,
            "segment_id": 1,
            "days_since_wash": np.arange(n),
            "rain_day": False,
            "nasa_allsky_kwh_m2": 4.5,
            "nasa_t2m": 15.0,
            "nasa_t2m_max": 20.0,
            "nasa_ws2m": 2.0,
            "nasa_precip_mm": 0.0,
            "pm10": 20.0,
            "dust": 5.0,
            "aerosol_optical_depth": 0.1,
        }
    )
    return frame


def test_leakage_guard_rejects_production() -> None:
    """Production and irradiation must not appear in the feature matrix."""
    assert_no_leakage(list(FEATURE_COLUMNS))
    try:
        assert_no_leakage(["days_since_wash", "production"])
    except ValueError as exc:
        assert "production" in str(exc)
    else:
        raise AssertionError("Expected leakage guard to fail on production")


def test_split_is_time_ordered() -> None:
    """Train dates must precede all test dates."""
    master = _synthetic_master()
    # attach_clearness needs nasa merge columns - mock minimal clearness path
    master["nasa_clrsky_kwh_m2"] = 5.0
    master["clearness_index"] = 0.9
    frame = build_modelling_frame(master)
    split = time_based_split(frame, test_fraction=0.2)
    assert split.train["date"].max() <= split.test["date"].min()
    assert len(split.test) >= 1


def test_pipeline_fits_and_predicts_on_synthetic() -> None:
    """Tiny synthetic frame runs through feature prep and RF predict."""
    master = _synthetic_master(80)
    master["nasa_clrsky_kwh_m2"] = 5.0
    frame = build_modelling_frame(master)
    split = time_based_split(frame, test_fraction=0.25)
    x_train, y_train = prepare_xy(split.train)
    x_test, y_test = prepare_xy(split.test)
    model = RandomForestRegressor(n_estimators=10, random_state=config.RANDOM_STATE)
    model.fit(x_train, y_train)
    preds = model.predict(x_test)
    assert len(preds) == len(y_test)
    assert not np.isnan(preds).any()


def test_permutation_importance_one_score_per_feature() -> None:
    """Permutation importance returns one row per feature."""
    rng = np.random.default_rng(config.RANDOM_STATE)
    x = pd.DataFrame(
        {col: rng.normal(size=40) for col in FEATURE_COLUMNS}
    )
    y = pd.Series(rng.normal(size=40))
    model = RandomForestRegressor(n_estimators=20, random_state=config.RANDOM_STATE)
    model.fit(x, y)
    result = permutation_importance_with_ci(model, x, y)
    assert len(result) == len(FEATURE_COLUMNS)
    assert set(result["feature"]) == set(FEATURE_COLUMNS)
