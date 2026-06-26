"""Shared data models for the SPIS Streamlit UI."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from spis.optimize import SoilingRateBand

SAMPLE_UPLOAD_KEY = "sample_upload"


@dataclass(frozen=True)
class DashboardSnapshot:
    """Bundle of headline metrics for one site."""

    site_key: str
    site_name: str
    available: bool
    message: str
    clear_sky_rate_pct_per_day: float | None
    clear_sky_ci_lower: float | None
    clear_sky_ci_upper: float | None
    pollution_verdict: str
    daily_energy_kwh: float | None
    rate_band: SoilingRateBand | None
    master: pd.DataFrame | None
    segments: pd.DataFrame | None = None
    comparison_table: pd.DataFrame | None = None
    plain_language_soiling: str = ""

    def segment_count(self) -> int:
        """Return the number of fitted wash segments (0 when unavailable)."""
        segments = getattr(self, "segments", None)
        return len(segments) if segments is not None else 0

    def segments_frame(self) -> pd.DataFrame | None:
        """Return segment table if present (safe for hot-reloaded Streamlit sessions)."""
        return getattr(self, "segments", None)
