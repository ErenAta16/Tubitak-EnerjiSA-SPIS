"""CLI entry point for the SPIS analysis pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable

LOGGER = logging.getLogger(__name__)

STAGES: tuple[str, ...] = (
    "ingest",
    "clean",
    "soiling",
    "robustness",
    "optimize",
    "ml",
    "report",
    "site_comparison",
    "inverter_anomaly",
    "field_visit",
    "external_validation",
    "pvdaq_validation",
    "method_benchmark",
)

ALL_STAGES: tuple[str, ...] = (
    "ingest",
    "clean",
    "soiling",
    "robustness",
    "optimize",
    "ml",
    "report",
    "site_comparison",
    "inverter_anomaly",
    "field_visit",
    "external_validation",
    "pvdaq_validation",
    "method_benchmark",
)

STAGE_PHASES: dict[str, str] = {
    "ingest": "P1",
    "clean": "P2",
    "soiling": "P3",
    "robustness": "P3.5",
    "optimize": "P4",
    "ml": "P5",
    "report": "P7",
    "site_comparison": "P9-B",
    "inverter_anomaly": "P6",
    "field_visit": "P8",
    "external_validation": "P14",
    "pvdaq_validation": "P17-A",
    "method_benchmark": "P17-B",
}


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


def stage_robustness() -> None:
    """Run pollution-aware soiling robustness analysis."""
    from spis.robustness import run_robustness_analysis

    run_robustness_analysis()


def stage_optimize() -> None:
    """Optimize washing schedule against cost and yield."""
    from spis.optimize import run_optimization_analysis

    run_optimization_analysis()


def stage_ml() -> None:
    """Train and evaluate ML models for underperformance detection."""
    from spis.ml import run_ml_analysis

    run_ml_analysis()


def stage_report() -> None:
    """Render figures and the written report."""
    from spis.reporting import run_reporting

    run_reporting()


def stage_site_comparison() -> None:
    """Run two-site environmental comparison and ground-vs-CAMS validation."""
    from spis.site_comparison import run_site_comparison

    run_site_comparison()


def stage_inverter_anomaly() -> None:
    """Descriptive inverter relative-performance screening."""
    from spis.inverter_anomaly import run_inverter_anomaly_analysis

    run_inverter_anomaly_analysis()


def stage_field_visit() -> None:
    """Build the on-site field visit support pack."""
    from spis.field_visit import run_field_visit_pack

    run_field_visit_pack()


def stage_external_validation() -> None:
    """Run DKASC Alice Springs external validation against Canakkale."""
    from spis.external_validation import run_external_validation

    run_external_validation()


def stage_pvdaq_validation() -> None:
    """Run PVDAQ 2107 utility-scale external validation."""
    from spis.pvdaq_validation import run_pvdaq_validation

    run_pvdaq_validation()


def stage_method_benchmark() -> None:
    """Benchmark SPIS vs RdTools SRR on Canakkale and PVDAQ 2107."""
    from spis.method_benchmark import run_method_benchmark

    run_method_benchmark()


STAGE_HANDLERS: dict[str, Callable[[], None]] = {
    "ingest": stage_ingest,
    "clean": stage_clean,
    "soiling": stage_soiling,
    "robustness": stage_robustness,
    "optimize": stage_optimize,
    "ml": stage_ml,
    "report": stage_report,
    "site_comparison": stage_site_comparison,
    "inverter_anomaly": stage_inverter_anomaly,
    "field_visit": stage_field_visit,
    "external_validation": stage_external_validation,
    "pvdaq_validation": stage_pvdaq_validation,
    "method_benchmark": stage_method_benchmark,
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
        choices=(*STAGES, "all"),
        required=True,
        help="Pipeline stage to run, or 'all' for the full reproducible chain.",
    )
    return parser.parse_args(argv)


def run_stage(stage: str) -> None:
    """Dispatch a single pipeline stage."""
    if stage not in STAGE_HANDLERS:
        raise KeyError(f"Unknown stage {stage!r}")
    LOGGER.info("Starting pipeline stage: %s (%s)", stage, STAGE_PHASES[stage])
    STAGE_HANDLERS[stage]()


def run_all_stages() -> None:
    """Run the full reproducible SPIS pipeline (ingest through field_visit)."""
    for stage in ALL_STAGES:
        run_stage(stage)


def main(argv: list[str] | None = None) -> None:
    """Configure logging and dispatch the requested pipeline stage."""
    _configure_logging()
    args = parse_args(argv)
    if args.stage == "all":
        run_all_stages()
        return
    run_stage(args.stage)


if __name__ == "__main__":
    try:
        main()
    except NotImplementedError:
        LOGGER.exception("Pipeline stage is not yet implemented")
        sys.exit(1)
