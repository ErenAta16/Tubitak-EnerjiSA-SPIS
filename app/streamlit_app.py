"""SPIS web interface for non-developer users."""

from __future__ import annotations

import sys


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
from app.models import SAMPLE_UPLOAD_KEY, DashboardSnapshot
from app.sample_data import load_sample_upload_snapshot
from app.tables import format_comparison_table, format_data_preview, format_segments_table
from app.ui_logic import (
    build_results_summary_markdown,
    compute_live_optimization,
    default_example_site_key,
    get_sample_upload_csv_bytes,
    list_downloadable_figures,
    list_example_site_options,
    load_dashboard_snapshot,
    load_upload_dashboard_snapshot,
    plain_language_soiling_line,
)
from spis import config

UI_BUILD = "2026-06-26-upload-v3"

st.set_page_config(page_title="SPIS", layout="wide", initial_sidebar_state="expanded")

TEXT = {
    "title": (
        "SPIS — Solar Performance Improvement System",
        "SPIS — Güneş Performans İyileştirme Sistemi",
    ),
    "subtitle": (
        "Estimate soiling loss between washes and a cost-optimal wash interval.",
        "Yıkamalar arası kirlenme kaybını ve maliyet-optimal yıkama aralığını tahmin edin.",
    ),
    "how_title": ("How it works", "Nasıl çalışır"),
    "how_steps": (
        [
            "1. Load daily production and irradiation (or use the synthetic demo).",
            "2. Keep clear-sky days and fit soiling trends between washes.",
            "3. Estimate the daily performance drop rate (%/day) with uncertainty.",
            "4. Compare pollution indicators (when available).",
            "5. Pick wash cost and electricity price to find the economic optimum T*.",
        ],
        [
            "1. Günlük üretim ve ışınım verisini yükleyin (veya sentetik demoyu kullanın).",
            "2. Açık gökyüzü günlerini seçip yıkamalar arası trendi uydurun.",
            "3. Günlük performans düşüş hızını (%/gün) belirsizlikle tahmin edin.",
            "4. Kirlilik göstergelerini karşılaştırın (varsa).",
            "5. Yıkama maliyeti ve elektrik fiyatı ile ekonomik optimum T* bulun.",
        ],
    ),
    "overview": ("Overview", "Özet"),
    "charts": ("Charts", "Grafikler"),
    "segments": ("Segments", "Segmentler"),
    "economy": ("Economics", "Ekonomi"),
    "data_tab": ("Data table", "Veri tablosu"),
    "soiling": ("Soiling rate (clear-sky)", "Kirlenme hızı (açık gökyüzü)"),
    "soiling_help": (
        "Negative %/day means performance index falls between washes on sunny days.",
        "Negatif %/gün, güneşli günlerde performans endeksinin yıkamalar arasında "
        "düştüğünü gösterir.",
    ),
    "energy_help": (
        "Typical clean-day energy used for the economic optimizer (not plant nameplate).",
        "Ekonomik optimizasyon için kullanılan tipik temiz-gün enerjisi (nominal kapasite değil).",
    ),
    "segments_count": ("Wash segments", "Yıkama segmenti"),
    "days_count": ("Daily rows", "Günlük satır"),
    "optimizer": ("Economic optimizer", "Ekonomik optimizasyon"),
    "pollution": ("Pollution test", "Kirlilik testi"),
    "comparison": ("Site comparison", "Santral karşılaştırması"),
    "waiting_upload": (
        "Choose an example site in the sidebar or upload a daily CSV.",
        "Sidebar'dan örnek santral seçin veya günlük CSV yükleyin.",
    ),
    "sample_preview": (
        "Showing the built-in sample CSV below. Upload your own file to replace it.",
        "Aşağıda gömülü örnek CSV gösteriliyor. Kendi dosyanızı yükleyerek değiştirin.",
    ),
    "footer": (
        "TUBITAK 2209-B research demo — code under MIT; plant data proprietary. See DATA_USE.md.",
        "TUBITAK 2209-B araştırma demosu — kod MIT; santral verisi özel. DATA_USE.md.",
    ),
}


