"""P20 UI polish tests: i18n, formatting, and public-app safety."""

from __future__ import annotations

from pathlib import Path

from app.display_i18n import (
    format_headline_ci,
    format_headline_rate,
    site_label,
    snapshot_status_line,
    translate_backend_message,
)
from app.streamlit_app import TEXT, UI_BUILD, _t
from app.ui_logic import load_demo_dashboard_snapshot

ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_APP = ROOT / "app" / "streamlit_app.py"


def test_ui_build_tag_is_p20() -> None:
    assert UI_BUILD == "2026-06-26-p20-ui-polish"


def test_t_returns_single_language() -> None:
    assert _t("soiling", "TR") == "Kirlenme hızı (açık gökyüzü)"
    assert _t("soiling", "EN") == "Soiling rate (clear-sky)"
    assert " / " not in _t("ci_label", "TR")
    assert "GA" not in _t("ci_label", "EN")


def test_headline_number_formatting_two_decimals() -> None:
    assert format_headline_rate(-0.1469, na="n/a") == "-0.15 %/day"
    assert format_headline_ci(-0.18, -0.12, na="n/a") == "-0.18 .. -0.12"


def test_snapshot_status_line_localized_turkish() -> None:
    snap = load_demo_dashboard_snapshot()
    line = snapshot_status_line(snap, "TR")
    assert "Demo Santral" in line
    assert "Sentetik demo" in line


def test_translate_validated_rows_message() -> None:
    tr = translate_backend_message("Validated 120 daily rows.", "TR")
    assert "120" in tr
    assert "günlük" in tr


def test_streamlit_app_has_no_figure_downloads() -> None:
    source = STREAMLIT_APP.read_text(encoding="utf-8")
    assert "list_downloadable_figures" not in source
    assert "reports/figures" not in source


def test_no_dual_language_slash_in_text_catalog() -> None:
    skip = {"language_en", "language_tr", "csv_format_example"}
    for key, (en, tr) in TEXT.items():
        if key in skip:
            continue
        assert " / " not in en, f"Dual-language label in TEXT[{key!r}] EN"
        assert " / " not in tr, f"Dual-language label in TEXT[{key!r}] TR"


def test_demo_plant_headless_tab_functions_exist() -> None:
    from app import streamlit_app

    snap = load_demo_dashboard_snapshot()
    assert snap.available
    for name in (
        "render_overview_tab",
        "render_charts_tab",
        "render_segments_tab",
        "render_economy_tab",
        "render_data_tab",
        "render_headline_metrics",
    ):
        assert hasattr(streamlit_app, name)


def test_site_label_demo_turkish() -> None:
    from spis.demo_plant import DEMO_PLANT_KEY

    assert site_label(DEMO_PLANT_KEY, "fallback")("TR") == "Demo Santral (sentetik)"
