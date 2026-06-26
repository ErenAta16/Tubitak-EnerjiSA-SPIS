"""User-facing table formatting for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.theme import format_decimal, format_integer

SEGMENT_DISPLAY_COLUMNS = {
    "segment_id": ("Segment", "Segment"),
    "date_start": ("Start", "Başlangıç"),
    "date_end": ("End", "Bitiş"),
    "n_clean_days": ("Clean days", "Temiz gün"),
    "soiling_rate_pct_per_day": ("Rate (%/day)", "Hız (%/gün)"),
    "soiling_rate_ci_lower": ("CI lower", "GA alt"),
    "soiling_rate_ci_upper": ("CI upper", "GA üst"),
    "recovery_pct": ("Recovery (%)", "Toparlanma (%)"),
    "low_confidence": ("Low confidence", "Düşük güven"),
}

_SKIP_COLS = {
    "Segment",
    "Start",
    "End",
    "Başlangıç",
    "Bitiş",
    "Low confidence",
    "Düşük güven",
}

_INTEGER_COLS = {"Clean days", "Temiz gün"}
_RECOVERY_COLS = {"Recovery (%)", "Toparlanma (%)"}
_RATE_COLS = {
    "Rate (%/day)",
    "Hız (%/gün)",
    "CI lower",
    "GA alt",
    "CI upper",
    "GA üst",
}

_TEXT_COLS = _SKIP_COLS | _RECOVERY_COLS


def format_segments_table(segments: pd.DataFrame | None, lang: str) -> pd.DataFrame | None:
    """Return a user-facing segment summary table."""
    if segments is None or segments.empty:
        return None
    cols = [c for c in SEGMENT_DISPLAY_COLUMNS if c in segments.columns]
    out = segments[cols].copy()
    rename = {
        col: SEGMENT_DISPLAY_COLUMNS[col][1 if lang == "TR" else 0] for col in cols
    }
    out = out.rename(columns=rename)
    for date_col in ("Start", "Bitiş", "End", "Başlangıç"):
        if date_col in out.columns:
            out[date_col] = pd.to_datetime(out[date_col]).dt.strftime("%Y-%m-%d")
    for col in out.columns:
        if col in _SKIP_COLS:
            continue
        if col in _INTEGER_COLS:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(0).astype("Int64")
        elif col in _RECOVERY_COLS:
            numeric = pd.to_numeric(out[col], errors="coerce")
            out[col] = numeric.apply(
                lambda value: "—"
                if pd.isna(value)
                else format_decimal(float(value), lang, decimals=2)
            )
        elif col in _RATE_COLS:
            numeric = pd.to_numeric(out[col], errors="coerce")
            out[col] = numeric.apply(
                lambda value: format_decimal(float(value), lang, decimals=2)
                if pd.notna(value)
                else value
            )
    return out


def segments_table_column_config(table: pd.DataFrame) -> dict[str, st.column_config.Column]:
    """Streamlit column_config for the segments table."""
    cfg: dict[str, st.column_config.Column] = {}
    for col in table.columns:
        if col in _TEXT_COLS:
            if col in _RECOVERY_COLS:
                cfg[col] = st.column_config.TextColumn(col, width="small")
            continue
        if col in _INTEGER_COLS:
            cfg[col] = st.column_config.NumberColumn(col, format="%d", width="small")
        elif col in _RATE_COLS:
            cfg[col] = st.column_config.TextColumn(col, width="medium")
        else:
            cfg[col] = st.column_config.TextColumn(col)
    return cfg


def format_data_preview(
    master: pd.DataFrame | None,
    *,
    n_rows: int = 14,
    lang: str,
) -> pd.DataFrame | None:
    """Return the most recent daily rows for tabular preview."""
    if master is None or master.empty:
        return None
    cols = ["date", "production", "irradiation"]
    has_pi = "pi" in master.columns
    has_pi_tc = "pi_temp_corrected" in master.columns
    if has_pi_tc:
        if has_pi and master["pi"].equals(master["pi_temp_corrected"]):
            cols.append("pi_temp_corrected")
        else:
            if has_pi:
                cols.append("pi")
            cols.append("pi_temp_corrected")
    elif has_pi:
        cols.append("pi")
    if "clearness_index" in master.columns:
        cols.append("clearness_index")
    if "days_since_wash" in master.columns:
        cols.append("days_since_wash")
    present = [c for c in cols if c in master.columns]
    preview = master.sort_values("date").tail(n_rows)[present].copy()
    labels = {
        "date": "Date" if lang == "EN" else "Tarih",
        "production": "Production (kWh)" if lang == "EN" else "Üretim (kWh)",
        "irradiation": "Irradiation (Wh/m²)" if lang == "EN" else "Işınım (Wh/m²)",
        "pi": "PI",
        "pi_temp_corrected": "PI (temp corr.)" if lang == "EN" else "PI (sıc. düz.)",
        "clearness_index": "Clearness" if lang == "EN" else "Berraklık",
        "days_since_wash": "Days since wash" if lang == "EN" else "Yıkamadan beri gün",
    }
    if (
        has_pi_tc
        and has_pi
        and master["pi"].equals(master["pi_temp_corrected"])
        and "pi_temp_corrected" in present
    ):
        labels["pi_temp_corrected"] = "PI"
    preview = preview.rename(columns={k: labels[k] for k in present})
    if "Date" in preview.columns or "Tarih" in preview.columns:
        date_name = "Date" if lang == "EN" else "Tarih"
        preview[date_name] = pd.to_datetime(preview[date_name]).dt.strftime("%Y-%m-%d")
    if lang == "TR":
        prod_col = "Üretim (kWh)"
        if prod_col in preview.columns:
            preview[prod_col] = preview[prod_col].apply(
                lambda v: format_integer(v, lang) if pd.notna(v) else v
            )
        days_col = "Yıkamadan beri gün"
        if days_col in preview.columns:
            preview[days_col] = preview[days_col].apply(
                lambda v: format_integer(v, lang) if pd.notna(v) else v
            )
        for pi_col in ("PI", "PI (sıc. düz.)"):
            if pi_col in preview.columns:
                preview[pi_col] = preview[pi_col].apply(
                    lambda v: format_decimal(float(v), lang, decimals=4)
                    if pd.notna(v)
                    else v
                )
    else:
        preview = preview.round(4)
    return preview


def data_preview_column_config(
    table: pd.DataFrame,
    lang: str,
) -> dict[str, st.column_config.Column]:
    """Streamlit column_config for the data preview table."""
    cfg: dict[str, st.column_config.Column] = {}
    date_col = "Date" if lang == "EN" else "Tarih"
    prod_col = "Production (kWh)" if lang == "EN" else "Üretim (kWh)"
    days_col = "Days since wash" if lang == "EN" else "Yıkamadan beri gün"
    for col in table.columns:
        if col == date_col:
            cfg[col] = st.column_config.TextColumn(col)
        elif col == prod_col or col == days_col:
            if lang == "TR":
                cfg[col] = st.column_config.TextColumn(col, width="medium")
            else:
                cfg[col] = st.column_config.NumberColumn(
                    col,
                    format="%d" if col == days_col else ",.0f",
                    width="medium",
                )
        elif col.startswith("PI") or col == "Clearness" or col == "Berraklık":
            if lang == "TR":
                cfg[col] = st.column_config.TextColumn(col, width="small")
            else:
                cfg[col] = st.column_config.NumberColumn(col, format="%.4f", width="small")
        elif "Irradiation" in col or "Işınım" in col:
            cfg[col] = st.column_config.NumberColumn(col, format=",.0f", width="medium")
        else:
            cfg[col] = st.column_config.TextColumn(col)
    return cfg


def format_comparison_table(table: pd.DataFrame | None, lang: str) -> pd.DataFrame | None:
    """Trim external-validation comparison export for display."""
    if table is None or table.empty:
        return None
    keep = [
        c
        for c in (
            "site_key",
            "array_number",
            "clear_sky_pooled_rate_pct_per_day",
            "clear_sky_ci_lower",
            "clear_sky_ci_upper",
            "pollution_significant",
        )
        if c in table.columns
    ]
    if not keep:
        return table.copy()
    out = table[keep].copy()
    labels = {
        "site_key": "Site" if lang == "EN" else "Santral",
        "array_number": "Array" if lang == "EN" else "Dizi",
        "clear_sky_pooled_rate_pct_per_day": "Rate (%/day)" if lang == "EN" else "Hız (%/gün)",
        "clear_sky_ci_lower": "CI lower" if lang == "EN" else "GA alt",
        "clear_sky_ci_upper": "CI upper" if lang == "EN" else "GA üst",
        "pollution_significant": "Pollution sig." if lang == "EN" else "Kirlilik anlamlı",
    }
    out = out.rename(columns=labels)
    rate_cols = [
        labels["clear_sky_pooled_rate_pct_per_day"],
        labels["clear_sky_ci_lower"],
        labels["clear_sky_ci_upper"],
    ]
    for col in rate_cols:
        if col in out.columns:
            out[col] = out[col].apply(
                lambda v: format_decimal(float(v), lang, decimals=2) if pd.notna(v) else v
            )
    return out
