"""Bundled public real-site examples for the Streamlit dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from spis import config
from spis.optimize import (
    SoilingRateBand,
    compute_clean_baseline_energy,
    load_soiling_rate_band,
)
from spis.robustness import ROBUSTNESS_OUTPUT_NAME
from spis.soiling import MASTER_INPUT_NAME, SOILING_OUTPUT_NAME

PVDAQ_2107_KEY = "pvdaq_2107"
PVDAQ_2107_NAME = "PVDAQ 2107 (public site)"
DKASC_KEY = "alice_springs"
DKASC_NAME = "DKASC array 14 (public site)"
PUBLIC_EXAMPLE_KEYS = (PVDAQ_2107_KEY, DKASC_KEY)
PUBLIC_EXAMPLES_DIR = config.ROOT / "data" / "examples"


def public_example_dir(site_key: str) -> Path:
    """Return the committed artifact directory for one public example."""
    if site_key == PVDAQ_2107_KEY:
        return PUBLIC_EXAMPLES_DIR / "pvdaq_2107"
    if site_key == DKASC_KEY:
        return PUBLIC_EXAMPLES_DIR / "dkasc"
    raise KeyError(f"Unknown public example site: {site_key}")


def public_artifact_path(site_key: str, name: str) -> Path:
    """Return one bundled public-example Parquet path."""
    return public_example_dir(site_key) / f"{name}.parquet"


def public_example_available(site_key: str) -> bool:
    """Return True when all dashboard artifacts are bundled for a public site."""
    if site_key not in PUBLIC_EXAMPLE_KEYS:
        return False
    return all(
        public_artifact_path(site_key, name).exists()
        for name in (MASTER_INPUT_NAME, SOILING_OUTPUT_NAME, ROBUSTNESS_OUTPUT_NAME)
    )


def load_public_headline_metrics(site_key: str) -> dict[str, Any]:
    """Load public-site headline, optimizer, and provenance-safe display metrics."""
    robustness = pd.read_parquet(public_artifact_path(site_key, ROBUSTNESS_OUTPUT_NAME))
    verdict = robustness.loc[robustness["record_type"] == "p4_verdict"].iloc[0]
    master = pd.read_parquet(public_artifact_path(site_key, MASTER_INPUT_NAME))
    segments = pd.read_parquet(public_artifact_path(site_key, SOILING_OUTPUT_NAME))
    baseline = compute_clean_baseline_energy(master, segments)
    rate = float(verdict["recommended_rate_pct_per_day"])
    half_width = float(verdict["recommended_uncertainty_half_width"])
    rate_band: SoilingRateBand = load_soiling_rate_band(robustness)
    return {
        "clear_sky_rate_pct_per_day": rate,
        "clear_sky_ci_lower": rate - half_width,
        "clear_sky_ci_upper": rate + half_width,
        "pollution_verdict": str(verdict["pollution_verdict"]),
        "daily_energy_kwh": float(baseline["clean_baseline_kwh_day"].median()),
        "rate_band": rate_band,
        "master": master,
        "segments": segments,
    }