def _t(key: str, lang: str) -> str:
    en, tr = TEXT[key]
    return tr if lang == "TR" else en


def _steps(lang: str) -> list[str]:
    en, tr = TEXT["how_steps"]
    return tr if lang == "TR" else en


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] {
            background: #f6f8fa;
            border: 1px solid #d0d7de;
            border-radius: 0.5rem;
            padding: 0.75rem 1rem;
        }
        .spis-hero {
            background: linear-gradient(120deg, #f6f8fa 0%, #ffffff 100%);
            border: 1px solid #d0d7de;
            border-radius: 0.75rem;
            padding: 1rem 1.25rem;
            margin-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_landing(lang: str) -> None:
    st.markdown(
        f"<div class='spis-hero'><h1 style='margin:0;padding:0;'>{_t('title', lang)}</h1>"
        f"<p style='margin:0.35rem 0 0;color:#57606a;'>{_t('subtitle', lang)}</p></div>",
        unsafe_allow_html=True,
    )
    with st.expander(_t("how_title", lang), expanded=False):
        for step in _steps(lang):
            st.markdown(step)


def render_footer(lang: str) -> None:
    st.divider()
    st.caption(
        f"{_t('footer', lang)} · [DATA_USE.md](https://github.com/ErenAta16/Tubitak-EnerjiSA-SPIS/blob/main/DATA_USE.md)"
    )


def load_input_snapshot(lang: str) -> DashboardSnapshot | None:
    st.sidebar.header("Data / Veri")
    source = st.sidebar.radio(
        "Input source / Veri kaynağı",
        ["Example site / Örnek santral", "Upload CSV / CSV yükle"],
    )
    if source.startswith("Example"):
        options = list_example_site_options()
        default_index = next(
            (idx for idx, opt in enumerate(options) if opt.site_key == default_example_site_key()),
            0,
        )
        selected = st.sidebar.selectbox(
            "Site / Santral",
            options,
            index=default_index,
            format_func=lambda item: item.label,
        )
        return load_dashboard_snapshot(selected.site_key)

    st.sidebar.download_button(
        "Download sample CSV / Örnek CSV indir",
        data=get_sample_upload_csv_bytes(),
        file_name="spis_upload_template.csv",
        mime="text/csv",
    )
    st.sidebar.caption("Required columns: date, production, irradiation")
    uploaded = st.sidebar.file_uploader("Daily CSV", type=["csv"], label_visibility="collapsed")
    if uploaded is None:
        return load_sample_upload_snapshot()
    import pandas as pd

    try:
        frame = pd.read_csv(uploaded)
    except Exception:
        st.error("Could not read the CSV file. Save as UTF-8 comma-separated text.")
        return None
    snapshot = load_upload_dashboard_snapshot(frame)
    if not snapshot.available:
        st.error(snapshot.message)
        return None
    st.sidebar.success(snapshot.message)
    return snapshot


def render_headline_metrics(snapshot: DashboardSnapshot, lang: str) -> None:
    rate = snapshot.clear_sky_rate_pct_per_day
    n_days = len(snapshot.master) if snapshot.master is not None else 0
    n_segments = snapshot.segment_count()
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            _t("soiling", lang),
            f"{rate:.4f} %/day" if rate is not None else "n/a",
            help=_t("soiling_help", lang),
        )
    with c2:
        ci_text = "n/a"
        if snapshot.clear_sky_ci_lower is not None and rate is not None:
            ci_text = f"{snapshot.clear_sky_ci_lower:.4f} .. {snapshot.clear_sky_ci_upper:.4f}"
        st.metric("95% CI / GA", ci_text)
    with c3:
        st.metric(
            "Median daily energy / Günlük enerji",
            f"{snapshot.daily_energy_kwh:,.0f} kWh" if snapshot.daily_energy_kwh else "n/a",
            help=_t("energy_help", lang),
        )
    with c4:
        st.metric(
            _t("segments_count", lang),
            f"{n_segments}" if n_segments else "n/a",
            delta=f"{n_days} {_t('days_count', lang).lower()}" if n_days else None,
        )


def render_overview_tab(snapshot: DashboardSnapshot, lang: str) -> None:
    rate = snapshot.clear_sky_rate_pct_per_day
    st.info(plain_language_soiling_line(rate, lang))
    st.markdown(f"**{_t('pollution', lang)}**")
    st.write(snapshot.pollution_verdict)
    if (
        rate is not None
        and snapshot.clear_sky_ci_lower is not None
        and snapshot.clear_sky_ci_upper is not None
    ):
        st.plotly_chart(
            rate_ci_figure(rate, snapshot.clear_sky_ci_lower, snapshot.clear_sky_ci_upper, lang),
            use_container_width=True,
        )
    if snapshot.comparison_table is not None:
        st.markdown(f"**{_t('comparison', lang)}**")
        comparison = format_comparison_table(snapshot.comparison_table, lang)
        if comparison is not None:
            st.dataframe(comparison, use_container_width=True, hide_index=True)


def render_charts_tab(snapshot: DashboardSnapshot, lang: str) -> None:
    if snapshot.master is None:
        st.warning("No time series available.")
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
        st.info("Segment table not available for this input.")
        return
    skip_cols = {
        "Segment",
        "Start",
        "End",
        "Başlangıç",
        "Bitiş",
        "Low confidence",
        "Düşük güven",
    }
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            col: st.column_config.NumberColumn(format="%.4f")
            for col in table.columns
            if col not in skip_cols
        },
    )


