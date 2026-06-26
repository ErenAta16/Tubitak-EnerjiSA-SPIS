"""Smoke tests for dashboard chart builders."""

from __future__ import annotations

from app.charts import (
    pi_timeline_figure,
    production_irradiation_figure,
    rate_ci_figure,
    segment_slopes_figure,
)
from app.tables import format_data_preview, format_segments_table
from app.ui_logic import load_demo_dashboard_snapshot


def test_chart_builders_run_on_demo_snapshot() -> None:
    snap = load_demo_dashboard_snapshot()
    assert snap.available
    assert snap.master is not None
    assert snap.segments is not None
    pi_timeline_figure(snap.master, "EN")
    production_irradiation_figure(snap.master, "TR")
    segment_slopes_figure(snap.segments, "EN")
    assert snap.clear_sky_rate_pct_per_day is not None
    assert snap.clear_sky_ci_lower is not None
    assert snap.clear_sky_ci_upper is not None
    rate_ci_figure(
        snap.clear_sky_rate_pct_per_day,
        snap.clear_sky_ci_lower,
        snap.clear_sky_ci_upper,
        "EN",
    )


def test_format_segments_table_localizes_columns() -> None:
    snap = load_demo_dashboard_snapshot()
    table_en = format_segments_table(snap.segments, "EN")
    table_tr = format_segments_table(snap.segments, "TR")
    assert table_en is not None
    assert table_tr is not None
    assert "Segment" in table_en.columns
    assert "Segment" in table_tr.columns
    assert "Başlangıç" in table_tr.columns


def test_format_data_preview_returns_recent_rows() -> None:
    snap = load_demo_dashboard_snapshot()
    preview = format_data_preview(snap.master, lang="EN")
    assert preview is not None
    assert len(preview) == 14
