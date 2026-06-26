"""Built-in sample upload data for the Streamlit UI."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pandas as pd

from app.models import SAMPLE_UPLOAD_KEY, DashboardSnapshot
from app.upload_analysis import sample_upload_csv_bytes


def load_sample_upload_snapshot() -> DashboardSnapshot:
    """Build a dashboard snapshot from the bundled sample upload CSV."""
    # Lazy import avoids circular imports during Streamlit module reload.
    from app.ui_logic import load_upload_dashboard_snapshot

    frame = pd.read_csv(BytesIO(sample_upload_csv_bytes()))
    snapshot = load_upload_dashboard_snapshot(frame)
    if not snapshot.available:
        return snapshot
    return replace(
        snapshot,
        site_key=SAMPLE_UPLOAD_KEY,
        site_name="Sample CSV (built-in)",
        message=(
            "Built-in sample upload (120 days, synthetic soiling ~0.15%/day). "
            "Upload your own CSV in the sidebar to replace this preview."
        ),
    )
