"""Verifier gate for P9 multi-site, site comparison, and inverter anomaly."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

from spis import config
from spis.clean import MASTER_OUTPUT_NAME, build_master_table
from spis.field_visit import FIELD_VISIT_PACK_PATH, build_field_visit_pack
from spis.inverter_anomaly import INVERTER_ANOMALY_OUTPUT, run_inverter_anomaly_analysis
from spis.site_comparison import SITE_COMPARISON_OUTPUT, run_site_comparison
from spis.sites import SITES, provisional_label

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")

CANAKKALE_MASTER_HASH = "bd1b07716649028b016f26d381216c6553c0ccc370ff2bd0cb88b61586c2c552"


def _hash_parquet(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_multisite() -> bool:
    """Run P9 verifier checklist."""
    failures: list[str] = []

    if set(SITES) != {"canakkale", "balikesir"}:
        failures.append("SITES registry missing canakkale or balikesir")
    bal = SITES["balikesir"]
    if not bal.coordinates_provisional:
        failures.append("Balikesir coordinates_provisional must be True")
    if bal.operational_data_available:
        failures.append("Balikesir operational_data_available must be False without raw data")

    master_path = config.DATA_PROCESSED / f"{MASTER_OUTPUT_NAME}.parquet"
    build_master_table(site_key="canakkale")
    hash_after = _hash_parquet(master_path)
    build_master_table(site_key="canakkale")
    hash_rerun = _hash_parquet(master_path)
    if hash_after != CANAKKALE_MASTER_HASH:
        failures.append(f"Canakkale master hash {hash_after} != baseline {CANAKKALE_MASTER_HASH}")
    if hash_after != hash_rerun:
        failures.append("Canakkale master hash not reproducible across two builds")

    comparison = run_site_comparison(force_refresh=False)
    comp_path = config.DATA_PROCESSED / f"{SITE_COMPARISON_OUTPUT}.parquet"
    if not comp_path.exists():
        failures.append("site_comparison.parquet missing")
    report_path = config.REPORTS / "SITE_COMPARISON.md"
    if not report_path.exists():
        failures.append("SITE_COMPARISON.md missing")
    else:
        text = report_path.read_text(encoding="utf-8")
        if "PROVISIONAL" not in text:
            failures.append("SITE_COMPARISON.md missing PROVISIONAL label for Balikesir")
        if "Ground-station vs CAMS" not in text:
            failures.append("SITE_COMPARISON.md missing ground-vs-CAMS section")

    tests = comparison["tests"]
    if tests["median_canakkale"].isna().any() or tests["median_balikesir"].isna().any():
        failures.append("Pollution tests contain null median metrics")

    inv = run_inverter_anomaly_analysis()
    inv_path = config.DATA_PROCESSED / f"{INVERTER_ANOMALY_OUTPUT}.parquet"
    if not inv_path.exists():
        failures.append("inverter_anomaly.parquet missing")
    inv_report = config.REPORTS / "INVERTER_ANOMALY.md"
    inv_text = inv_report.read_text(encoding="utf-8")
    if "not fault diagnosis" not in inv_text.lower() and "descriptive" not in inv_text.lower():
        failures.append("INVERTER_ANOMALY.md missing descriptive-not-diagnostic language")

    build_field_visit_pack()
    pack = FIELD_VISIT_PACK_PATH.read_text(encoding="utf-8")
    if "reference irradiance sensor" not in pack.lower():
        failures.append("FIELD_VISIT_PACK.md missing reference irradiance sensor check")
    if "PROVISIONAL" not in pack:
        failures.append("FIELD_VISIT_PACK.md missing PROVISIONAL Balikesir flag")

    for stem in (
        "site_comparison_pm10_monthly",
        "site_comparison_dust_monthly",
        "site_comparison_aod_monthly",
        "site_comparison_rainfall_monthly",
        "site_comparison_median_pollution_bar",
        "site_comparison_ground_vs_cams_canakkale",
        "site_comparison_ground_vs_cams_balikesir",
        "inverter_relative_performance_timeseries",
        "inverter_relative_performance_ranking",
    ):
        png = config.FIGURES / f"{stem}.png"
        csv = config.FIGURES / f"{stem}.csv"
        if not png.exists():
            failures.append(f"Missing figure {png.name}")
        if not csv.exists():
            failures.append(f"Missing figure CSV {csv.name}")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Canakkale master hash unchanged: %s", hash_after[:16])
    LOGGER.info("- Environmental verdict: %s", comparison["verdict"][:120])
    LOGGER.info("- Inverter candidates: %s", inv["candidate_underperformers"])
    LOGGER.info("- Balikesir status: %s", provisional_label("balikesir"))
    return True


def main() -> int:
    return 0 if verify_multisite() else 1


if __name__ == "__main__":
    sys.exit(main())
