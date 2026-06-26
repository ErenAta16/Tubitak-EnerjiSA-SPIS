"""SPIS web interface for non-developer users."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from app.ui_logic import (
    DashboardSnapshot,
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

st.set_page_config(page_title="SPIS", layout="wide")

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
    "run": ("Show results", "Sonuçları göster"),
    "soiling": ("Soiling rate (clear-sky)", "Kirlenme hızı (açık gökyüzü)"),
    "soiling_help": (
        "Negative %/day means performance index falls between washes on sunny days.",
        "Negatif %/gün, güneşli günlerde performans endeksinin yıkamalar arasında düştüğünü gösterir.",
    ),
    "energy_help": (
        "Typical clean-day energy used for the economic optimizer (not plant nameplate).",
        "Ekonomik optimizasyon için kullanılan tipik temiz-gün enerjisi (nominal kapasite değil).",
    ),
    "optimizer": ("Economic optimizer", "Ekonomik optimizasyon"),
    "pollution": ("Pollution test", "Kirlilik testi"),
    "comparison": ("Site comparison", "Santral karşılaştırması"),
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


def render_landing(lang: str) -> None:
    st.title(_t("title", lang))
    st.caption(_t("subtitle", lang))
    with st.expander(_t("how_title", lang), expanded=False):
        for step in _steps(lang):
            st.markdown(step)


def render_footer(lang: str) -> None:
    st.divider()
    st.caption(
        f"{_t('footer', lang)} · [DATA_USE.md](https://github.com/ErenAta16/Tubitak-EnerjiSA-SPIS/blob/main/DATA_USE.md)"
    )


def load_input_snapshot(lang: str) -> DashboardSnapshot | None:
    st.subheader("Data / Veri")
    source = st.radio(
        "Input source / Veri kaynağı",
        ["Example site / Örnek santral", "Upload CSV / CSV yükle"],
        horizontal=True,
    )
    if source.startswith("Example"):
        options = list_example_site_options()
        default_index = next(
            (idx for idx, opt in enumerate(options) if opt.site_key == default_example_site_key()),
            0,
        )
        selected = st.selectbox(
            "Site / Santral",
            options,
            index=default_index,
            format_func=lambda item: item.label,
        )
        return load_dashboard_snapshot(selected.site_key)

    st.download_button(
        "Download sample CSV / Örnek CSV indir",
        data=get_sample_upload_csv_bytes(),
        file_name="spis_upload_template.csv",
        mime="text/csv",
    )
    st.caption("Required columns: date, production, irradiation")
    uploaded = st.file_uploader("Daily CSV (date, production, irradiation)", type=["csv"])
    if uploaded is None:
        return None
    try:
        frame = pd.read_csv(uploaded)
    except Exception:
        st.error("Could not read the CSV file. Save as UTF-8 comma-separated text.")
        return None
    snapshot = load_upload_dashboard_snapshot(frame)
    if not snapshot.available:
        st.error(snapshot.message)
        return None
    st.success(snapshot.message)
    return snapshot


def render_dashboard(snapshot: DashboardSnapshot, lang: str) -> None:
    if not snapshot.available:
        st.warning(snapshot.message)
        return

    st.success(snapshot.message)
    rate = snapshot.clear_sky_rate_pct_per_day
    st.markdown(f"**{plain_language_soiling_line(rate, lang)}**")

    col1, col2 = st.columns(2)
    with col1:
        st.metric(
            _t("soiling", lang),
            f"{rate:.4f} %/day" if rate is not None else "n/a",
            help=_t("soiling_help", lang),
        )
        if snapshot.clear_sky_ci_lower is not None and rate is not None:
            st.caption(
                f"95% CI: {snapshot.clear_sky_ci_lower:.4f} .. "
                f"{snapshot.clear_sky_ci_upper:.4f} %/day"
            )
    with col2:
        st.metric(
            "Median daily energy / Günlük enerji",
            f"{snapshot.daily_energy_kwh:.0f} kWh" if snapshot.daily_energy_kwh else "n/a",
            help=_t("energy_help", lang),
        )

    st.subheader(_t("pollution", lang))
    st.info(snapshot.pollution_verdict)

    optimization = {"t_star_days": 0, "wash_cost_tl": 0, "price_tl_mwh": 0}
    if snapshot.rate_band is not None and snapshot.daily_energy_kwh is not None:
        st.subheader(_t("optimizer", lang))
        wash_cost = st.slider(
            "Wash cost (TL) / Yıkama maliyeti (TL)",
            min_value=50_000,
            max_value=300_000,
            value=int(config.WASH_COST_TL_CENTRAL),
            step=10_000,
        )
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
        fig, ax = plt.subplots(figsize=(8, 3))
        curve = optimization["cost_curve"]
        ax.plot(curve["interval_days"], curve["total_cost_per_day_tl"])
        ax.set_xlabel("Wash interval (days)")
        ax.set_ylabel("Total cost per day (TL)")
        ax.axvline(optimization["t_star_days"], color="#1f6feb", linestyle="--", label="T*")
        ax.legend()
        st.pyplot(fig)
        plt.close(fig)

    if snapshot.master is not None:
        st.subheader("PI timeline / PI zaman serisi")
        plot_frame = snapshot.master.sort_values("date")
        ycol = "pi_temp_corrected" if "pi_temp_corrected" in plot_frame.columns else "pi"
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.plot(plot_frame["date"], plot_frame[ycol])
        ax.set_ylabel("Performance index")
        st.pyplot(fig)
        plt.close(fig)

    if snapshot.comparison_table is not None:
        st.subheader(_t("comparison", lang))
        st.dataframe(snapshot.comparison_table, use_container_width=True)

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
    lang = st.sidebar.selectbox("Language / Dil", ["EN", "TR"])
    render_landing(lang)
    snapshot = load_input_snapshot(lang)
    if st.button(_t("run", lang)) and snapshot is not None:
        render_dashboard(snapshot, lang)
    render_footer(lang)


if __name__ == "__main__":
    main()
