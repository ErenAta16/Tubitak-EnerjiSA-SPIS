"""Plotly chart builders for the SPIS Streamlit dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.theme import (
    ACCENT_TINT,
    CHART_HEIGHT_COMPACT,
    HAIRLINE,
    PRIMARY,
    SECONDARY_LINE,
    apply_spis_layout,
    format_decimal,
    format_integer,
    format_rate_axis,
)


def _lang(lang: str, en: str, tr: str) -> str:
    return tr if lang == "TR" else en


def _rate_unit(lang: str) -> str:
    return "%/gün" if lang == "TR" else "%/day"


def _format_hover_rate(value: float, lang: str) -> str:
    return f"{format_decimal(value, lang)} {_rate_unit(lang)}"


def _format_hover_pi(value: float, lang: str) -> str:
    return format_decimal(value, lang, decimals=3)


def _format_hover_int(value: float, lang: str) -> str:
    return format_integer(value, lang, na="0")


def pi_timeline_figure(master: pd.DataFrame, lang: str = "EN") -> go.Figure:
    """Performance index over time with wash-event markers."""
    frame = master.sort_values("date").copy()
    ycol = "pi_temp_corrected" if "pi_temp_corrected" in frame.columns else "pi"
    y_values = frame[ycol]
    custom = [[_format_hover_pi(y, lang)] for y in y_values]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["date"],
            y=y_values,
            mode="lines",
            name=_lang(lang, "Performance index", "Performans endeksi"),
            line={"color": PRIMARY, "width": 1.5},
            customdata=custom,
            hovertemplate="%{x|%Y-%m-%d}<br>PI=%{customdata[0]}<extra></extra>",
        )
    )
    if "segment_id" in frame.columns and "days_since_wash" in frame.columns:
        wash_days = frame.loc[frame["days_since_wash"] == 0, "date"]
        if not wash_days.empty:
            for wash_date in wash_days:
                fig.add_vline(
                    x=wash_date,
                    line={"color": SECONDARY_LINE, "width": 1, "dash": "dot"},
                )
            fig.add_trace(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode="lines",
                    line={"color": SECONDARY_LINE, "dash": "dot"},
                    name=_lang(lang, "Wash event", "Yıkama"),
                    hoverinfo="skip",
                )
            )
    apply_spis_layout(
        fig,
        title=_lang(lang, "Performance index timeline", "Performans endeksi zaman serisi"),
    )
    fig.update_layout(xaxis_title=_lang(lang, "Date", "Tarih"), yaxis_title="PI")
    return fig


def production_irradiation_figure(master: pd.DataFrame, lang: str = "EN") -> go.Figure:
    """Daily production and irradiation on shared timeline."""
    frame = master.sort_values("date").copy()
    prod_custom = [[_format_hover_int(y, lang)] for y in frame["production"]]
    irrad_custom = [[_format_hover_int(y, lang)] for y in frame["irradiation"]]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=frame["date"],
            y=frame["production"],
            name=_lang(lang, "Production (kWh)", "Üretim (kWh)"),
            marker={"color": PRIMARY, "opacity": 0.35},
            customdata=prod_custom,
            hovertemplate="%{x|%Y-%m-%d}<br>%{customdata[0]} kWh<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame["irradiation"],
            name=_lang(lang, "Irradiation (Wh/m²)", "Işınım (Wh/m²)"),
            line={"color": SECONDARY_LINE, "width": 1.2},
            customdata=irrad_custom,
            hovertemplate="%{x|%Y-%m-%d}<br>%{customdata[0]}<extra></extra>",
        ),
        secondary_y=True,
    )
    apply_spis_layout(
        fig,
        title=_lang(lang, "Daily production vs irradiation", "Günlük üretim ve ışınım"),
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
    rates = frame["soiling_rate_pct_per_day"]
    lower_err = rates - frame["soiling_rate_ci_lower"]
    upper_err = frame["soiling_rate_ci_upper"] - rates
    rate_custom = [[_format_hover_rate(y, lang)] for y in rates]
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=rates,
                marker={"color": PRIMARY, "line": {"width": 0}},
                width=0.35,
                customdata=rate_custom,
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "arrayminus": lower_err,
                    "array": upper_err,
                    "thickness": 1.2,
                    "width": 4,
                    "color": SECONDARY_LINE,
                },
                hovertemplate=(
                    f"{_lang(lang, 'Segment', 'Segment')} %{{x}}<br>"
                    f"{_lang(lang, 'Rate', 'Hız')}=%{{customdata[0]}}<extra></extra>"
                ),
            )
        ]
    )
    fig.add_hline(y=0, line={"color": SECONDARY_LINE, "width": 1, "dash": "dash"})
    apply_spis_layout(
        fig,
        title=_lang(lang, "Soiling rate by wash segment", "Yıkama segmentine göre kirlenme"),
    )
    fig.update_layout(
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
    cost_custom = [[_format_hover_int(y, lang)] for y in curve["total_cost_per_day_tl"]]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=curve["interval_days"],
            y=curve["total_cost_per_day_tl"],
            mode="lines",
            name=_lang(lang, "Total daily cost", "Toplam günlük maliyet"),
            line={"color": PRIMARY, "width": 2},
            customdata=cost_custom,
            hovertemplate=(
                f"T=%{{x:.0f}} {_lang(lang, 'd', 'gün')}<br>"
                f"%{{customdata[0]}} TL/{_lang(lang, 'd', 'gün')}<extra></extra>"
            ),
        )
    )
    fig.add_vline(
        x=t_star,
        line={"color": PRIMARY, "width": 1.5, "dash": "dash"},
        annotation_text=f"T*={format_integer(t_star, lang)}",
        annotation_font={"size": 11, "color": PRIMARY},
        annotation_position="top right",
    )
    apply_spis_layout(
        fig,
        title=_lang(lang, "Economic cost vs wash interval", "Maliyet ve yıkama aralığı"),
    )
    fig.update_layout(
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
            line={"color": HAIRLINE, "width": 3},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_vrect(
        x0=lower,
        x1=upper,
        fillcolor=ACCENT_TINT,
        line_width=0,
        layer="below",
    )
    fig.add_vline(x=0, line={"color": SECONDARY_LINE, "width": 1, "dash": "dash"})
    fig.add_trace(
        go.Scatter(
            x=[rate],
            y=[0],
            mode="markers",
            marker={"color": PRIMARY, "size": 12, "symbol": "diamond"},
            name=_lang(lang, "Pooled estimate", "Havuzlanmış tahmin"),
            customdata=[[_format_hover_rate(rate, lang)]],
            hovertemplate="%{customdata[0]}<extra></extra>",
        )
    )
    apply_spis_layout(
        fig,
        title=_lang(lang, "Clear-sky rate (95% CI)", "Açık gökyüzü hızı (%95 GA)"),
        height=CHART_HEIGHT_COMPACT,
        compact=True,
    )
    tick_count = 5
    span = x_max - x_min
    raw_ticks = [x_min + span * i / (tick_count - 1) for i in range(tick_count)]
    ticktext = [format_rate_axis(tick, lang) for tick in raw_ticks]
    fig.update_layout(
        xaxis={
            "title": _lang(lang, "Soiling rate (%/day)", "Kirlenme hızı (%/gün)"),
            "range": [x_min, x_max],
            "tickvals": raw_ticks,
            "ticktext": ticktext,
            "zeroline": False,
        },
        yaxis={"visible": False, "range": [-1, 0.55], "showticklabels": False, "fixedrange": True},
        showlegend=False,
    )
    fig.add_annotation(
        x=0,
        y=-0.45,
        text="0",
        showarrow=False,
        font={"size": 11, "color": SECONDARY_LINE},
        yref="y",
    )
    return fig
