"""P8 field-visit support pack tying P4, P6, and site context."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from spis import config
from spis.inverter_anomaly import (
    INVERTER_ANOMALY_OUTPUT,
    UNDERPERFORMER_MEDIAN_THRESHOLD,
    run_inverter_anomaly_analysis,
)
from spis.io import read_processed
from spis.optimize import OPTIMIZE_OUTPUT_NAME
from spis.sites import SITES, get_site, provisional_label

LOGGER = logging.getLogger(__name__)

FIELD_VISIT_PACK_PATH = config.REPORTS / "FIELD_VISIT_PACK.md"


def _load_inverter_summary() -> pd.DataFrame:
    path = config.DATA_PROCESSED / f"{INVERTER_ANOMALY_OUTPUT}.parquet"
    if not path.exists():
        run_inverter_anomaly_analysis()
    frame = read_processed(INVERTER_ANOMALY_OUTPUT)
    return frame.loc[frame["record_type"] == "inverter_summary"].copy()


def _load_washing_context() -> dict[str, Any]:
    opt_path = config.DATA_PROCESSED / f"{OPTIMIZE_OUTPUT_NAME}.parquet"
    if not opt_path.exists():
        return {"t_star_days": None, "rate_ci": None, "note": "P4 optimization not run locally"}
    opt = read_processed(OPTIMIZE_OUTPUT_NAME)
    central = opt.loc[opt["record_type"] == "central_estimate"].iloc[0]
    return {
        "t_star_days": float(central["t_star_days"]),
        "t_star_ci_low": float(central["t_star_ci_low_days"]),
        "t_star_ci_high": float(central["t_star_ci_high_days"]),
        "note": "Model T* uses the clear-sky pooled soiling rate and real 2023 PTF.",
    }


def _site_coordinate_label(site_key: str, site) -> str:
    """Format coordinates for reports without disclosing precise Canakkale location."""
    if site_key == "canakkale" and config.PLANT_COORD_SOURCE != "env":
        return (
            "coarse public default (set PLANT_LAT/PLANT_LON in .env for precise location)"
        )
    return f"lat={site.lat}, lon={site.lon}"


def build_field_visit_pack() -> Path:
    """Write FIELD_VISIT_PACK.md for Canakkale (Balikesir checklist when data arrives)."""
    inverter_summary = _load_inverter_summary()
    wash = _load_washing_context()
    bal = get_site("balikesir")

    inspect_first = inverter_summary.sort_values("median_relative").head(3)
    flagged = inverter_summary.loc[inverter_summary["candidate_underperformer"]]

    lines = [
        "# Field visit support pack",
        "",
        "Checklist for on-site verification at Canakkale Hybrid GES. "
        "Balikesir section is a placeholder until Enerjisa supplies operational data.",
        "",
        "## Priority field action — reference irradiance sensor",
        "",
        "**CRITICAL:** Inspect and clean the **reference irradiance sensor** and verify "
        "whether it soils at the same rate as the PV modules. SPIS soiling rates are a "
        "**lower bound** when the sensor co-soils with modules; confirming sensor condition "
        "directly bounds how conservative the modeled wash interval is.",
        "",
        "- [ ] Visual inspection of reference sensor glass/soiling",
        "- [ ] Compare sensor reading to a clean handheld reference on a clear day",
        "- [ ] Log last sensor cleaning date; photograph condition",
        "- [ ] Note whether sensor is co-located with soiled module strings",
        "",
        "## Canakkale — inverter inspection priorities (descriptive ranking)",
        "",
        f"Threshold: median relative performance < {UNDERPERFORMER_MEDIAN_THRESHOLD:.2f} "
        "vs daily peer median (not fault diagnosis).",
        "",
        "### Inspect first (lowest median relative performance)",
        "",
    ]
    for _, row in inspect_first.iterrows():
        flag = " **candidate underperformer**" if row["candidate_underperformer"] else ""
        lines.append(
            f"- [ ] **{row['inverter']}**: expected peer median = 1.00, "
            f"observed median = {row['median_relative']:.3f}{flag}"
        )

    lines.extend(["", "### All flagged candidate underperformers", ""])
    if flagged.empty:
        lines.append("- None at documented thresholds.")
    else:
        for _, row in flagged.iterrows():
            lines.append(
                f"- [ ] **{row['inverter']}** median relative {row['median_relative']:.3f}"
            )

    lines.extend(
        [
            "",
            "## Canakkale — soiling / washing context",
            "",
        ]
    )
    if wash["t_star_days"] is None:
        lines.append(f"- {wash['note']}")
    else:
        lines.extend(
            [
                f"- Model-optimal wash interval **T* = {wash['t_star_days']:.0f} days** "
                f"(rate CI band {wash['t_star_ci_low']:.0f}..{wash['t_star_ci_high']:.0f} days).",
                "- Compare actual inter-wash gaps in the washing log to T*.",
                "- Remember: true soiling may exceed model if the reference sensor co-soils.",
            ]
        )

    lines.extend(
        [
            "",
            "## Canakkale — general checklist",
            "",
            "- [ ] Confirm washing method used on last event matches log (brush vs robot).",
            "- [ ] Check for string/feeder imbalance between EFLATUN and HIPOKRAT.",
            "- [ ] Review inverter fault alarms for units ranked below peer median.",
            "- [ ] Note any curtailment or grid events during low relative-performance days.",
            "",
            f"## Balikesir — pending ({provisional_label('balikesir')})",
            "",
            f"- Coordinates: **PROVISIONAL** ({bal.lat}, {bal.lon}) — {bal.coordinates_note}",
            "- Environmental comparison only until operational data supplied.",
            "",
            "### Checklist when Balikesir data is available",
            "",
            "- [ ] Confirm coordinates from KMZ / as-built layout",
            "- [ ] Collect production + irradiance workbook (Canakkale-equivalent schema)",
            "- [ ] Collect downtime log and washing dates",
            "- [ ] Repeat reference irradiance sensor soiling check",
            "- [ ] Run full SPIS pipeline with `operational_data_available=True`",
            "",
            "## Site registry",
            "",
        ]
    )
    for key, site in SITES.items():
        lines.append(
            f"- **{key}** ({site.name}): {_site_coordinate_label(key, site)}, "
            f"panel={site.panel_class}, operational_data={site.operational_data_available}, "
            f"status={provisional_label(key)}"
        )

    FIELD_VISIT_PACK_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", FIELD_VISIT_PACK_PATH)
    return FIELD_VISIT_PACK_PATH


def run_field_visit_pack() -> Path:
    """Public entry point for Phase D."""
    return build_field_visit_pack()
