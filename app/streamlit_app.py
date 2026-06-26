"""SPIS web interface for non-developer users."""

from __future__ import annotations

import sys

SOURCE_EXAMPLE = "example"
SOURCE_UPLOAD = "upload"
SOURCE_OPTIONS = (SOURCE_EXAMPLE, SOURCE_UPLOAD)
LANG_OPTIONS = ("TR", "EN")
DATA_USE_URL = (
    "https://github.com/ErenAta16/Tubitak-EnerjiSA-SPIS/blob/main/DATA_USE.md"
)


def _refresh_app_modules() -> None:
    """Drop cached app.* modules so each Streamlit rerun loads fresh code from disk."""
    skip = frozenset({"app.streamlit_app"})
    for name in list(sys.modules):
        if name.startswith("app.") and name not in skip:
            del sys.modules[name]


_refresh_app_modules()

import streamlit as st

from app.charts import (
    cost_curve_figure,
    pi_timeline_figure,
    production_irradiation_figure,
    rate_ci_figure,
    segment_slopes_figure,
)
from app.display_i18n import (
    format_headline_rate,
    format_t_star_days,
    site_label,
    translate_backend_message,
    translate_pollution_verdict,
    validation_status_line,
)
from app.models import DashboardSnapshot
from app.sample_data import load_sample_upload_snapshot
from app.tables import format_comparison_table, format_data_preview, format_segments_table
from app.ui_logic import (
    ExampleSiteOption,
    build_results_summary_markdown,
    compute_live_optimization,
    default_example_site_key,
    get_sample_upload_csv_bytes,
    list_example_site_options,
    load_dashboard_snapshot,
    load_upload_dashboard_snapshot,
    plain_language_soiling_line,
)
from spis import config

UI_BUILD = "2026-06-25-p21-ui-redesign"

st.set_page_config(page_title="SPIS", layout="wide", initial_sidebar_state="expanded")

TEXT = {
    "language_label": ("Language", "Dil"),
    "language_tr": ("Turkish", "Türkçe"),
    "language_en": ("English", "English"),
    "tagline": (
        "Estimate soiling loss between washes and a cost-optimal wash interval.",
        "Yıkamalar arası kirlenme kaybını ve maliyet-optimal yıkama aralığını tahmin edin.",
    ),
    "demo_pill": ("demo", "demo"),
    "input_source": ("Input source", "Veri kaynağı"),
    "source_example": ("Example", "Örnek"),
    "source_upload": ("Upload CSV", "CSV yükle"),
    "site_label": ("Site", "Santral"),
    "download_sample_csv": ("Download sample CSV", "Örnek CSV indir"),
    "sidebar_columns": (
        "Columns: date, production, irradiation",
        "Sütunlar: date, production, irradiation",
    ),
    "upload_file_label": ("Daily CSV file", "Günlük CSV dosyası"),
    "overview": ("Overview", "Özet"),
    "charts": ("Charts", "Grafikler"),
    "segments": ("Segments", "Segmentler"),
    "economy": ("Economics", "Ekonomi"),
    "data_tab": ("Data", "Veri"),
    "hero_soiling_label": (
        "Soiling rate — clear sky",
        "Kirlenme hızı — açık gökyüzü",
    ),
    "energy_label": ("Daily energy", "Günlük enerji"),
    "energy_unit": ("kWh", "kWh"),
    "segments_count": ("Wash segments", "Yıkama segmenti"),
    "date_range_label": ("Data range", "Veri aralığı"),
    "days_unit": ("days", "gün"),
    "na": ("n/a", "yok"),
    "optimizer": ("Economic optimizer", "Ekonomik optimizasyon"),
    "wash_cost": ("Wash cost (TL)", "Yıkama maliyeti (TL)"),
    "electricity_price": ("Electricity price (TL/MWh)", "Elektrik fiyatı (TL/MWh)"),
    "t_star": ("Optimal wash interval T*", "Optimal yıkama aralığı T*"),
    "t_star_help": (
        "Minimum total daily cost (lost energy + amortized wash cost).",
        "Minimum günlük toplam maliyet (enerji kaybı + yıkama maliyeti).",
    ),
    "pollution": ("Pollution test", "Kirlilik testi"),
    "comparison": ("Site comparison", "Santral karşılaştırması"),
    "waiting_upload": (
        "Choose an example site in the sidebar or upload a daily CSV.",
        "Sidebar'dan örnek santral seçin veya günlük CSV yükleyin.",
    ),
    "no_timeseries": ("No time series available.", "Zaman serisi yok."),
    "no_segments_table": (
        "Segment table not available for this input.",
        "Bu girdi için segment tablosu yok.",
    ),
    "optimizer_unavailable": (
        "Economic optimizer needs a valid soiling rate and daily energy estimate.",
        "Ekonomik optimizasyon için geçerli kirlenme hızı ve günlük enerji gerekir.",
    ),
    "no_daily_rows": ("No daily rows to display.", "Gösterilecek günlük satır yok."),
    "data_preview_caption": ("Most recent daily rows", "Son günlük satırlar"),
    "download_summary": ("Download summary", "Özeti indir"),
    "csv_read_error": (
        "Could not read the CSV file. Save as UTF-8 comma-separated text.",
        "CSV okunamadı. UTF-8 ve virgülle ayrılmış metin olarak kaydedin.",
    ),
    "ci_below_zero_caption": (
        "Estimate is below zero — measurable soiling.",
        "Tahmin sıfırın altında — ölçülebilir kirlenme.",
    ),
    "footer_text": (
        "TUBITAK 2209-B research demo · Code MIT · Plant data proprietary ·",
        "TÜBİTAK 2209-B araştırma demosu · Kod MIT · Santral verisi özel ·",
    ),
    "footer_data_use": ("DATA_USE.md", "DATA_USE.md"),
}


