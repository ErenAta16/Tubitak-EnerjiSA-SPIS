"""Tests for P17 PVDAQ loader and method benchmark helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from spis.data_sources.pvdaq import (
    CHANNEL_MAP,
    SYSTEM_ID,
    ensure_pvdaq_metadata,
    introspect_pvdaq_channels,
    load_pvdaq_metadata,
    metadata_site_facts,
    resolve_analysis_window,
    select_energy_channel,
)
from spis.method_benchmark import benchmark_table, srr_slope_from_ratio
from spis.sites import SITES, get_site


def test_sites_registry_includes_pvdaq_2107() -> None:
    assert "pvdaq_2107" in SITES
    site = get_site("pvdaq_2107")
    assert site.lat == pytest.approx(38.996306)
    assert site.lon == pytest.approx(-122.134111)
    assert site.operational_data_available


def test_pvdaq_metadata_site_facts() -> None:
    meta = load_pvdaq_metadata()
    facts = metadata_site_facts(meta)
    assert facts["system_id"] == SYSTEM_ID
    assert facts["public_name"] == "Farm Solar Array"
    assert facts["dc_capacity_kw"] == pytest.approx(893.0)
    assert facts["climate_type"] == "Csa"
    assert facts["module_model"] == "HiS-M310TI"


def test_pvdaq_channel_map_has_required_fields() -> None:
    assert "ac_power_kw" in CHANNEL_MAP
    assert "poa_wm2" in CHANNEL_MAP
    assert "ambient_temp_f" in CHANNEL_MAP
    assert CHANNEL_MAP["timestamp"] == "measured_on"


def test_select_energy_channel_is_integrated_power() -> None:
    daily = pd.DataFrame({"production": [100.0], "production_counter": [None]})
    channel, meta = select_energy_channel(daily)
    assert channel == "integrated_ac_power"
    assert "interval-mean kW" in meta["selection_reason"]


def test_resolve_analysis_window_filters_sparse_days() -> None:
    daily = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=5, freq="D"),
            "production": [10.0, 0.0, 12.0, 11.0, 9.0],
            "irradiation": [1000.0, 1000.0, 1100.0, 900.0, 950.0],
            "n_intervals": [96, 96, 96, 10, 96],
        }
    )
    start, end, info = resolve_analysis_window(daily)
    assert start == "2020-01-01"
    assert end == "2020-01-05"
    assert info["days_total"] == 3


def test_srr_slope_from_ratio() -> None:
    assert srr_slope_from_ratio(0.97, interval_days=30.0) == pytest.approx(0.1, rel=1e-3)


def test_benchmark_table_shape() -> None:
    table = benchmark_table(
        [
            {
                "site_name": "Canakkale",
                "site_key": "canakkale",
                "spis_rate_pct_per_day": -0.125,
                "spis_ci_lower": -0.186,
                "spis_ci_upper": -0.064,
                "ci_method": "clear_sky_pooled_weighted_by_n_fit",
                "srr_soiling_ratio": 0.99,
                "srr_ci_lower": 0.98,
                "srr_ci_upper": 1.0,
                "srr_median_interval_slope_pct_per_day": -0.11,
                "srr_interval_count": 5,
                "agreement_verdict": "sign agreement only",
            }
        ]
    )
    assert len(table) == 1
    assert "spis_clear_sky_rate_pct_per_day" in table.columns


@pytest.mark.integration
def test_pvdaq_metadata_on_disk() -> None:
    path = ensure_pvdaq_metadata()
    assert path.exists()
    info = introspect_pvdaq_channels()
    assert info["site_facts"]["system_id"] == SYSTEM_ID
    sidecar = Path("data/external/pvdaq/2107/2107_system_metadata.json")
    assert sidecar.exists()
    json.loads(sidecar.read_text(encoding="utf-8"))


@pytest.mark.integration
def test_rdtools_import_guard() -> None:
    pytest.importorskip("rdtools")
    from rdtools import soiling

    assert hasattr(soiling, "soiling_srr")
