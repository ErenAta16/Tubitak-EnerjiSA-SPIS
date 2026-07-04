"""Verification gate for P4 washing-schedule optimization."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

from spis import config
from spis.data_sources.epias_ptf import load_ptf_central_price
from spis.io import read_processed
from spis.optimize import (
    OPTIMIZE_OUTPUT_NAME,
    build_sensitivity_sweep,
    load_soiling_rate_band,
    optimal_interval_closed_form,
    optimal_interval_grid_search,
    run_optimization_analysis,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")


def _hash_parquet(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_optimize() -> bool:
    """Run verifier checklist for P4 optimization outputs."""
    failures: list[str] = []

    run_optimization_analysis()
    path = config.DATA_PROCESSED / f"{OPTIMIZE_OUTPUT_NAME}.parquet"
    hash_first = _hash_parquet(path)
    run_optimization_analysis()
    hash_second = _hash_parquet(path)
    if hash_first != hash_second:
        failures.append("Reproducibility: washing_optimization hash differs between runs")

    output = read_processed(OPTIMIZE_OUTPUT_NAME)
    assumptions = output.loc[output["record_type"] == "assumption"]
    real = output.loc[output["record_type"] == "real_2023"]
    if assumptions.empty:
        failures.append("No assumption rows logged")
    if real.empty:
        failures.append("No real_2023 central PTF row logged")
    if (assumptions["source"] == "ASSUMED").sum() < 3:
        failures.append("Expected ASSUMED economic inputs to be logged explicitly")

    sweep = output.loc[output["record_type"] == "sweep_point"]
    if not (sweep["price_source"] == "assumption").all():
        failures.append("Sweep grid prices must be logged as assumption")

    max_delta = float(sweep["closed_grid_delta_days"].max())
    if max_delta > config.OPTIMIZE_CLOSED_FORM_TOLERANCE_DAYS:
        failures.append(
            f"Closed-form vs grid T* delta {max_delta:.2f} exceeds tolerance "
            f"{config.OPTIMIZE_CLOSED_FORM_TOLERANCE_DAYS}"
        )

    central = output.loc[output["record_type"] == "central_estimate"].iloc[0]
    if central.get("price_source") != "real_2023":
        failures.append("Central estimate must use price_source=real_2023")
    t_lo = float(central["t_star_ci_low_days"])
    t_pt = float(central["t_star_days"])
    t_hi = float(central["t_star_ci_high_days"])
    if not (t_lo <= t_pt <= t_hi):
        failures.append("Central T* not within rate CI band ordering")

    robustness = read_processed("soiling_robustness")
    band = load_soiling_rate_band(robustness)
    pooled = float(output.loc[output["segment_id"] == -1, "clean_baseline_kwh_day"].iloc[0])
    central_price, _ = load_ptf_central_price()
    recomputed = optimal_interval_closed_form(
        config.WASH_COST_TL_CENTRAL,
        pooled,
        central_price,
        band.point,
    )
    if abs(recomputed - t_pt) > 1e-6:
        failures.append("Independent closed-form T* differs from stored central estimate")
    if abs(float(central["price_tl_mwh"]) - central_price) > 1e-6:
        failures.append("Central price does not match ingested 2023 annual mean")

    cheap = build_sensitivity_sweep(pooled, band, wash_costs=(50_000.0,), prices=(3500.0,))
    costly = build_sensitivity_sweep(pooled, band, wash_costs=(300_000.0,), prices=(1000.0,))
    t_cheap = float(cheap.loc[cheap["rate_scenario"] == "point", "t_star_closed_form_days"].iloc[0])
    t_costly = float(
        costly.loc[costly["rate_scenario"] == "point", "t_star_closed_form_days"].iloc[0]
    )
    if not (t_cheap < t_costly):
        failures.append("Monotonicity: cheaper wash/higher price should shorten T*")

    zero_grid, _ = optimal_interval_grid_search(150_000.0, pooled, central_price, 0.0)
    if zero_grid != float(config.OPTIMIZE_GRID_MAX_DAYS):
        failures.append("Zero-rate edge case not handled")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Reproducibility: identical washing_optimization hash")
    LOGGER.info("- Closed-form vs grid max delta: %.2f days", max_delta)
    LOGGER.info(
        "- Central T*=%.0f days (CI %.0f..%.0f) at real 2023 PTF %.2f TL/MWh",
        t_pt,
        t_lo,
        t_hi,
        central_price,
    )
    return True


def main() -> int:
    return 0 if verify_optimize() else 1


if __name__ == "__main__":
    sys.exit(main())
