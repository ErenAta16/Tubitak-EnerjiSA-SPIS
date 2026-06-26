"""Verifier gate for P16 external validation (DKASC Alice Springs)."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import numpy as np

from spis import config
from spis.clean import MASTER_OUTPUT_NAME, build_master_table
from spis.external_validation import (
    CANAKKALE_SITE_KEY,
    CANONICAL_CI_METHOD,
    EXTERNAL_VALIDATION_OUTPUT,
    FORBIDDEN_OVERCLAIM_PHRASES,
    run_external_validation,
)
from spis.io import read_processed
from spis.robustness import ROBUSTNESS_OUTPUT_NAME
from spis.sites import SITES, get_site

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")

CANAKKALE_MASTER_HASH = "e1574bac5420e007ac3c04b35ab399d9c0daa089ac3490e210df8807b70ddcc2"
CANONICAL_CANAKKALE_RATE = -0.1247
CANONICAL_CANAKKALE_CI = (-0.186, -0.064)


def _hash_parquet(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_external_validation() -> bool:
    """Run P16 verifier checklist."""
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
        text = report_path.read_text(encoding="utf-8").lower()
        for phrase in (
            "cleaning-inference sensitivity",
            "kw-scale research-array caveat",
            "verdict",
            "daily energy channel selection",
            "canonical ci method",
            "inconclusive",
        ):
            if phrase not in text:
                failures.append(f"EXTERNAL_VALIDATION.md missing section: {phrase}")
        for phrase in FORBIDDEN_OVERCLAIM_PHRASES:
            if phrase.lower() in text:
                failures.append(f"EXTERNAL_VALIDATION.md contains forbidden overclaim: {phrase}")

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
        if (table["ci_method"] != CANONICAL_CI_METHOD).any():
            failures.append("Comparison table CI method not canonical for all rows")
        if "verdict" not in result or not result["verdict"]:
            failures.append("Verdict not reported")
        if "inconclusive" not in result["verdict"].lower():
            failures.append("Verdict must state INCONCLUSIVE primary conclusion")

        can_row = table.loc[table["site_key"] == CANAKKALE_SITE_KEY].iloc[0]
        if not (
            abs(float(can_row["clear_sky_pooled_rate_pct_per_day"]) - CANONICAL_CANAKKALE_RATE)
            < 1e-3
        ):
            failures.append("Canakkale rate does not match canonical -0.125 %/day")
        can_lo = float(can_row["clear_sky_ci_lower"])
        can_hi = float(can_row["clear_sky_ci_upper"])
        if not (
            abs(can_lo - CANONICAL_CANAKKALE_CI[0]) < 0.002
            and abs(can_hi - CANONICAL_CANAKKALE_CI[1]) < 0.002
        ):
            failures.append(
                f"Canakkale CI [{can_lo:.4f}, {can_hi:.4f}] != canonical "
                f"{CANONICAL_CANAKKALE_CI}"
            )

        dkasc_rows = table.loc[table["site_key"] == "alice_springs"]
        if len(dkasc_rows) < 4:
            failures.append("Expected at least 4 DKASC array rows in comparison table")

        sensitivity = result.get("sensitivity")
        if sensitivity is None or sensitivity.empty:
            failures.append("Cleaning sensitivity table missing")
        elif set(sensitivity["preset"]) != set(config.INFERRED_CLEANING_PRESETS):
            failures.append("Cleaning sensitivity missing preset rows")

        robustness = read_processed(ROBUSTNESS_OUTPUT_NAME, site_key=CANAKKALE_SITE_KEY)
        verdict_row = robustness.loc[robustness["record_type"] == "p4_verdict"].iloc[0]
        if not np.isclose(
            float(verdict_row["recommended_rate_pct_per_day"]),
            CANONICAL_CANAKKALE_RATE,
            rtol=1e-4,
            atol=1e-4,
        ):
            failures.append("Canakkale p4_verdict rate changed")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Canakkale master hash unchanged: %s", hash_after[:16])
    if result is not None:
        LOGGER.info("- Verdict: %s", result["verdict"][:200])
    return True


def main() -> int:
    return 0 if verify_external_validation() else 1


if __name__ == "__main__":
    sys.exit(main())