def _t(key: str, lang: str) -> str:
    en, tr = TEXT[key]
    return tr if lang == "TR" else en


def _language_name(code: str) -> str:
    return _t("language_tr", code) if code == "TR" else _t("language_en", code)


def _format_site_option(option: ExampleSiteOption, lang: str) -> str:
    return site_label(option.site_key, option.label)(lang)


def _format_integer(value: float | int | None, *, lang: str, na: str) -> str:
    if value is None:
        return na
    formatted = f"{int(round(value)):,}"
    if lang == "TR":
        formatted = formatted.replace(",", ".")
    return formatted


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.25rem;
            padding-bottom: 1.5rem;
            max-width: 1100px;
        }
        section[data-testid="stSidebar"] .block-container {
            padding-top: 1rem;
        }
        .spis-header {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.55rem;
            margin-bottom: 1.25rem;
        }
        .spis-wordmark {
            font-size: 18px;
            font-weight: 700;
            letter-spacing: 0.04em;
            color: #1f2328;
        }
        .spis-pill {
            display: inline-block;
            font-size: 11px;
            font-weight: 600;
            text-transform: lowercase;
            color: #57606a;
            background: #f6f8fa;
            border: 1px solid #d0d7de;
            border-radius: 999px;
            padding: 0.1rem 0.55rem;
        }
        .spis-tagline {
            flex: 1 1 100%;
            margin: 0;
            font-size: 0.92rem;
            color: #57606a;
            line-height: 1.45;
        }
        .spis-validation {
            display: flex;
            align-items: center;
            gap: 0.45rem;
            margin: 0 0 1rem 0;
            font-size: 0.86rem;
            color: #57606a;
        }
        .spis-validation-icon {
            color: #1a7f37;
            font-weight: 700;
        }
        .spis-hero-card {
            background: #f6f8fa;
            border: 1px solid #d0d7de;
            border-left: 4px solid #1f6feb;
            border-radius: 0.5rem;
            padding: 1.1rem 1.25rem 1rem;
            margin-bottom: 1rem;
        }
        .spis-hero-label {
            margin: 0 0 0.35rem 0;
            font-size: 0.82rem;
            font-weight: 600;
            color: #57606a;
            letter-spacing: 0.01em;
        }
        .spis-hero-value {
            margin: 0;
            font-size: 2rem;
            font-weight: 700;
            line-height: 1.15;
            color: #1f2328;
        }
        .spis-hero-detail {
            margin: 0.55rem 0 0 0;
            font-size: 0.92rem;
            color: #424a53;
            line-height: 1.45;
        }
        .spis-chips {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.75rem;
            margin-bottom: 1.25rem;
        }
        .spis-chip {
            background: #ffffff;
            border: 1px solid #d0d7de;
            border-radius: 0.45rem;
            padding: 0.7rem 0.85rem;
        }
        .spis-chip-label {
            margin: 0 0 0.2rem 0;
            font-size: 0.75rem;
            color: #57606a;
        }
        .spis-chip-value {
            margin: 0;
            font-size: 1.05rem;
            font-weight: 600;
            color: #1f2328;
        }
        .spis-footer {
            margin-top: 0.5rem;
            font-size: 0.75rem;
            color: #8c959f;
        }
        .spis-footer a {
            color: #57606a;
            text-decoration: none;
        }
        .spis-footer a:hover {
            text-decoration: underline;
        }
        @media (max-width: 768px) {
            .spis-chips {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_compact_header(lang: str) -> None:
    st.markdown(
        f"""
        <div class="spis-header">
            <span class="spis-wordmark">SPIS</span>
            <span class="spis-pill">{_t("demo_pill", lang)}</span>
            <p class="spis-tagline">{_t("tagline", lang)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_validation_line(snapshot: DashboardSnapshot, lang: str) -> None:
    message = validation_status_line(snapshot, lang)
    st.markdown(
        f"""
        <p class="spis-validation">
            <span class="spis-validation-icon" aria-hidden="true">✓</span>
            <span>{message}</span>
        </p>
        """,
        unsafe_allow_html=True,
    )


def render_hero_and_chips(snapshot: DashboardSnapshot, lang: str) -> None:
    rate = snapshot.clear_sky_rate_pct_per_day
    na = _t("na", lang)
    n_days = len(snapshot.master) if snapshot.master is not None else 0
    n_segments = snapshot.segment_count()
    rate_text = format_headline_rate(rate, na=na, lang=lang)
    detail = plain_language_soiling_line(rate, lang)
    energy_value = (
        f"{_format_integer(snapshot.daily_energy_kwh, lang=lang, na=na)} {_t('energy_unit', lang)}"
        if snapshot.daily_energy_kwh
        else na
    )
    segments_value = _format_integer(n_segments, lang=lang, na=na) if n_segments else na
    range_value = (
        f"{_format_integer(n_days, lang=lang, na=na)} {_t('days_unit', lang)}"
        if n_days
        else na
    )
    st.markdown(
        f"""
        <div class="spis-hero-card">
            <p class="spis-hero-label">{_t("hero_soiling_label", lang)}</p>
            <p class="spis-hero-value">{rate_text}</p>
            <p class="spis-hero-detail">{detail}</p>
        </div>
        <div class="spis-chips">
            <div class="spis-chip">
                <p class="spis-chip-label">{_t("energy_label", lang)}</p>
                <p class="spis-chip-value">{energy_value}</p>
            </div>
            <div class="spis-chip">
                <p class="spis-chip-label">{_t("segments_count", lang)}</p>
                <p class="spis-chip-value">{segments_value}</p>
            </div>
            <div class="spis-chip">
                <p class="spis-chip-label">{_t("date_range_label", lang)}</p>
                <p class="spis-chip-value">{range_value}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer(lang: str) -> None:
    st.markdown(
        f"""
        <p class="spis-footer">
            {_t("footer_text", lang)}
            <a href="{DATA_USE_URL}">{_t("footer_data_use", lang)}</a>
            · {UI_BUILD}
        </p>
        """,
        unsafe_allow_html=True,
    )


def load_input_snapshot(lang: str) -> DashboardSnapshot | None:
    source_key = st.sidebar.radio(
        _t("input_source", lang),
        SOURCE_OPTIONS,
        format_func=lambda key: _t(f"source_{key}", lang),
        horizontal=True,
    )
    if source_key == SOURCE_EXAMPLE:
        options = list_example_site_options()
        default_index = next(
            (idx for idx, opt in enumerate(options) if opt.site_key == default_example_site_key()),
            0,
        )
        selected = st.sidebar.selectbox(
            _t("site_label", lang),
            options,
            index=default_index,
            format_func=lambda item: _format_site_option(item, lang),
        )
        return load_dashboard_snapshot(selected.site_key)

    st.sidebar.download_button(
        _t("download_sample_csv", lang),
        data=get_sample_upload_csv_bytes(),
        file_name="spis_upload_template.csv",
        mime="text/csv",
    )
    st.sidebar.caption(_t("sidebar_columns", lang))
    uploaded = st.sidebar.file_uploader(
        _t("upload_file_label", lang),
        type=["csv"],
    )
    if uploaded is None:
        return load_sample_upload_snapshot()
    import pandas as pd

    try:
        frame = pd.read_csv(uploaded)
    except Exception:
        st.error(_t("csv_read_error", lang))
        return None
    snapshot = load_upload_dashboard_snapshot(frame)
    if not snapshot.available:
        st.error(translate_backend_message(snapshot.message, lang))
        return None
    return snapshot


def render_overview_tab(snapshot: DashboardSnapshot, lang: str) -> None:
    rate = snapshot.clear_sky_rate_pct_per_day
    st.markdown(f"**{_t('pollution', lang)}**")
    st.write(translate_pollution_verdict(snapshot.pollution_verdict, lang))
    if (
        rate is not None
        and snapshot.clear_sky_ci_lower is not None
        and snapshot.clear_sky_ci_upper is not None
    ):
        st.plotly_chart(
            rate_ci_figure(rate, snapshot.clear_sky_ci_lower, snapshot.clear_sky_ci_upper, lang),
            use_container_width=True,
        )
        if rate < 0:
            st.caption(_t("ci_below_zero_caption", lang))
    if snapshot.comparison_table is not None:
        st.markdown(f"**{_t('comparison', lang)}**")
        comparison = format_comparison_table(snapshot.comparison_table, lang)
        if comparison is not None:
            st.dataframe(comparison, use_container_width=True, hide_index=True)


def render_charts_tab(snapshot: DashboardSnapshot, lang: str) -> None:
    if snapshot.master is None:
        st.warning(_t("no_timeseries", lang))
        return
    left, right = st.columns(2)
    with left:
        st.plotly_chart(pi_timeline_figure(snapshot.master, lang), use_container_width=True)
    with right:
        st.plotly_chart(
            production_irradiation_figure(snapshot.master, lang),
            use_container_width=True,
        )
    segments = snapshot.segments_frame()
    if segments is not None and not segments.empty:
        st.plotly_chart(
            segment_slopes_figure(segments, lang),
            use_container_width=True,
        )


def render_segments_tab(snapshot: DashboardSnapshot, lang: str) -> None:
    table = format_segments_table(snapshot.segments_frame(), lang)
    if table is None:
        st.info(_t("no_segments_table", lang))
        return
    st.dataframe(table, use_container_width=True, hide_index=True)


def render_economy_tab(snapshot: DashboardSnapshot, lang: str) -> dict | None:
    if snapshot.rate_band is None or snapshot.daily_energy_kwh is None:
        st.info(_t("optimizer_unavailable", lang))
        return None
    st.subheader(_t("optimizer", lang))
    c1, c2 = st.columns(2)
    with c1:
        wash_cost = st.slider(
            _t("wash_cost", lang),
            min_value=50_000,
            max_value=300_000,
            value=int(config.WASH_COST_TL_CENTRAL),
            step=10_000,
        )
    with c2:
        price = st.slider(
            _t("electricity_price", lang),
            min_value=500,
            max_value=3500,
            value=1500,
            step=100,
        )
    optimization = compute_live_optimization(
        wash_cost_tl=float(wash_cost),
        price_tl_mwh=float(price),
        rate_band=snapshot.rate_band,
        daily_energy_kwh=snapshot.daily_energy_kwh,
    )
    st.metric(
        _t("t_star", lang),
        format_t_star_days(optimization["t_star_days"], unit=_t("days_unit", lang)),
        help=_t("t_star_help", lang),
    )
    st.plotly_chart(cost_curve_figure(optimization, lang), use_container_width=True)
    return optimization


def render_data_tab(snapshot: DashboardSnapshot, lang: str) -> None:
    preview = format_data_preview(snapshot.master, lang=lang)
    if preview is None:
        st.info(_t("no_daily_rows", lang))
        return
    st.caption(_t("data_preview_caption", lang))
    st.dataframe(preview, use_container_width=True, hide_index=True)


def render_dashboard(snapshot: DashboardSnapshot, lang: str) -> None:
    if not snapshot.available:
        st.warning(translate_backend_message(snapshot.message, lang))
        return

    render_validation_line(snapshot, lang)
    render_hero_and_chips(snapshot, lang)

    tab_overview, tab_charts, tab_segments, tab_economy, tab_data = st.tabs(
        [
            _t("overview", lang),
            _t("charts", lang),
            _t("segments", lang),
            _t("economy", lang),
            _t("data_tab", lang),
        ]
    )
    optimization = {"t_star_days": 0, "wash_cost_tl": 0, "price_tl_mwh": 0}
    with tab_overview:
        render_overview_tab(snapshot, lang)
    with tab_charts:
        render_charts_tab(snapshot, lang)
    with tab_segments:
        render_segments_tab(snapshot, lang)
    with tab_economy:
        result = render_economy_tab(snapshot, lang)
        if isinstance(result, dict):
            optimization = result
    with tab_data:
        render_data_tab(snapshot, lang)

    summary = build_results_summary_markdown(snapshot, optimization)
    st.download_button(
        _t("download_summary", lang),
        data=summary,
        file_name="spis_summary.md",
        mime="text/markdown",
    )


def main() -> None:
    inject_styles()
    default_lang = st.session_state.get("ui_lang", "TR")
    lang = st.sidebar.selectbox(
        _t("language_label", default_lang),
        LANG_OPTIONS,
        index=LANG_OPTIONS.index(default_lang) if default_lang in LANG_OPTIONS else 0,
        format_func=_language_name,
        key="ui_lang",
    )
    render_compact_header(lang)
    snapshot = load_input_snapshot(lang)
    if snapshot is not None and snapshot.available:
        render_dashboard(snapshot, lang)
    elif snapshot is None:
        st.info(_t("waiting_upload", lang))
    render_footer(lang)


if __name__ == "__main__":
    main()
