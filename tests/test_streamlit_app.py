"""Smoke tests for the SPIS Streamlit UI logic."""

from __future__ import annotations

import importlib

import pandas as pd
import pytest

from app.ui_logic import (
    build_results_summary_markdown,
    compute_live_optimization,
    default_example_site_key,
    example_site_available,
    list_example_site_options,
    load_dashboard_snapshot,
    load_demo_dashboard_snapshot,
    load_upload_dashboard_snapshot,
    validate_upload_frame,
)
from spis.demo_plant import DEMO_PLANT_KEY
from spis.optimize import SoilingRateBand
from spis.sites import DEFAULT_SITE


def test_validate_upload_frame_accepts_minimal_csv() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=40, freq="D"),
            "production": [1000, 1100, 1200, 1150, 1300] * 8,
            "irradiation": [4000, 4200, 4100, 3900, 4300] * 8,
        }
    )
    result = validate_upload_frame(frame)
    assert result.ok
    assert result.frame is not None
    assert len(result.frame) == 40


def test_validate_upload_frame_rejects_zero_irradiation() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "production": [1000, 1100, 1200, 1150, 1300],
            "irradiation": [4000, 0, 4100, 3900, 4300],
        }
    )
    result = validate_upload_frame(frame)
    assert not result.ok


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


def test_demo_plant_dashboard_headless_end_to_end() -> None:
    assert default_example_site_key() == DEMO_PLANT_KEY
    snap = load_demo_dashboard_snapshot()
    assert snap.available
    assert snap.rate_band is not None
    assert snap.clear_sky_rate_pct_per_day is not None
    assert snap.master is not None
    optimization = compute_live_optimization(
        150_000,
        1500,
        snap.rate_band,
        snap.daily_energy_kwh or 10_000,
    )
    summary = build_results_summary_markdown(snap, optimization)
    assert "Soiling" in summary
    assert snap.clear_sky_rate_pct_per_day is not None


def test_upload_mode_computes_soiling_rate() -> None:
    rng = pd.Series([0.84 - 0.0015 * i for i in range(120)])
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=120, freq="D"),
            "production": 4000 * rng,
            "irradiation": [4000.0] * 120,
        }
    )
    snap = load_upload_dashboard_snapshot(frame)
    assert snap.available
    assert snap.clear_sky_rate_pct_per_day is not None
    assert snap.rate_band is not None
    assert snap.clear_sky_ci_lower is not None


def test_example_site_list_defaults_to_demo() -> None:
    options = list_example_site_options()
    assert options[0].site_key == DEMO_PLANT_KEY


def test_load_canakkale_dashboard_when_processed_data_exists() -> None:
    if not example_site_available(DEFAULT_SITE):
        pytest.skip("Canakkale processed data not present locally")
    snap = load_dashboard_snapshot(DEFAULT_SITE)
    assert snap.available
    assert snap.rate_band is not None


def test_streamlit_app_imports_without_data_processed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        "spis.config.DATA_PROCESSED",
        tmp_path / "missing_processed",
    )
    module = importlib.import_module("app.streamlit_app")
    assert hasattr(module, "main")
    snap = load_demo_dashboard_snapshot()
    assert snap.available
