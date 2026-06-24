"""Verification gate for P7 consolidated reporting."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

from spis import config
from spis.reporting import (
    FIGURE_MANIFEST,
    FINAL_REPORT,
    RESULTS_TABLE_CSV,
    check_figure_companions,
    check_no_overclaim,
    collect_headline_metrics,
    cross_check_metrics,
    run_reporting,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_report() -> bool:
    """Run verifier checklist for P7 reporting outputs."""
    failures: list[str] = []

    run_reporting()
    table_path = config.REPORTS / RESULTS_TABLE_CSV
    report_path = config.REPORTS / FINAL_REPORT
    hash_table_first = _hash_file(table_path)
    hash_report_first = _hash_file(report_path)
    run_reporting()
    if _hash_file(table_path) != hash_table_first:
        failures.append("Reproducibility: FINAL_RESULTS_TABLE.csv hash differs")
    if _hash_file(report_path) != hash_report_first:
        failures.append("Reproducibility: FINAL_REPORT.md hash differs")

    metrics = collect_headline_metrics()
    failures.extend(cross_check_metrics(metrics))
    failures.extend(check_figure_companions())
    failures.extend(check_no_overclaim())

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Reproducibility: identical report artifacts")
    LOGGER.info("- Cross-check: results table matches parquets")
    LOGGER.info("- Figures: %s PNG+CSV pairs present", len(FIGURE_MANIFEST))
    return True


def main() -> int:
    return 0 if verify_report() else 1


if __name__ == "__main__":
    sys.exit(main())
