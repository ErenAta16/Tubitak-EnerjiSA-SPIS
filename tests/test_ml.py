"""Unit tests for P5/P12 machine-learning pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from spis import config
from spis.ml import (
    FEATURE_COLUMNS,
    TARGET_SOILING_RATIO,
    assert_no_leakage,
    attach_soiling_ratio,
    blocked_cv_metrics,
    build_modelling_frame,
    fit_panel_model,
    permutation_importance_with_ci,
    prepare_xy,
    time_based_split,
)


def _synthetic_segments() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "segment_id": [1],
            "baseline_pi_temp_corrected": [2.0],
            "soiling_rate_pct_per_day": [-0.1],
        }
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


def test_soiling_ratio_uses_segment_baseline() -> None:
    """Soiling ratio equals 100 * pi / P3 segment baseline."""
    master = _synthetic_master(10)
    segments = _synthetic_segments()
    frame = attach_soiling_ratio(master, segments)
    expected = 100.0 * master["pi_temp_corrected"] / 2.0
    assert np.allclose(frame[TARGET_SOILING_RATIO], expected)


def test_split_is_time_ordered() -> None:
    """Train dates must precede all test dates."""
    master = _synthetic_master()
    master["nasa_clrsky_kwh_m2"] = 5.0
    master["clearness_index"] = 0.9
    frame = build_modelling_frame(master, _synthetic_segments())
    split = time_based_split(frame, test_fraction=0.2)
    assert split.train["date"].max() <= split.test["date"].min()
    assert len(split.test) >= 1


def test_pipeline_fits_and_predicts_on_synthetic() -> None:
    """Tiny synthetic frame runs through feature prep and RF predict."""
    master = _synthetic_master(80)
    master["nasa_clrsky_kwh_m2"] = 5.0
    frame = build_modelling_frame(master, _synthetic_segments())
    split = time_based_split(frame, test_fraction=0.25)
    x_train, y_train = prepare_xy(split.train, TARGET_SOILING_RATIO)
    x_test, y_test = prepare_xy(split.test, TARGET_SOILING_RATIO)
    model = RandomForestRegressor(n_estimators=10, random_state=config.RANDOM_STATE)
    model.fit(x_train, y_train)
    preds = model.predict(x_test)
    assert len(preds) == len(y_test)
    assert not np.isnan(preds).any()


def test_blocked_cv_returns_all_models() -> None:
    """Blocked CV returns finite mean/std metrics."""
    master = _synthetic_master(120)
    master["nasa_clrsky_kwh_m2"] = 5.0
    frame = build_modelling_frame(master, _synthetic_segments())
    split = time_based_split(frame, test_fraction=0.2)
    cv = blocked_cv_metrics(split.train, TARGET_SOILING_RATIO, "mean_baseline", n_splits=3)
    assert cv.n_folds == 3
    assert np.isfinite(cv.r2_mean)
    assert cv.r2_std >= 0.0


def test_scaled_models_use_pipeline() -> None:
    """Non-tree panel models must use a StandardScaler pipeline."""
    rng = np.random.default_rng(config.RANDOM_STATE)
    x = pd.DataFrame({col: rng.normal(size=60) for col in FEATURE_COLUMNS})
    y = pd.Series(rng.normal(size=60))
    pipe = fit_panel_model("ridge", x, y)
    assert hasattr(pipe, "named_steps")
    assert "scaler" in pipe.named_steps


def test_panel_model_registry_covers_families() -> None:
    """P13 panel includes baselines, linear, kernel, tree, boosting, and MLP."""
    from spis.ml import PANEL_MODELS

    assert len(PANEL_MODELS) == 15
    assert "mlp" in PANEL_MODELS
    assert "svr_rbf" in PANEL_MODELS
    """Permutation importance returns one row per feature."""
    rng = np.random.default_rng(config.RANDOM_STATE)
    x = pd.DataFrame({col: rng.normal(size=40) for col in FEATURE_COLUMNS})
    y = pd.Series(rng.normal(size=40))
    model = RandomForestRegressor(n_estimators=20, random_state=config.RANDOM_STATE)
    model.fit(x, y)
    result = permutation_importance_with_ci(model, x, y)
    assert len(result) == len(FEATURE_COLUMNS)
    assert set(result["feature"]) == set(FEATURE_COLUMNS)
