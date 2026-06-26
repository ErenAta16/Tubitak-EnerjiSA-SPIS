"""SPIS visual design system — tokens, CSS, Plotly layout, and locale-aware numbers."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

# --- Palette ---
PAGE_BG = "#FAFAF8"
CARD_SURFACE = "#FFFFFF"
SUBTLE_SURFACE = "#F4F4F1"
HAIRLINE = "#E6E6E2"
TEXT = "#1A1A1A"
TEXT_MUTED = "#6B7280"
PRIMARY = "#0E7C66"
ACCENT_TINT = "#E6F2EF"
GRID = "#EEF0F2"
SECONDARY_LINE = "#9CA3AF"

# --- Typography (px / weight) ---
FONT_STACK = '"Inter", system-ui, -apple-system, "Segoe UI", sans-serif'
FONT_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap"

TYPE_PAGE_TITLE = (22, 600)
TYPE_SECTION = (16, 600)
TYPE_METRIC_VALUE = (26, 600)
TYPE_METRIC_LABEL = (12, 500)
TYPE_BODY = (14, 400)
TYPE_CAPTION = (12, 400)

# --- Spacing (px) ---
SPACE_BASE = 8
CARD_PADDING = 20
SECTION_GAP = 24
RADIUS_CARD = 12
RADIUS_CONTROL = 8

# --- Plotly ---
CHART_HEIGHT = 320
CHART_HEIGHT_COMPACT = 200
CHART_MARGINS = {"l": 56, "r": 24, "t": 56, "b": 44}
PLOTLY_CHART_CONFIG: dict[str, Any] = {"displayModeBar": False}


def format_decimal(value: float, lang: str, *, decimals: int = 2) -> str:
    """Locale-aware fixed-decimal formatting (comma decimal in TR)."""
    text = f"{value:.{decimals}f}"
    if lang == "TR":
        return text.replace(".", ",")
    return text


def format_integer(value: float | int | None, lang: str, *, na: str = "n/a") -> str:
    """Locale-aware integer with thousands grouping."""
    if value is None:
        return na
    formatted = f"{int(round(value)):,}"
    if lang == "TR":
        return formatted.replace(",", ".")
    return formatted


def format_percent_in_text(value: float, lang: str, *, decimals: int = 2) -> str:
    """Percent fragment for inline copy, e.g. '%0,15' in TR."""
    body = format_decimal(abs(value), lang, decimals=decimals)
    return f"%{body}"


def format_headline_rate(
    rate_pct_per_day: float | None,
    *,
    na: str,
    lang: str = "EN",
) -> str:
    """Hero soiling rate with unit."""
    if rate_pct_per_day is None:
        return na
    unit = "%/gün" if lang == "TR" else "%/day"
    body = format_decimal(rate_pct_per_day, lang)
    if rate_pct_per_day < 0:
        sign = "−" if lang == "TR" else "-"
        body = f"{sign}{body.lstrip('-')}"
    return f"{body} {unit}"


def format_rate_axis(value: float, lang: str) -> str:
    """Tick label for soiling-rate axes."""
    return format_decimal(value, lang)


def apply_spis_layout(
    fig: go.Figure,
    *,
    title: str,
    height: int = CHART_HEIGHT,
    compact: bool = False,
) -> go.Figure:
    """Apply shared margins, typography, grid, and hover defaults to a Plotly figure."""
    fig.update_layout(
        height=height if not compact else CHART_HEIGHT_COMPACT,
        margin=dict(CHART_MARGINS),
        title={
            "text": title,
            "x": 0,
            "xanchor": "left",
            "y": 0.97,
            "yanchor": "top",
            "font": {"size": TYPE_SECTION[0], "color": TEXT, "family": FONT_STACK},
        },
        paper_bgcolor=CARD_SURFACE,
        plot_bgcolor=CARD_SURFACE,
        font={"family": FONT_STACK, "size": TYPE_BODY[0], "color": TEXT},
        hovermode="closest",
        hoverlabel={
            "bgcolor": CARD_SURFACE,
            "bordercolor": HAIRLINE,
            "font": {"family": FONT_STACK, "size": TYPE_CAPTION[0], "color": TEXT},
        },
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "x": 0,
            "font": {"size": TYPE_CAPTION[0], "color": TEXT_MUTED},
        },
    )
    fig.update_xaxes(
        automargin=True,
        showgrid=True,
        gridcolor=GRID,
        gridwidth=1,
        zeroline=False,
        linecolor=HAIRLINE,
        tickfont={"size": TYPE_CAPTION[0], "color": TEXT_MUTED},
        title_font={"size": TYPE_CAPTION[0], "color": TEXT_MUTED},
    )
    fig.update_yaxes(
        automargin=True,
        showgrid=True,
        gridcolor=GRID,
        gridwidth=1,
        zeroline=False,
        linecolor=HAIRLINE,
        tickfont={"size": TYPE_CAPTION[0], "color": TEXT_MUTED},
        title_font={"size": TYPE_CAPTION[0], "color": TEXT_MUTED},
    )
    return fig


def inject_theme_css() -> str:
    """Return the full SPIS CSS theme (Inter + tokens + Streamlit chrome hiding)."""
    return f"""
    @import url('{FONT_URL}');

    html, body, [class*="css"] {{
        font-family: {FONT_STACK};
    }}

    .stApp {{
        background-color: {PAGE_BG};
        color: {TEXT};
    }}

    .block-container {{
        padding-top: {SPACE_BASE}px;
        padding-bottom: {SECTION_GAP}px;
        max-width: 1100px;
    }}

    section[data-testid="stSidebar"] .block-container {{
        padding-top: {CARD_PADDING}px;
    }}

    section[data-testid="stSidebar"] {{
        background-color: {SUBTLE_SURFACE};
        border-right: 1px solid {HAIRLINE};
    }}

    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    [data-testid="stToolbar"] {{visibility: hidden; height: 0;}}
    header[data-testid="stHeader"] {{
        background: transparent;
        pointer-events: none;
    }}
    header[data-testid="stHeader"] > div {{
        display: none;
    }}

    div[data-testid="stMetric"] {{
        background: {CARD_SURFACE};
        border: 1px solid {HAIRLINE};
        border-radius: {RADIUS_CARD}px;
        padding: {CARD_PADDING}px;
    }}

    .stTabs [data-baseweb="tab-list"] {{
        gap: {SPACE_BASE}px;
    }}

    .stTabs [data-baseweb="tab"] {{
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 12px;
        font-size: {TYPE_BODY[0]}px;
        font-weight: {TYPE_BODY[1]};
    }}

    .spis-brand-row {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 0 0 6px 0;
        padding: 0;
    }}

    .spis-wordmark {{
        font-size: {TYPE_PAGE_TITLE[0]}px;
        font-weight: {TYPE_PAGE_TITLE[1]};
        letter-spacing: 0.03em;
        color: {TEXT};
        line-height: 1.2;
    }}

    .spis-pill {{
        display: inline-block;
        font-size: 11px;
        font-weight: 500;
        text-transform: lowercase;
        color: {TEXT_MUTED};
        background: {SUBTLE_SURFACE};
        border: 1px solid {HAIRLINE};
        border-radius: 999px;
        padding: 2px 8px;
        line-height: 1.4;
    }}

    .spis-tagline {{
        margin: 0 0 {SECTION_GAP}px 0;
        padding: 0;
        font-size: {TYPE_BODY[0]}px;
        font-weight: {TYPE_BODY[1]};
        color: {TEXT_MUTED};
        line-height: 1.5;
    }}

    .spis-validation {{
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 0 0 {SECTION_GAP}px 0;
        font-size: {TYPE_CAPTION[0]}px;
        color: {TEXT_MUTED};
    }}

    .spis-validation-icon {{
        color: {PRIMARY};
        font-weight: 600;
    }}

    .spis-hero-card {{
        background: {CARD_SURFACE};
        border: 1px solid {HAIRLINE};
        border-left: 4px solid {PRIMARY};
        border-radius: {RADIUS_CARD}px;
        padding: {CARD_PADDING}px;
        margin-bottom: {SECTION_GAP}px;
    }}

    .spis-hero-label {{
        margin: 0 0 8px 0;
        font-size: {TYPE_METRIC_LABEL[0]}px;
        font-weight: {TYPE_METRIC_LABEL[1]};
        letter-spacing: 0.02em;
        color: {TEXT_MUTED};
        text-transform: none;
    }}

    .spis-hero-value {{
        margin: 0;
        font-size: {TYPE_METRIC_VALUE[0]}px;
        font-weight: {TYPE_METRIC_VALUE[1]};
        line-height: 1.15;
        color: {TEXT};
    }}

    .spis-hero-detail {{
        margin: 10px 0 0 0;
        font-size: {TYPE_BODY[0]}px;
        font-weight: {TYPE_BODY[1]};
        color: {TEXT_MUTED};
        line-height: 1.5;
    }}

    .spis-chips {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: {SPACE_BASE + 4}px;
        margin-bottom: {SECTION_GAP}px;
    }}

    .spis-chip {{
        background: {CARD_SURFACE};
        border: 1px solid {HAIRLINE};
        border-radius: {RADIUS_CARD}px;
        padding: {CARD_PADDING}px;
    }}

    .spis-chip-label {{
        margin: 0 0 6px 0;
        font-size: {TYPE_METRIC_LABEL[0]}px;
        font-weight: {TYPE_METRIC_LABEL[1]};
        letter-spacing: 0.02em;
        color: {TEXT_MUTED};
    }}

    .spis-chip-value {{
        margin: 0;
        font-size: 18px;
        font-weight: 600;
        color: {TEXT};
    }}

    .spis-section-heading {{
        margin: 0 0 12px 0;
        font-size: {TYPE_SECTION[0]}px;
        font-weight: {TYPE_SECTION[1]};
        color: {TEXT};
        line-height: 1.35;
    }}

    .spis-section-block {{
        margin-bottom: {SECTION_GAP}px;
    }}

    .spis-footer {{
        margin-top: {SECTION_GAP}px;
        font-size: {TYPE_CAPTION[0]}px;
        color: {TEXT_MUTED};
        line-height: 1.5;
    }}

    .spis-footer a {{
        color: {TEXT_MUTED};
        text-decoration: none;
    }}

    .spis-footer a:hover {{
        color: {PRIMARY};
        text-decoration: underline;
    }}

    @media (max-width: 768px) {{
        .spis-chips {{
            grid-template-columns: 1fr;
        }}
    }}
    """
