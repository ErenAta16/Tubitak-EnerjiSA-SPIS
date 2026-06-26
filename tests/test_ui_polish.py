"""P21 UI redesign tests: layout, i18n, formatting, and public-app safety."""

from __future__ import annotations

import json
from pathlib import Path

from app.charts import rate_ci_figure, segment_slopes_figure
from app.display_i18n import (
    format_headline_rate,
    site_label,
    translate_backend_message,
    validation_status_line,
)
from app.sample_data import load_sample_upload_snapshot
from app.streamlit_app import TEXT, UI_BUILD, _t
from app.tables import format_data_preview, format_segments_table
from app.ui_logic import load_demo_dashboard_snapshot

ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_APP = ROOT / "app" / "streamlit_app.py"


def test_ui_build_tag_is_p21() -> None:
    assert UI_BUILD == "2026-06-25-p21-ui-redesign"


def test_t_returns_single_language() -> None:
    assert _t("hero_soiling_label", "TR") == "Kirlenme hızı — açık gökyüzü"
    assert _t("hero_soiling_label", "EN") == "Soiling rate — clear sky"
    assert _t("data_tab", "TR") == "Veri"
    assert _t("source_example", "TR") == "Örnek"


def test_headline_number_formatting_two_decimals() -> None:
    assert format_headline_rate(-0.1469, na="n/a", lang="EN") == "-0.15 %/day"
    assert format_headline_rate(-0.1469, na="yok", lang="TR") == "−0,15 %/gün"


def test_validation_status_line_localized_turkish() -> None:
    snap = load_sample_upload_snapshot()
    assert snap.available
    validated = validation_status_line(snap, "TR")
    assert "120" in validated or "gömülü" in validated.lower() or "Gömülü" in validated
    upload_msg = translate_backend_message("Validated 120 daily rows.", "TR")
    assert upload_msg == "120 günlük satır doğrulandı."


def test_translate_validated_rows_message() -> None:
    tr = translate_backend_message("Validated 120 daily rows.", "TR")
    assert tr == "120 günlük satır doğrulandı."


def test_streamlit_app_has_no_figure_downloads() -> None:
    source = STREAMLIT_APP.read_text(encoding="utf-8")
    assert "list_downloadable_figures" not in source
    assert "reports/figures" not in source


def test_no_dual_language_slash_in_text_catalog() -> None:
    skip = {"language_en", "language_tr"}
    for key, (en, tr) in TEXT.items():
        if key in skip:
            continue
        assert " / " not in en, f"Dual-language label in TEXT[{key!r}] EN"
        assert " / " not in tr, f"Dual-language label in TEXT[{key!r}] TR"


def test_tr_catalog_has_no_english_unit_leaks() -> None:
    skip = {"language_en", "language_tr", "demo_pill", "energy_unit", "footer_data_use"}
    for key, (_en, tr) in TEXT.items():
        if key in skip:
            continue
        assert "%/day" not in tr, f"TR leak %/day in TEXT[{key!r}]"
        assert "95% CI" not in tr, f"TR leak 95% CI in TEXT[{key!r}]"


def test_tr_chart_strings_no_english_leaks() -> None:
    snap = load_demo_dashboard_snapshot()
    assert snap.clear_sky_rate_pct_per_day is not None
    assert snap.clear_sky_ci_lower is not None
    assert snap.clear_sky_ci_upper is not None
    ci_fig = rate_ci_figure(
        snap.clear_sky_rate_pct_per_day,
        snap.clear_sky_ci_lower,
        snap.clear_sky_ci_upper,
        "TR",
    )
    ci_payload = json.loads(ci_fig.to_json())
    ci_blob = json.dumps(ci_payload, ensure_ascii=False)
    assert "%/day" not in ci_blob
    assert "%95 GA" in ci_blob

    assert snap.segments is not None
    seg_fig = segment_slopes_figure(snap.segments, "TR")
    seg_blob = json.dumps(json.loads(seg_fig.to_json()), ensure_ascii=False)
    assert "%/day" not in seg_blob
    assert "%/gün" in seg_blob


def test_segments_table_uses_integer_clean_days() -> None:
    snap = load_demo_dashboard_snapshot()
    table = format_segments_table(snap.segments, "TR")
    assert table is not None
    clean_col = "Temiz gün"
    assert clean_col in table.columns
    for value in table[clean_col]:
        assert "." not in str(value)


def test_data_preview_single_pi_column_when_identical() -> None:
    snap = load_demo_dashboard_snapshot()
    preview = format_data_preview(snap.master, lang="TR")
    assert preview is not None
    pi_cols = [col for col in preview.columns if col.startswith("PI")]
    assert len(pi_cols) == 1


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
        "render_hero_and_chips",
        "render_validation_line",
    ):
        assert hasattr(streamlit_app, name)


def test_site_label_demo_turkish() -> None:
    from spis.demo_plant import DEMO_PLANT_KEY

    assert site_label(DEMO_PLANT_KEY, "fallback")("TR") == "Demo Santral (sentetik)"
