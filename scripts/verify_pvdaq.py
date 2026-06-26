"""Verifier gate for P17 PVDAQ utility validation and RdTools benchmark."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import numpy as np

from spis import config
from spis.clean import MASTER_OUTPUT_NAME, build_master_table
from spis.external_validation import CANONICAL_CI_METHOD
from spis.io import read_processed
from spis.method_benchmark import run_method_benchmark
from spis.pvdaq_validation import PVDAQ_2107_SITE_KEY, PVDAQ_VALIDATION_OUTPUT, run_pvdaq_validation
from spis.robustness import ROBUSTNESS_OUTPUT_NAME
from spis.sites import SITES, get_site

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")

CANAKKALE_MASTER_HASH = "e1574bac5420e007ac3c04b35ab399d9c0daa089ac3490e210df8807b70ddcc2"
CANONICAL_CANAKKALE_RATE = -0.1247
CANONICAL_CANAKKALE_CI = (-0.186, -0.064)


def _hash_parquet(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pvdaq_pipeline() -> bool:
    failures: list[str] = []

    if PVDAQ_2107_SITE_KEY not in SITES:
        failures.append("SITES registry missing pvdaq_2107")
    site = get_site(PVDAQ_2107_SITE_KEY)
    if site.lat != 38.996306 or site.lon != -122.134111:
        failures.append("pvdaq_2107 coordinates incorrect")
    if not site.operational_data_available:
        failures.append("pvdaq_2107 operational_data_available must be True")

    master_path = config.DATA_PROCESSED / f"{MASTER_OUTPUT_NAME}.parquet"
    build_master_table(site_key="canakkale")
    hash_after = _hash_parquet(master_path)
    if hash_after != CANAKKALE_MASTER_HASH:
        failures.append(f"Canakkale master hash {hash_after} != baseline {CANAKKALE_MASTER_HASH}")

    try:
        pvdaq_result = run_pvdaq_validation(force_refresh=False)
    except Exception as exc:
        failures.append(f"run_pvdaq_validation failed: {exc}")
        pvdaq_result = None

    ext_report = config.REPORTS / "EXTERNAL_VALIDATION.md"
    if not ext_report.exists():
        failures.append("EXTERNAL_VALIDATION.md missing")
    elif pvdaq_result is not None:
        text = ext_report.read_text(encoding="utf-8").lower()
        if "pvdaq 2107 utility-scale validation" not in text:
            failures.append("EXTERNAL_VALIDATION.md missing PVDAQ section")

    out_path = config.DATA_PROCESSED / "pvdaq_2107" / f"{PVDAQ_VALIDATION_OUTPUT}.parquet"
    if pvdaq_result is not None and not out_path.exists():
        failures.append("pvdaq_validation.parquet missing")

    try:
        import rdtools  # noqa: F401
    except ImportError:
        failures.append("rdtools not installed; pip install -r requirements-bench.txt")
        bench_result = None
    else:
        try:
            bench_result = run_method_benchmark(srr_reps=200)
        except Exception as exc:
            failures.append(f"run_method_benchmark failed: {exc}")
            bench_result = None

    bench_report = config.REPORTS / "METHOD_BENCHMARK.md"
    if bench_result is not None:
        if not bench_report.exists():
            failures.append("METHOD_BENCHMARK.md missing")
        else:
            bench_text = bench_report.read_text(encoding="utf-8").lower()
            for phrase in ("rdtools", "spis", "conversion", "caveats"):
                if phrase not in bench_text:
                    failures.append(f"METHOD_BENCHMARK.md missing: {phrase}")
        table = bench_result["table"]
        if len(table) != 2:
            failures.append("Benchmark table must have Canakkale and PVDAQ rows")
        if table["agreement_verdict"].isna().any():
            failures.append("Benchmark missing agreement verdict")

    if pvdaq_result is not None:
        table = pvdaq_result["table"]
        can_row = table.loc[table["site_key"] == "canakkale"].iloc[0]
        can_rate = float(can_row["clear_sky_rate_pct_per_day"])
        if not np.isclose(can_rate, CANONICAL_CANAKKALE_RATE, atol=1e-3):
            failures.append("Canakkale rate in PVDAQ comparison table wrong")
        can_lo = float(can_row["clear_sky_ci_lower"])
        can_hi = float(can_row["clear_sky_ci_upper"])
        if not (
            abs(can_lo - CANONICAL_CANAKKALE_CI[0]) < 0.002
            and abs(can_hi - CANONICAL_CANAKKALE_CI[1]) < 0.002
        ):
            failures.append(f"Canakkale CI in PVDAQ table != canonical {CANONICAL_CANAKKALE_CI}")
        if (table["ci_method"] != CANONICAL_CI_METHOD).any():
            failures.append("CI method not canonical in utility comparison table")

        robustness = read_processed(ROBUSTNESS_OUTPUT_NAME, site_key="canakkale")
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
    if pvdaq_result is not None:
        LOGGER.info("- PVDAQ verdict: %s", pvdaq_result["verdict"][:180])
    if bench_result is not None:
        LOGGER.info("- Benchmark verdict: %s", bench_result["verdict"][:180])
    return True


def main() -> int:
    return 0 if verify_pvdaq_pipeline() else 1


if __name__ == "__main__":
    sys.exit(main())
