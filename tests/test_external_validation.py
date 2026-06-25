"""Tests for P14 external validation and DKASC loader."""

from __future__ import annotations

import pandas as pd
import pytest

from spis.data_sources.dkasc import discover_dkasc_csv, introspect_dkasc_csv, map_dkasc_columns
from spis.external_validation import (
    ALICE_SPRINGS_SITE_KEY,
    comparison_table,
    detect_inferred_cleaning_events,
    honest_verdict,
)
from spis.sites import SITES, get_site


def test_sites_registry_includes_alice_springs() -> None:
    assert "alice_springs" in SITES
    site = get_site(ALICE_SPRINGS_SITE_KEY)
    assert site.operational_data_available
    assert site.lat == pytest.approx(-23.762)
    assert site.lon == pytest.approx(133.874)
    assert "Canadian Solar" in site.panel_class


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
    assert meta["source_id"] == 214


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


def test_honest_verdict_reports_direction() -> None:
    table = comparison_table(
        {
            "site_key": "canakkale",
            "pooled": {"pooled_rate": -0.1, "pooled_ci_lower": -0.12, "pooled_ci_upper": -0.08},
            "clear_pooled": {
                "pooled_rate": -0.125,
                "pooled_ci_lower": -0.14,
                "pooled_ci_upper": -0.11,
            },
            "pollution_summary": {
                "pm10_coef": 0.0,
                "pm10_p": 0.7,
                "dust_coef": 0.0,
                "dust_p": 0.8,
                "pollution_significant": False,
                "pollution_verdict": "null",
            },
        },
        {
            "site_key": ALICE_SPRINGS_SITE_KEY,
            "pooled": {"pooled_rate": -0.2, "pooled_ci_lower": -0.25, "pooled_ci_upper": -0.15},
            "clear_pooled": {
                "pooled_rate": -0.22,
                "pooled_ci_lower": -0.28,
                "pooled_ci_upper": -0.16,
            },
            "pollution_summary": {
                "pm10_coef": -0.01,
                "pm10_p": 0.01,
                "dust_coef": -0.02,
                "dust_p": 0.02,
                "pollution_significant": True,
                "pollution_verdict": "sig",
            },
        },
    )
    verdict = honest_verdict(table, {"inferred_cleaning_events": 5})
    assert "Canakkale" in verdict
    assert "Alice Springs" in verdict
    assert "inferred cleaning" in verdict.lower() or "inferred" in verdict.lower()
