"""CLI entry point for the SPIS analysis pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable

LOGGER = logging.getLogger(__name__)

STAGES: tuple[str, ...] = ("ingest", "clean", "soiling", "optimize", "ml", "report")

STAGE_PHASES: dict[str, str] = {
    "ingest": "P1",
    "clean": "P2",
    "soiling": "P3",
    "optimize": "P4",
    "ml": "P5",
    "report": "P6",
}


def _not_implemented(stage: str) -> None:
    phase = STAGE_PHASES[stage]
    raise NotImplementedError(f"Stage '{stage}' is not implemented ({phase}).")


def stage_ingest() -> None:
    """Load raw inputs into typed interim frames."""
    from spis.ingest import ingest_all

    ingest_all()


def stage_clean() -> None:
    """Clean, align, and validate daily production and irradiance series."""
    from spis.clean import build_master_table

    build_master_table()


def stage_soiling() -> None:
    """Fit soiling rates between washing events."""
    from spis.soiling import run_soiling_analysis

    run_soiling_analysis()


def stage_optimize() -> None:
    """Optimize washing schedule against cost and yield."""
    _not_implemented("optimize")


def stage_ml() -> None:
    """Train and evaluate ML models for underperformance detection."""
    _not_implemented("ml")


def stage_report() -> None:
    """Render figures and the written report."""
    _not_implemented("report")


STAGE_HANDLERS: dict[str, Callable[[], None]] = {
    "ingest": stage_ingest,
    "clean": stage_clean,
    "soiling": stage_soiling,
    "optimize": stage_optimize,
    "ml": stage_ml,
    "report": stage_report,
}


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Run one stage of the SPIS pipeline.")
    parser.add_argument(
        "--stage",
        choices=STAGES,
        required=True,
        help="Pipeline stage to run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Configure logging and dispatch the requested pipeline stage."""
    _configure_logging()
    args = parse_args(argv)
    LOGGER.info("Starting pipeline stage: %s", args.stage)
    STAGE_HANDLERS[args.stage]()


if __name__ == "__main__":
    try:
        main()
    except NotImplementedError:
        LOGGER.exception("Pipeline stage is not yet implemented")
        sys.exit(1)
