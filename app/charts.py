"""Plotly chart builders for the SPIS Streamlit dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

BRAND = "#1f6feb"
MUTED = "#57606a"
ACCENT_FILL = "rgba(31, 111, 235, 0.16)"
TRACK = "#d0d7de"


def _lang(lang: str, en: str, tr: str) -> str:
    return tr if lang == "TR" else en


def _rate_unit(lang: str) -> str:
    return "%/gün" if lang == "TR" else "%/day"


def _rate_hover_template(lang: str) -> str:
    unit = _rate_unit(lang)
    return f"%{{x:.2f}} {unit}<extra></extra>"


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
    labels = [str(int(seg_id)) for seg_id in frame["segment_id"]]
    lower_err = frame["soiling_rate_pct_per_day"] - frame["soiling_rate_ci_lower"]
    upper_err = frame["soiling_rate_ci_upper"] - frame["soiling_rate_pct_per_day"]
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=frame["soiling_rate_pct_per_day"],
                marker={"color": BRAND, "line": {"width": 0}},
                width=0.35,
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "arrayminus": lower_err,
                    "array": upper_err,
                    "thickness": 1.2,
                    "width": 4,
                    "color": MUTED,
                },
                hovertemplate=(
                    f"{_lang(lang, 'Segment', 'Segment')} %{{x}}<br>"
                    f"{_lang(lang, 'Rate', 'Hız')}=%{{y:.2f}} {_rate_unit(lang)}<extra></extra>"
                ),
            )
        ]
    )
    fig.add_hline(y=0, line={"color": MUTED, "width": 1, "dash": "dash"})
    fig.update_layout(
        height=340,
        margin={"l": 40, "r": 20, "t": 40, "b": 40},
        title=_lang(lang, "Soiling rate by wash segment", "Yıkama segmentine göre kirlenme"),
        xaxis={
            "title": _lang(lang, "Segment", "Segment"),
            "type": "category",
            "categoryorder": "array",
            "categoryarray": labels,
        },
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
        line={"color": BRAND, "width": 2, "dash": "dash"},
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
    """Horizontal range indicator for pooled clear-sky rate with zero reference."""
    x_min = min(-0.20, lower - 0.02, rate - 0.02)
    x_max = max(0.05, upper + 0.02, rate + 0.02)
    if x_min > 0:
        x_min = -0.05
    if x_max < 0:
        x_max = 0.05

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[x_min, x_max],
            y=[0, 0],
            mode="lines",
            line={"color": TRACK, "width": 3},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_vrect(
        x0=lower,
        x1=upper,
        fillcolor=ACCENT_FILL,
        line_width=0,
        layer="below",
    )
    fig.add_vline(x=0, line={"color": MUTED, "width": 1, "dash": "dash"})
    fig.add_trace(
        go.Scatter(
            x=[rate],
            y=[0],
            mode="markers",
            marker={"color": BRAND, "size": 13, "symbol": "diamond"},
            name=_lang(lang, "Pooled estimate", "Havuzlanmış tahmin"),
            hovertemplate=_rate_hover_template(lang),
        )
    )
    fig.add_annotation(
        x=0,
        y=-0.55,
        text="0",
        showarrow=False,
        font={"size": 11, "color": MUTED},
        yref="y",
    )
    fig.update_layout(
        height=130,
        margin={"l": 48, "r": 16, "t": 8, "b": 36},
        title=_lang(lang, "Clear-sky rate (95% CI)", "Açık gökyüzü hızı (%95 GA)"),
        xaxis={
            "title": _lang(lang, "Soiling rate (%/day)", "Kirlenme hızı (%/gün)"),
            "range": [x_min, x_max],
            "zeroline": False,
        },
        yaxis={"visible": False, "range": [-1, 0.6], "showticklabels": False},
        showlegend=False,
    )
    return fig
