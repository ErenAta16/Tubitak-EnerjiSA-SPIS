"""Independent verification gate for the P2 master table build."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import pandas as pd

from spis import config
from spis.clean import MASTER_OUTPUT_NAME, build_master_table
from spis.io import read_processed

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")


def _hash_parquet(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_clean() -> bool:
    """Run verifier checklist for the master table build."""
    failures: list[str] = []

    _, meta_first = build_master_table()
    path = config.DATA_PROCESSED / f"{MASTER_OUTPUT_NAME}.parquet"
    hash_first = _hash_parquet(path)
    _, meta_second = build_master_table()
    hash_second = _hash_parquet(path)
    if hash_first != hash_second:
        failures.append("Reproducibility: master Parquet hash differs between two runs")

    master = read_processed(MASTER_OUTPUT_NAME)
    expected_rows = len(
        pd.date_range(config.IRRADIANCE_START_DATE, config.IRRADIANCE_END_DATE, freq="D")
    )
    if len(master) != expected_rows:
        failures.append(f"Row count {len(master)} != expected spine {expected_rows}")

    recomputed_pi = master["production"] / master["irradiation"]
    if (recomputed_pi - master["pi"]).abs().max() > 1e-6:
        failures.append("Independent PI recompute exceeds 1e-6 tolerance")

    delta_t = master["cell_temp_c"] - config.STC_REF_TEMP_C
    recomputed_pi_t = master["pi"] / (1.0 + config.MODULE_PMAX_TEMP_COEFF * delta_t)
    if (recomputed_pi_t - master["pi_temp_corrected"]).abs().max() > 1e-6:
        failures.append("Independent temperature-corrected PI recompute exceeds 1e-6")

    if master[["production", "irradiation", "pi"]].isna().any().any():
        failures.append("Core SCADA columns contain imputed nulls")

    cams_cols = ["pm10", "pm2_5", "dust", "aerosol_optical_depth"]
    if (master[cams_cols].notna().sum() == 0).any():
        failures.append("CAMS columns are entirely null (unexpected given API coverage)")

    if (master["nasa_t2m"] < -30).any() or (master["nasa_t2m"] > 50).any():
        failures.append("NASA T2M outside plausible ambient range")

    if meta_first["filter_counts"]["is_clean_observation"] <= 0:
        failures.append("No clean observation days remain after filtering")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Reproducibility: identical master Parquet hash on two runs")
    LOGGER.info("- Row accounting: %s", meta_first["filter_counts"])
    LOGGER.info("- Independent PI and temperature correction recompute agree to 1e-6")
    LOGGER.info("- CAMS coverage: %s", meta_first["cams_meta"]["date_span"])
    LOGGER.info(
        "- Clean observation days: %s",
        meta_first["filter_counts"]["is_clean_observation"],
    )
    return True


def main() -> int:
    return 0 if verify_clean() else 1


if __name__ == "__main__":
    sys.exit(main())
