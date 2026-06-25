"""Verification gate for P3.5 soiling robustness analysis."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import pandas as pd

from spis import config
from spis.io import read_processed
from spis.robustness import (
    ROBUSTNESS_OUTPUT_NAME,
    attach_ground_pollution,
    build_daily_residual_frame,
    hac_regression,
    load_canakkale_ground_pollution,
    run_robustness_analysis,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")


def _hash_parquet(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_robustness() -> bool:
    """Run verifier checklist for robustness outputs."""
    failures: list[str] = []

    run_robustness_analysis()
    path = config.DATA_PROCESSED / f"{ROBUSTNESS_OUTPUT_NAME}.parquet"
    hash_first = _hash_parquet(path)
    run_robustness_analysis()
    hash_second = _hash_parquet(path)
    if hash_first != hash_second:
        failures.append("Reproducibility: soiling_robustness hash differs between runs")

    output = read_processed(ROBUSTNESS_OUTPUT_NAME)
    master = read_processed("master_daily")
    segments = read_processed("soiling_segments")

    if output[["clear_rate_pct_per_day", "coef"]].isna().all().all():
        failures.append("All headline metrics are null")

    daily = build_daily_residual_frame(master, segments)
    ground = load_canakkale_ground_pollution()
    daily, paired = attach_ground_pollution(daily, ground)
    if daily["pi_residual"].isna().any():
        failures.append("PI residuals contain imputed nulls")

    pm10 = output.loc[output["record_type"] == "pollution_pm10"].iloc[0]
    recomputed = hac_regression(daily, "pi_residual", ["pm10_accumulated"])
    coef = recomputed["coefficients"]["pm10_accumulated"]
    if abs(coef["coef"] - float(pm10["coef"])) > 1e-8:
        failures.append("Independent HAC recompute differs from stored PM10 coefficient")

    ground_row = output.loc[
        output["record_type"] == "pollution_ground_pm10_accumulated"
    ]
    if ground_row.empty:
        failures.append("Ground PM10 accumulated regression row missing")
    else:
        ground_stored = ground_row.iloc[0]
        ground_recomputed = hac_regression(
            daily, "pi_residual", ["ground_pm10_accumulated"]
        )
        ground_coef = ground_recomputed["coefficients"]["ground_pm10_accumulated"]
        if abs(ground_coef["coef"] - float(ground_stored["coef"])) > 1e-8:
            failures.append(
                "Independent HAC recompute differs from stored ground PM10 coefficient"
            )
        if not ground_recomputed.get("hac_se_wider_than_naive"):
            failures.append(
                "HAC SE sanity: ground PM10 expected wider SE than naive OLS"
            )
        if paired["ground_pm10_accumulated_pairs"] != int(ground_stored["n_obs"]):
            failures.append(
                "Ground PM10 paired-day count does not match regression n "
                f"({paired['ground_pm10_accumulated_pairs']} vs {ground_stored['n_obs']})"
            )

    if not recomputed.get("hac_se_wider_than_naive"):
        failures.append("HAC SE sanity: expected wider SE than naive OLS on daily residuals")

    verdict = output.loc[output["record_type"] == "p4_verdict"].iloc[0]
    if pd.isna(verdict["pollution_verdict"]):
        failures.append("Pollution verdict missing despite completed run")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Reproducibility: identical soiling_robustness hash")
    LOGGER.info("- Independent PM10 HAC coef matches stored value")
    if not ground_row.empty:
        LOGGER.info("- Independent ground PM10 HAC coef matches stored value")
        LOGGER.info(
            "- Ground PM10 accumulated paired days: %s",
            paired["ground_pm10_accumulated_pairs"],
        )
    LOGGER.info("- HAC SE wider than naive SE")
    LOGGER.info("- Pollution verdict: %s", verdict["pollution_verdict"])
    return True


def main() -> int:
    return 0 if verify_robustness() else 1


if __name__ == "__main__":
    sys.exit(main())
