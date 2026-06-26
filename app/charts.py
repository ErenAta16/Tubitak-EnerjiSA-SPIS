"""Plotly chart builders for the SPIS Streamlit dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

BRAND = "#1f6feb"
MUTED = "#57606a"
POSITIVE = "#1a7f37"
NEGATIVE = "#cf222e"


def _lang(lang: str, en: str, tr: str) -> str:
    return tr if lang == "TR" else en


def pi_timeline_figure(master: pd.DataFrame, lang: str = "EN") -> go.Figure:
    """Performance index over time with wash-event markers."""
    frame = master.sort_values("date").copy()
    ycol = "pi_temp_corrected" if "pi_temp_corrected" in frame.columns else "pi"
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame[ycol],
            mode="lines",
            name=_lang(lang, "Performance index", "Performans endeksi"),
            line={"color": BRAND, "width": 1.5},
            hovertemplate="%{x|%Y-%m-%d}<br>PI=%{y:.3f}<extra></extra>",
        )
    )
    if "segment_id" in frame.columns and "days_since_wash" in frame.columns:
        wash_days = frame.loc[frame["days_since_wash"] == 0, "date"]
        if not wash_days.empty:
            for wash_date in wash_days:
                fig.add_vline(
                    x=wash_date,
                    line={"color": MUTED, "width": 1, "dash": "dot"},
                )
            fig.add_trace(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode="lines",
                    line={"color": MUTED, "dash": "dot"},
                    name=_lang(lang, "Wash event", "Yıkama"),
                )
            )
    fig.update_layout(
        height=360,
        margin={"l": 40, "r": 20, "t": 40, "b": 40},
        title=_lang(lang, "Performance index timeline", "Performans endeksi zaman serisi"),
        xaxis_title=_lang(lang, "Date", "Tarih"),
        yaxis_title="PI",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    return fig


def production_irradiation_figure(master: pd.DataFrame, lang: str = "EN") -> go.Figure:
    """Daily production and irradiation on shared timeline."""
    frame = master.sort_values("date").copy()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=frame["date"],
            y=frame["production"],
            name=_lang(lang, "Production (kWh)", "Üretim (kWh)"),
            marker={"color": "#54aeff", "opacity": 0.55},
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f} kWh<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame["irradiation"],
            name=_lang(lang, "Irradiation (Wh/m²)", "Işınım (Wh/m²)"),
            line={"color": "#bf8700", "width": 1.2},
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f}<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.update_layout(
        height=360,
        margin={"l": 40, "r": 40, "t": 40, "b": 40},
        title=_lang(lang, "Daily production vs irradiation", "Günlük üretim ve ışınım"),
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    fig.update_yaxes(title_text=_lang(lang, "Production (kWh)", "Üretim (kWh)"), secondary_y=False)
    fig.update_yaxes(
        title_text=_lang(lang, "Irradiation (Wh/m²)", "Işınım (Wh/m²)"),
        secondary_y=True,
    )
    return fig


def segment_slopes_figure(segments: pd.DataFrame, lang: str = "EN") -> go.Figure:
    """Per-segment clear-sky soiling slopes with confidence intervals."""
    frame = segments.sort_values("segment_id").copy()
    if frame.empty:
        return go.Figure()
    colors = [
        NEGATIVE if rate < 0 else POSITIVE
        for rate in frame["soiling_rate_pct_per_day"].fillna(0.0)
    ]
    fig = go.Figure(
        data=[
            go.Bar(
                x=frame["segment_id"].astype(str),
                y=frame["soiling_rate_pct_per_day"],
                marker={"color": colors},
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "arrayminus": frame["soiling_rate_pct_per_day"]
                    - frame["soiling_rate_ci_lower"],
                    "array": frame["soiling_rate_ci_upper"]
                    - frame["soiling_rate_pct_per_day"],
                    "color": MUTED,
                },
                hovertemplate=(
                    "Segment %{x}<br>"
                    + _lang(lang, "Rate", "Hız")
                    + "=%{y:.3f} %/day<extra></extra>"
                ),
            )
        ]
    )
    fig.add_hline(y=0, line={"color": MUTED, "width": 1, "dash": "dash"})
    fig.update_layout(
        height=340,
        margin={"l": 40, "r": 20, "t": 40, "b": 40},
        title=_lang(lang, "Soiling rate by wash segment", "Yıkama segmentine göre kirlenme"),
        xaxis_title=_lang(lang, "Segment", "Segment"),
        yaxis_title=_lang(lang, "Soiling rate (%/day)", "Kirlenme hızı (%/gün)"),
    )
    return fig


def cost_curve_figure(optimization: dict[str, Any], lang: str = "EN") -> go.Figure:
    """Total daily cost vs wash interval with optimal T* marker."""
    curve = optimization["cost_curve"]
    t_star = float(optimization["t_star_days"])
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=curve["interval_days"],
            y=curve["total_cost_per_day_tl"],
            mode="lines",
            name=_lang(lang, "Total daily cost", "Toplam günlük maliyet"),
            line={"color": BRAND, "width": 2},
            hovertemplate="T=%{x:.0f} d<br>%{y:,.0f} TL/d<extra></extra>",
        )
    )
    fig.add_vline(
        x=t_star,
        line={"color": NEGATIVE, "width": 2, "dash": "dash"},
        annotation_text=f"T*={t_star:.0f}d",
        annotation_position="top right",
    )
    fig.update_layout(
        height=340,
        margin={"l": 40, "r": 20, "t": 40, "b": 40},
        title=_lang(lang, "Economic cost vs wash interval", "Maliyet ve yıkama aralığı"),
        xaxis_title=_lang(lang, "Wash interval (days)", "Yıkama aralığı (gün)"),
        yaxis_title=_lang(lang, "Total cost per day (TL)", "Toplam günlük maliyet (TL)"),
    )
    return fig


def rate_ci_figure(
    rate: float,
    lower: float,
    upper: float,
    lang: str = "EN",
) -> go.Figure:
    """Horizontal interval plot for the pooled clear-sky soiling rate."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[lower, upper],
            y=[0, 0],
            mode="lines",
            line={"color": BRAND, "width": 8},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[rate],
            y=[0],
            mode="markers",
            marker={"color": NEGATIVE, "size": 14, "symbol": "diamond"},
            name=_lang(lang, "Pooled estimate", "Havuzlanmış tahmin"),
            hovertemplate="%{x:.4f} %/day<extra></extra>",
        )
    )
    fig.update_layout(
        height=180,
        margin={"l": 40, "r": 20, "t": 30, "b": 30},
        title=_lang(lang, "Clear-sky rate (95% CI)", "Açık gökyüzü hızı (%95 GA)"),
        xaxis_title=_lang(lang, "Soiling rate (%/day)", "Kirlenme hızı (%/gün)"),
        yaxis={"visible": False, "showticklabels": False},
    )
    return fig
