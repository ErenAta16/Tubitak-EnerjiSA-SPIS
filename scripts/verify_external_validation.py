"""Verifier gate for P14 external validation (DKASC Alice Springs)."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

from spis import config
from spis.clean import MASTER_OUTPUT_NAME, build_master_table
from spis.external_validation import (
    EXTERNAL_VALIDATION_OUTPUT,
    run_external_validation,
)
from spis.sites import SITES, get_site

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")

CANAKKALE_MASTER_HASH = "bd1b07716649028b016f26d381216c6553c0ccc370ff2bd0cb88b61586c2c552"


def _hash_parquet(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_external_validation() -> bool:
    """Run P14 verifier checklist."""
    failures: list[str] = []

    if "alice_springs" not in SITES:
        failures.append("SITES registry missing alice_springs")
    alice = get_site("alice_springs")
    if not alice.operational_data_available:
        failures.append("alice_springs operational_data_available must be True")
    if alice.lat != -23.762 or alice.lon != 133.874:
        failures.append("alice_springs coordinates incorrect")

    master_path = config.DATA_PROCESSED / f"{MASTER_OUTPUT_NAME}.parquet"
    build_master_table(site_key="canakkale")
    hash_after = _hash_parquet(master_path)
    build_master_table(site_key="canakkale")
    hash_rerun = _hash_parquet(master_path)
    if hash_after != CANAKKALE_MASTER_HASH:
        failures.append(f"Canakkale master hash {hash_after} != baseline {CANAKKALE_MASTER_HASH}")
    if hash_after != hash_rerun:
        failures.append("Canakkale master hash not reproducible across two builds")

    try:
        result = run_external_validation(force_refresh=False)
    except FileNotFoundError as exc:
        failures.append(str(exc))
        result = None

    report_path = config.REPORTS / "EXTERNAL_VALIDATION.md"
    if not report_path.exists():
        failures.append("EXTERNAL_VALIDATION.md missing")
    else:
        text = report_path.read_text(encoding="utf-8")
        for phrase in (
            "Cleaning-inference caveat",
            "kW-scale research-array caveat",
            "Verdict",
            "column mapping",
        ):
            if phrase not in text:
                failures.append(f"EXTERNAL_VALIDATION.md missing section: {phrase}")

    out_path = config.DATA_PROCESSED / "alice_springs" / f"{EXTERNAL_VALIDATION_OUTPUT}.parquet"
    if result is not None and not out_path.exists():
        failures.append("external_validation.parquet missing for alice_springs")

    for stem in (
        "external_validation_soiling_rate_comparison",
        "external_validation_alice_dust_vs_residual",
    ):
        png = config.FIGURES / f"{stem}.png"
        csv = config.FIGURES / f"{stem}.csv"
        if not png.exists():
            failures.append(f"Missing figure {png.name}")
        if not csv.exists():
            failures.append(f"Missing figure CSV {csv.name}")

    if result is not None:
        table = result["table"]
        if table["clear_sky_pooled_rate_pct_per_day"].isna().any():
            failures.append("Comparison table contains null clear-sky rates")
        if "verdict" not in result or not result["verdict"]:
            failures.append("Verdict not reported")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Canakkale master hash unchanged: %s", hash_after[:16])
    if result is not None:
        LOGGER.info("- Verdict: %s", result["verdict"][:160])
    return True


def main() -> int:
    return 0 if verify_external_validation() else 1


if __name__ == "__main__":
    sys.exit(main())
