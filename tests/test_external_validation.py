"""Tests for P14/P16 external validation and DKASC loader."""

from __future__ import annotations

import pandas as pd
import pytest

from spis.data_sources.dkasc import (
    DEFAULT_ARRAY,
    VALIDATION_ARRAYS,
    discover_dkasc_csv,
    introspect_dkasc_csv,
    map_dkasc_columns,
)
from spis.external_validation import (
    ALICE_SPRINGS_SITE_KEY,
    CANONICAL_CI_METHOD,
    cleaning_sensitivity_table,
    comparison_table,
    detect_inferred_cleaning_events,
    honest_verdict,
    load_canakkale_baseline,
)
from spis.robustness import canonical_clear_sky_pooled
from spis.sites import SITES, get_site


def test_sites_registry_includes_alice_springs() -> None:
    assert "alice_springs" in SITES
    site = get_site(ALICE_SPRINGS_SITE_KEY)
    assert site.operational_data_available
    assert site.lat == pytest.approx(-23.762)
    assert site.lon == pytest.approx(133.874)


def test_validation_arrays_are_fixed_tilt() -> None:
    assert len(VALIDATION_ARRAYS) >= 4
    assert all(item.tilt_type == "fixed" for item in VALIDATION_ARRAYS)
    assert {item.array_number for item in VALIDATION_ARRAYS} >= {"13", "14", "18", "32"}


def test_map_dkasc_columns_on_sample_header() -> None:
    headers = [
        "timestamp",
        "Active_Power",
        "Global_Horizontal_Radiation",
        "Weather_Temperature_Celsius",
        "Weather_Daily_Rainfall",
    ]
    mapping = map_dkasc_columns(headers)
    assert mapping["timestamp"] == "timestamp"
    assert mapping["active_power_kw"] == "Active_Power"
    assert mapping["ghi_wm2"] == "Global_Horizontal_Radiation"


@pytest.mark.integration
def test_dkasc_csv_present_and_introspectable() -> None:
    csv_path = discover_dkasc_csv()
    assert csv_path.exists()
    meta = introspect_dkasc_csv(csv_path)
    assert "timestamp" in meta["column_mapping"]
    assert meta["source_id"] == DEFAULT_ARRAY.source_id


def test_detect_inferred_cleaning_events_on_synthetic_series() -> None:
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    pi = pd.Series(1.0 - 0.001 * pd.Series(range(40)), index=dates)
    pi.iloc[20] = pi.iloc[19] * 1.06
    frame = pd.DataFrame(
        {
            "date": dates,
            "pi_temp_corrected": pi.to_numpy(),
            "weather_rainfall_mm": [0.0] * 39 + [12.0],
        }
    )
    events = detect_inferred_cleaning_events(frame)
    assert len(events) >= 1
    assert events.iloc[0]["method"] in {
        "inferred_rain",
        "inferred_pi_step",
        "inferred_rain+inferred_pi_step",
    }


def test_canonical_clear_sky_pooled_matches_p4_style() -> None:
    segment_compare = pd.DataFrame(
        {
            "clear_rate_pct_per_day": [-0.10, -0.15],
            "clear_n_fit": [100.0, 80.0],
            "clear_ci_lower": [-0.14, -0.20],
            "clear_ci_upper": [-0.06, -0.10],
        }
    )
    pooled = canonical_clear_sky_pooled(segment_compare)
    assert pooled["ci_method"] == CANONICAL_CI_METHOD
    expected_rate = float(pd.Series([-0.10, -0.15]).dot(pd.Series([100.0, 80.0])) / 180.0)
    assert pooled["pooled_rate"] == pytest.approx(expected_rate)
    ci_width = ((0.14 - 0.06) + (0.20 - 0.10)) / 2.0
    assert pooled["ci_half_width"] == pytest.approx(ci_width / 2.0)


def test_honest_verdict_is_inconclusive_not_overclaiming() -> None:
    table = comparison_table(
        {
            "site_key": "canakkale",
            "site_label": "Canakkale Hybrid GES",
            "clear_pooled": {
                "pooled_rate": -0.125,
                "pooled_ci_lower": -0.186,
                "pooled_ci_upper": -0.064,
                "ci_method": CANONICAL_CI_METHOD,
            },
            "pollution_summary": {
                "pm10_coef": 0.0,
                "pm10_p": 0.73,
                "dust_coef": 0.0,
                "dust_p": 0.66,
                "pollution_significant": False,
                "pollution_verdict": "null",
            },
        },
        [
            {
                "site_key": ALICE_SPRINGS_SITE_KEY,
                "array_number": "13",
                "array_label": "Trina",
                "source_id": 92,
                "clear_pooled": {
                    "pooled_rate": 0.04,
                    "pooled_ci_lower": -0.56,
                    "pooled_ci_upper": 0.64,
                    "ci_method": CANONICAL_CI_METHOD,
                },
                "pollution_summary": {
                    "pm10_coef": -1e-8,
                    "pm10_p": 0.08,
                    "dust_coef": -1e-8,
                    "dust_p": 0.10,
                    "pollution_significant": False,
                    "pollution_verdict": "null",
                },
                "inferred_cleaning_events": 40,
            }
        ],
    )
    sensitivity = cleaning_sensitivity_table(
        {
            "default": [
                {
                    "array_number": "13",
                    "array_label": "Trina",
                    "clear_pooled": {
                        "pooled_rate": 0.04,
                        "pooled_ci_lower": -0.56,
                        "pooled_ci_upper": 0.64,
                    },
                    "inferred_cleaning_events": 40,
                }
            ],
            "strict": [
                {
                    "array_number": "13",
                    "array_label": "Trina",
                    "clear_pooled": {
                        "pooled_rate": 0.02,
                        "pooled_ci_lower": -0.50,
                        "pooled_ci_upper": 0.55,
                    },
                    "inferred_cleaning_events": 30,
                }
            ],
            "sensitive": [
                {
                    "array_number": "13",
                    "array_label": "Trina",
                    "clear_pooled": {
                        "pooled_rate": 0.05,
                        "pooled_ci_lower": -0.60,
                        "pooled_ci_upper": 0.70,
                    },
                    "inferred_cleaning_events": 55,
                }
            ],
        }
    )
    verdict = honest_verdict(table, sensitivity, [])
    assert "INCONCLUSIVE" in verdict
    assert "dramatically dustier" not in verdict.lower()
    assert "p≈0.08" in verdict or "0.08" in verdict


@pytest.mark.integration
def test_canakkale_baseline_uses_canonical_ci() -> None:
    can = load_canakkale_baseline()
    clear = can["clear_pooled"]
    assert clear["pooled_rate"] == pytest.approx(-0.1247, abs=1e-3)
    assert clear["pooled_ci_lower"] == pytest.approx(-0.186, abs=0.002)
    assert clear["pooled_ci_upper"] == pytest.approx(-0.064, abs=0.002)
    assert clear["ci_method"] == CANONICAL_CI_METHOD
