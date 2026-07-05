"""Public real-site bundle, dashboard, and confidentiality smoke tests."""

from __future__ import annotations

import pandas as pd
import pytest

from app.charts import (
    cost_curve_figure,
    pi_timeline_figure,
    production_irradiation_figure,
    rate_ci_figure,
    segment_slopes_figure,
)
from app.display_i18n import site_label, validation_status_line
from app.tables import format_data_preview, format_segments_table
from app.ui_logic import (
    build_results_summary_markdown,
    compute_live_optimization,
    list_example_site_options,
    load_dashboard_snapshot,
    plain_language_soiling_line,
)
from spis import config
from spis.public_examples import (
    DKASC_KEY,
    PUBLIC_EXAMPLE_KEYS,
    PVDAQ_2107_KEY,
    public_artifact_path,
    public_example_available,
)
from spis.soiling import MASTER_INPUT_NAME, SOILING_OUTPUT_NAME

EXPECTED_MASTER_COLUMNS = {
    "date",
    "production",
    "irradiation",
    "pi",
    "pi_temp_corrected",
    "is_clean_observation",
    "segment_id",
    "days_since_wash",
}
FORBIDDEN_TOKENS = ("enerjisa", "canakkale", "çanakkale", "latitude", "longitude")


@pytest.mark.parametrize("site_key", PUBLIC_EXAMPLE_KEYS)
def test_public_snapshot_is_bundled_and_contains_only_dashboard_fields(site_key: str) -> None:
    assert public_example_available(site_key)
    master = pd.read_parquet(public_artifact_path(site_key, MASTER_INPUT_NAME))
    assert set(master.columns) == EXPECTED_MASTER_COLUMNS
    assert not any(token in " ".join(master.columns).lower() for token in FORBIDDEN_TOKENS)
    text = " ".join(
        master.select_dtypes(include=["object", "string"]).fillna("").astype(str).to_numpy().ravel()
    ).lower()
    assert not any(token in text for token in FORBIDDEN_TOKENS)
    segments = pd.read_parquet(public_artifact_path(site_key, SOILING_OUTPUT_NAME))
    assert not segments.empty


def test_public_headlines_match_external_validation_report() -> None:
    pvdaq = load_dashboard_snapshot(PVDAQ_2107_KEY)
    dkasc = load_dashboard_snapshot(DKASC_KEY)
    assert pvdaq.clear_sky_rate_pct_per_day == pytest.approx(0.0908383158)
    assert pvdaq.clear_sky_ci_lower == pytest.approx(-0.5124641975)
    assert pvdaq.clear_sky_ci_upper == pytest.approx(0.6941408292)
    assert dkasc.clear_sky_rate_pct_per_day == pytest.approx(-0.1437411647)
    assert dkasc.clear_sky_ci_lower == pytest.approx(-4.1451643654)
    assert dkasc.clear_sky_ci_upper == pytest.approx(3.8576820359)


def test_public_sites_are_unconditional_but_canakkale_remains_gated(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path / "missing")
    keys = [option.site_key for option in list_example_site_options()]
    assert PVDAQ_2107_KEY in keys
    assert DKASC_KEY in keys
    assert "canakkale" not in keys


@pytest.mark.parametrize("site_key", PUBLIC_EXAMPLE_KEYS)
def test_public_snapshots_drive_every_dashboard_tab_headlessly(site_key: str) -> None:
    snapshot = load_dashboard_snapshot(site_key)
    assert snapshot.available
    assert snapshot.master is not None
    assert snapshot.segments is not None
    assert snapshot.rate_band is not None
    assert snapshot.daily_energy_kwh is not None
    assert snapshot.clear_sky_rate_pct_per_day is not None
    assert snapshot.clear_sky_ci_lower is not None
    assert snapshot.clear_sky_ci_upper is not None

    rate_ci_figure(
        snapshot.clear_sky_rate_pct_per_day,
        snapshot.clear_sky_ci_lower,
        snapshot.clear_sky_ci_upper,
        "EN",
    )
    pi_timeline_figure(snapshot.master, "EN")
    production_irradiation_figure(snapshot.master, "EN")
    segment_slopes_figure(snapshot.segments, "EN")
    assert format_segments_table(snapshot.segments, "EN") is not None

    optimization = compute_live_optimization(
        150_000,
        1500,
        snapshot.rate_band,
        snapshot.daily_energy_kwh,
    )
    cost_curve_figure(optimization, "EN")
    assert format_data_preview(snapshot.master, lang="EN") is not None
    assert "Economic optimizer" in build_results_summary_markdown(snapshot, optimization)


def test_public_site_labels_and_banners_are_source_specific() -> None:
    pvdaq = load_dashboard_snapshot(PVDAQ_2107_KEY)
    dkasc = load_dashboard_snapshot(DKASC_KEY)
    assert site_label(PVDAQ_2107_KEY, "")("TR") == "PVDAQ 2107 (halka açık saha)"
    assert site_label(DKASC_KEY, "")("TR") == "DKASC (halka açık saha)"
    assert "Enerjisa verisi değildir" in validation_status_line(pvdaq, "TR")
    assert "NREL PVDAQ 2107" in validation_status_line(pvdaq, "EN")
    assert "Enerjisa verisi değildir" in validation_status_line(dkasc, "TR")
    assert "DKASC Alice Springs array 14" in validation_status_line(dkasc, "EN")
    assert "crosses zero" in plain_language_soiling_line(0.09, "EN", -0.51, 0.69)
    assert "sıfırı kesiyor" in plain_language_soiling_line(-0.14, "TR", -4.15, 3.86)
