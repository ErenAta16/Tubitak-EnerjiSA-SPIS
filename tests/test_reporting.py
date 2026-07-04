"""Smoke tests for P7 reporting outputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from spis import config
from spis.reporting import (
    FIGURE_MANIFEST,
    collect_headline_metrics,
    cross_check_metrics,
    run_reporting,
)

pytestmark = pytest.mark.integration


def test_reporting_figures_have_csv_companions() -> None:
    """Every manifest figure must have a CSV companion after reporting run."""
    run_reporting()
    for stem, _ in FIGURE_MANIFEST:
        assert (config.FIGURES / f"{stem}.png").exists()
        assert (config.FIGURES / f"{stem}.csv").exists()


def test_results_table_matches_parquets() -> None:
    """Headline metrics table must agree with processed parquets."""
    metrics = collect_headline_metrics()
    failures = cross_check_metrics(metrics)
    assert not failures, failures


def test_final_report_and_table_exist() -> None:
    """Reporting writes FINAL_REPORT and results table artifacts."""
    run_reporting()
    assert Path(config.REPORTS / "FINAL_REPORT.md").exists()
    assert Path(config.REPORTS / "FINAL_RESULTS_TABLE.csv").exists()
