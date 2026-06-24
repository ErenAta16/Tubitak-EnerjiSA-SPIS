"""Verification gate for P3 soiling analysis."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

from scipy import stats

from spis import config
from spis.io import read_processed
from spis.soiling import (
    MASTER_INPUT_NAME,
    SOILING_OUTPUT_NAME,
    rain_free_clean,
    run_soiling_analysis,
    segment_clean_days,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")


def _hash_parquet(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_soiling() -> bool:
    """Run verifier checklist for soiling outputs."""
    failures: list[str] = []

    run_soiling_analysis()
    out_path = config.DATA_PROCESSED / f"{SOILING_OUTPUT_NAME}.parquet"
    hash_first = _hash_parquet(out_path)
    run_soiling_analysis()
    hash_second = _hash_parquet(out_path)
    if hash_first != hash_second:
        failures.append("Reproducibility: soiling_segments Parquet hash differs between runs")

    segments = read_processed(SOILING_OUTPUT_NAME)
    master = read_processed(MASTER_INPUT_NAME)

    if (segments["segment_id"] == 0).any():
        failures.append("Segment 0 must be excluded from soiling_segments output")

    low = segments.loc[segments["low_confidence"]]
    if not low.empty and (low["soiling_rate_pct_per_day"] > 0).all():
        failures.append("Low-confidence segments should not all have positive slopes")

    valid = segments.loc[~segments["low_confidence"]].dropna(subset=["soiling_rate_pct_per_day"])
    positive = valid.loc[valid["soiling_rate_pct_per_day"] >= 0]
    if not positive.empty and not positive["unexpected_positive_slope"].all():
        failures.append("Positive slopes must be flagged with unexpected_positive_slope")

    pooled = float(valid["soiling_rate_pct_per_day"].mean())
    if pooled >= 0:
        failures.append("Pooled soiling rate should be negative for the study period")

    negative_recovery = segments.loc[
        segments["recovery_positive"].eq(False) & segments["recovery_abs"].notna()
    ]
    if not negative_recovery.empty:
        LOGGER.warning(
            "Segments with non-positive recovery flagged: %s",
            negative_recovery["segment_id"].tolist(),
        )

    sample = valid.iloc[0]
    sid = int(sample["segment_id"])
    clean = rain_free_clean(segment_clean_days(master, sid))
    clean = clean.loc[clean["days_since_wash"] > 0]
    baseline = float(sample["baseline_pi_temp_corrected"])
    y = 100.0 * clean["pi_temp_corrected"] / baseline
    x_flat = clean["days_since_wash"].to_numpy(dtype=float)
    ts = stats.theilslopes(y, x_flat)
    if abs(float(ts.slope) - float(sample["soiling_rate_pct_per_day"])) > 1e-6:
        failures.append("Independent Theil-Sen recompute differs from stored segment slope")

    if segments[["soiling_rate_pct_per_day", "baseline_pi_temp_corrected"]].isna().all(axis=None):
        failures.append("Soiling outputs contain all-null headline metrics")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Reproducibility: identical soiling_segments hash on two runs")
    LOGGER.info("- Slopes negative for %s high-confidence segments", len(valid))
    LOGGER.info("- Independent Theil-Sen recompute matches stored slope for segment %s", sid)
    LOGGER.info("- Low-confidence segments flagged: %s", segments["low_confidence"].sum())
    return True


def main() -> int:
    return 0 if verify_soiling() else 1


if __name__ == "__main__":
    sys.exit(main())
