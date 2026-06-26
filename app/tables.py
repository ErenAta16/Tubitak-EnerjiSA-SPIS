"""User-facing table formatting for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd

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
    numeric_cols = [c for c in out.columns if c not in _SKIP_COLS]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(4)
    return out


def format_data_preview(
    master: pd.DataFrame | None,
    *,
    n_rows: int = 14,
    lang: str,
) -> pd.DataFrame | None:
    """Return the most recent daily rows for tabular preview."""
    if master is None or master.empty:
        return None
    cols = ["date", "production", "irradiation", "pi"]
    if "pi_temp_corrected" in master.columns:
        cols.append("pi_temp_corrected")
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
    preview = preview.rename(columns={k: labels[k] for k in present})
    if "Date" in preview.columns or "Tarih" in preview.columns:
        date_name = "Date" if lang == "EN" else "Tarih"
        preview[date_name] = pd.to_datetime(preview[date_name]).dt.strftime("%Y-%m-%d")
    return preview.round(4)


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
    return out.rename(columns=labels).round(4)
