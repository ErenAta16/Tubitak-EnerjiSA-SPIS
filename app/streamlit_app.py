"""SPIS web interface for non-developer users."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from app.ui_logic import (
    ALICE_SPRINGS_SITE_KEY,
    DashboardSnapshot,
    build_results_summary_markdown,
    compute_live_optimization,
    list_downloadable_figures,
    load_dashboard_snapshot,
    validate_upload_frame,
)
from spis import config
from spis.sites import DEFAULT_SITE

st.set_page_config(page_title="SPIS", layout="wide")

LABELS = {
    "title": (
        "SPIS — Solar Performance Improvement System",
        "SPIS — Güneş Performans İyileştirme Sistemi",
    ),
    "subtitle": (
        "Data-driven soiling analysis and wash scheduling for PV plants.",
        "PV santralleri için veri tabanlı kirlenme analizi ve yıkama planlaması.",
    ),
    "run": ("Show results", "Sonuçları göster"),
    "soiling": ("Soiling rate (clear-sky)", "Kirlenme hızı (açık gökyüzü)"),
    "optimizer": ("Economic optimizer", "Ekonomik optimizasyon"),
    "pollution": ("Pollution test", "Kirlilik testi"),
    "comparison": ("Site comparison", "Santral karşılaştırması"),
}


def _t(key: str, lang: str) -> str:
    en, tr = LABELS[key]
    return tr if lang == "TR" else en


def render_landing(lang: str) -> None:
    st.title(_t("title", lang))
    st.caption(_t("subtitle", lang))
    st.markdown(
        """
        **SPIS** estimates how fast panel soiling reduces performance between washes and
        recommends a wash interval that balances lost energy against wash cost.

        **SPIS**, panellerin yıkamalar arasında performansı ne hızla düşürdüğünü tahmin eder
        ve yıkama maliyeti ile kayıp enerjiyi dengeleyen bir yıkama aralığı önerir.
        """
    )


def load_input_snapshot() -> DashboardSnapshot | None:
    st.subheader("Data / Veri")
    source = st.radio(
        "Input source / Veri kaynağı",
        ["Example site / Örnek santral", "Upload CSV / CSV yükle"],
        horizontal=True,
    )
    if source.startswith("Example"):
        site_label = st.selectbox(
            "Site / Santral",
            [
                ("Canakkale", DEFAULT_SITE),
                ("Alice Springs (DKASC)", ALICE_SPRINGS_SITE_KEY),
            ],
            format_func=lambda item: item[0],
        )
        return load_dashboard_snapshot(site_label[1])
    uploaded = st.file_uploader("Daily CSV (date, production, irradiation)", type=["csv"])
    if uploaded is None:
        return None
    frame = pd.read_csv(uploaded)
    result = validate_upload_frame(frame)
    if not result.ok:
        st.error(result.message)
        return None
    st.success(result.message)
    upload_master = result.frame.assign(pi_temp_corrected=result.frame["pi"])
    return DashboardSnapshot(
        site_key="upload",
        site_name="Uploaded data / Yüklenen veri",
        available=True,
        message="Upload validated; pollution and optimizer need full CLI pipeline outputs.",
        clear_sky_rate_pct_per_day=None,
        clear_sky_ci_lower=None,
        clear_sky_ci_upper=None,
        pollution_verdict="Upload mode: run the CLI pipeline for pollution testing.",
        daily_energy_kwh=float(result.frame["production"].median()),
        rate_band=None,
        master=upload_master,
    )


def render_dashboard(snapshot: DashboardSnapshot, lang: str) -> None:
    if not snapshot.available:
        st.warning(snapshot.message)
        return
    st.success(snapshot.message)
    col1, col2 = st.columns(2)
    with col1:
        st.metric(
            _t("soiling", lang),
            f"{snapshot.clear_sky_rate_pct_per_day:.4f} %/day"
            if snapshot.clear_sky_rate_pct_per_day is not None
            else "n/a",
            help="Negative means performance drops between washes.",
        )
        if snapshot.clear_sky_ci_lower is not None:
            st.caption(
                f"95% CI: {snapshot.clear_sky_ci_lower:.4f} .. "
                f"{snapshot.clear_sky_ci_upper:.4f} %/day"
            )
    with col2:
        st.metric(
            "Median daily energy / Günlük enerji",
            f"{snapshot.daily_energy_kwh:.0f} kWh" if snapshot.daily_energy_kwh else "n/a",
        )

    st.subheader(_t("pollution", lang))
    st.write(snapshot.pollution_verdict)

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
        st.metric("Optimal wash interval T*", f"{optimization['t_star_days']:.0f} days")
        fig, ax = plt.subplots(figsize=(8, 3))
        curve = optimization["cost_curve"]
        ax.plot(curve["interval_days"], curve["total_cost_per_day_tl"])
        ax.set_xlabel("Wash interval (days)")
        ax.set_ylabel("Total cost per day (TL)")
        ax.axvline(optimization["t_star_days"], color="red", linestyle="--", label="T*")
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
    snapshot = load_input_snapshot()
    if st.button(_t("run", lang)) and snapshot is not None:
        render_dashboard(snapshot, lang)


if __name__ == "__main__":
    main()
