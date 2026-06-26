"""Tests for multi-site registry, comparison, and inverter anomaly."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from spis import config
from spis.clean import MASTER_OUTPUT_NAME, build_master_table
from spis.inverter_anomaly import (
    UNDERPERFORMER_MEDIAN_THRESHOLD,
    compute_relative_performance,
    rank_inverters,
)
from spis.site_comparison import compare_ground_to_cams, run_pollution_difference_tests
from spis.sites import DEFAULT_SITE, SITES, get_site, site_processed_path

CANAKKALE_MASTER_HASH = "e1574bac5420e007ac3c04b35ab399d9c0daa089ac3490e210df8807b70ddcc2"


def test_sites_registry_has_required_fields() -> None:
    assert set(SITES) == {"canakkale", "balikesir", "alice_springs", "pvdaq_2107"}
    can = get_site("canakkale")
    bal = get_site("balikesir")
    assert can.operational_data_available
    assert not bal.operational_data_available
    assert can.coordinates_provisional is False
    assert bal.coordinates_provisional is True
    assert can.panel_class == bal.panel_class
    assert can.lat == pytest.approx(39.86857)
    assert can.lon == pytest.approx(26.24152)


def test_canakkale_processed_paths_legacy_flat() -> None:
    path = site_processed_path("canakkale", MASTER_OUTPUT_NAME)
    assert path == config.DATA_PROCESSED / f"{MASTER_OUTPUT_NAME}.parquet"


@pytest.mark.integration
def test_canakkale_master_hash_unchanged_after_refactor() -> None:
    """Regression: Canakkale master parquet byte hash must match pre-P9 baseline."""
    baseline = config.DATA_PROCESSED / f"{MASTER_OUTPUT_NAME}.parquet"
    if not baseline.exists():
        pytest.skip("master_daily.parquet not present locally")
    hash_before = hashlib.sha256(baseline.read_bytes()).hexdigest()
    build_master_table(site_key=DEFAULT_SITE)
    hash_after = hashlib.sha256(baseline.read_bytes()).hexdigest()
    assert hash_after == CANAKKALE_MASTER_HASH
    assert hash_before == hash_after


def test_site_comparison_difference_test_on_synthetic_data() -> None:
    dates = pd.date_range("2023-06-01", periods=120, freq="D")
    can_rows = []
    bal_rows = []
    rng = np.random.default_rng(42)
    for date in dates:
        can_rows.append(
            {
                "date": date,
                "site_key": "canakkale",
                "pm10": 40 + rng.normal(0, 5),
                "pm2_5": 20 + rng.normal(0, 3),
                "dust": 30 + rng.normal(0, 4),
                "aerosol_optical_depth": 0.25 + rng.normal(0, 0.03),
            }
        )
        bal_rows.append(
            {
                "date": date,
                "site_key": "balikesir",
                "pm10": 25 + rng.normal(0, 4),
                "pm2_5": 12 + rng.normal(0, 2),
                "dust": 18 + rng.normal(0, 3),
                "aerosol_optical_depth": 0.15 + rng.normal(0, 0.02),
            }
        )
    daily_long = pd.DataFrame(can_rows + bal_rows)
    tests = run_pollution_difference_tests(daily_long)
    core = tests.loc[tests["variable"].isin(("pm10", "dust", "aerosol_optical_depth"))]
    assert core["balikesir_lower_significant"].all()
    assert (core["median_balikesir"] < core["median_canakkale"]).all()


def test_ground_cams_comparison_on_synthetic_data() -> None:
    dates = pd.date_range("2023-06-01", periods=90, freq="D")
    ground = pd.DataFrame(
        {
            "date": dates,
            "pm10": np.linspace(40, 60, len(dates))
            + np.random.default_rng(1).normal(0, 3, len(dates)),
            "station_code": ["TR170141"] * len(dates),
            "station_name": ["Canakkale"] * len(dates),
        }
    )
    cams = pd.DataFrame(
        {
            "date": dates,
            "pm10": np.linspace(10, 14, len(dates))
            + np.random.default_rng(2).normal(0, 1, len(dates)),
        }
    )
    stats = compare_ground_to_cams(ground, cams, "canakkale", pollutant="pm10")
    assert stats["n_pairs"] == len(dates)
    assert stats["median_bias_ground_minus_cams"] > 20
    assert stats["pearson_r"] > 0.5


def test_inverter_relative_performance_ranking() -> None:
    dates = pd.date_range("2025-02-01", periods=10, freq="D")
    rows = []
    for date in dates:
        for inv, scale in (("INV1", 1.0), ("INV2", 0.85), ("INV3", 1.02)):
            rows.append(
                {
                    "date": date,
                    "inverter": inv,
                    "active_power": 1000 * scale,
                    "meteo_irradiance": 800.0,
                }
            )
    frame = pd.DataFrame(rows)
    relative = compute_relative_performance(frame)
    summary = rank_inverters(relative)
    assert summary.iloc[0]["inverter"] == "INV3"
    assert summary.iloc[-1]["inverter"] == "INV2"
    inv2 = summary.loc[summary["inverter"] == "INV2"].iloc[0]
    assert inv2["median_relative"] < UNDERPERFORMER_MEDIAN_THRESHOLD
    assert inv2["candidate_underperformer"]
