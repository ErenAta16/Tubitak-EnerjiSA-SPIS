"""Smoke tests for the SPIS Streamlit UI logic."""

from __future__ import annotations

import pandas as pd

from app.ui_logic import (
    compute_live_optimization,
    example_site_available,
    load_dashboard_snapshot,
    validate_upload_frame,
)
from spis.optimize import SoilingRateBand
from spis.sites import DEFAULT_SITE


def test_validate_upload_frame_accepts_minimal_csv() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "production": [1000, 1100, 1200, 1150, 1300],
            "irradiation": [4000, 4200, 4100, 3900, 4300],
        }
    )
    result = validate_upload_frame(frame)
    assert result.ok
    assert result.frame is not None
    assert len(result.frame) == 5


def test_compute_live_optimization_returns_t_star() -> None:
    band = SoilingRateBand(
        point=0.00125,
        low=0.001,
        high=0.0015,
        source="test",
        half_width=0.00025,
    )
    out = compute_live_optimization(150_000, 1500, band, 10_000)
    assert out["t_star_days"] > 0
    assert not out["cost_curve"].empty


def test_load_canakkale_dashboard_when_processed_data_exists() -> None:
    if not example_site_available(DEFAULT_SITE):
        return
    snap = load_dashboard_snapshot(DEFAULT_SITE)
    assert snap.available
    assert snap.rate_band is not None
    assert snap.clear_sky_rate_pct_per_day is not None


def test_streamlit_app_imports() -> None:
    import importlib

    module = importlib.import_module("app.streamlit_app")
    assert hasattr(module, "main")