def render_economy_tab(snapshot: DashboardSnapshot, lang: str) -> None:
    if snapshot.rate_band is None or snapshot.daily_energy_kwh is None:
        st.info("Economic optimizer needs a valid soiling rate and daily energy estimate.")
        return
    st.subheader(_t("optimizer", lang))
    c1, c2 = st.columns(2)
    with c1:
        wash_cost = st.slider(
            "Wash cost (TL) / Yıkama maliyeti (TL)",
            min_value=50_000,
            max_value=300_000,
            value=int(config.WASH_COST_TL_CENTRAL),
            step=10_000,
        )
    with c2:
        price = st.slider(
            "Electricity price (TL/MWh) / Elektrik fiyatı (TL/MWh)",
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
        "Optimal wash interval T* / Optimal yıkama aralığı T*",
        f"{optimization['t_star_days']:.0f} days",
        help="Minimum total daily cost (lost energy + amortized wash cost).",
    )
    st.plotly_chart(cost_curve_figure(optimization, lang), use_container_width=True)
    return optimization


def render_data_tab(snapshot: DashboardSnapshot, lang: str) -> None:
    preview = format_data_preview(snapshot.master, lang=lang)
    if preview is None:
        st.info("No daily rows to display.")
        return
    st.caption(
        "Most recent daily rows / Son günlük satırlar"
        if lang == "EN"
        else "Son günlük satırlar / Most recent daily rows"
    )
    st.dataframe(preview, use_container_width=True, hide_index=True)


def render_dashboard(snapshot: DashboardSnapshot, lang: str) -> None:
    if not snapshot.available:
        st.warning(snapshot.message)
        return

    st.success(f"{snapshot.site_name} — {snapshot.message}")
    if snapshot.site_key == SAMPLE_UPLOAD_KEY:
        st.info(_t("sample_preview", lang))
    render_headline_metrics(snapshot, lang)

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
        "Download summary / Özeti indir",
        data=summary,
        file_name="spis_summary.md",
        mime="text/markdown",
    )
    for fig_path in list_downloadable_figures():
        st.download_button(
            f"Download {fig_path.name}",
            data=fig_path.read_bytes(),
            file_name=fig_path.name,
            mime="image/png",
        )


def main() -> None:
    inject_styles()
    lang = st.sidebar.selectbox("Language / Dil", ["EN", "TR"])
    st.sidebar.caption(f"UI build: {UI_BUILD}")
    render_landing(lang)
    snapshot = load_input_snapshot(lang)
    if snapshot is not None and snapshot.available:
        render_dashboard(snapshot, lang)
    elif snapshot is None:
        st.info(_t("waiting_upload", lang))
    render_footer(lang)


if __name__ == "__main__":
    main()
