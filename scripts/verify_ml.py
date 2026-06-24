"""Verification gate for P5 machine-learning analysis."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

import joblib

from spis import config
from spis.io import read_processed
from spis.ml import (
    FEATURE_COLUMNS,
    POLLUTION_FEATURES,
    assert_no_leakage,
    build_modelling_frame,
    evaluate_model,
    prepare_xy,
    run_ml_analysis,
    time_based_split,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")


def _hash_parquet(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_ml() -> bool:
    """Run verifier checklist for ML outputs."""
    failures: list[str] = []

    run_ml_analysis()
    metrics_path = config.DATA_PROCESSED / f"{config.ML_METRICS_OUTPUT_NAME}.parquet"
    hash_first = _hash_parquet(metrics_path)
    run_ml_analysis()
    hash_second = _hash_parquet(metrics_path)
    if hash_first != hash_second:
        failures.append("Reproducibility: ml_model_metrics hash differs between runs")

    try:
        assert_no_leakage(list(FEATURE_COLUMNS))
    except ValueError as exc:
        failures.append(f"Leakage guard: {exc}")

    features_json = config.DATA_PROCESSED / config.ML_FEATURES_FILENAME
    if not features_json.exists():
        failures.append("Feature list JSON missing")
    else:
        saved = json.loads(features_json.read_text(encoding="utf-8"))
        if set(saved) & set(config.ML_LEAKAGE_FORBIDDEN):
            failures.append("Saved feature list contains forbidden leakage columns")

    master = read_processed("master_daily")
    frame = build_modelling_frame(master)
    split = time_based_split(frame)
    if split.train["date"].max() >= split.test["date"].min():
        failures.append("Split is not strictly time-based")

    output = read_processed(config.ML_METRICS_OUTPUT_NAME)
    importance = output.loc[output["record_type"] == "permutation_importance"]
    if len(importance) != len(FEATURE_COLUMNS):
        failures.append(
            f"Expected {len(FEATURE_COLUMNS)} importances, got {len(importance)}"
        )
    if not POLLUTION_FEATURES.issubset(set(importance["feature"])):
        failures.append("Pollution features missing from importance table")

    verdict = output.loc[output["record_type"] == "pollution_verdict", "verdict"]
    if verdict.isna().any() or verdict.empty:
        failures.append("Pollution verdict missing")

    rf = output.loc[
        (output["record_type"] == "test_metrics")
        & (output["model_name"] == "random_forest")
    ].iloc[0]
    model = joblib.load(config.DATA_PROCESSED / config.ML_MODEL_FILENAME)
    _, y_test = prepare_xy(split.test)
    x_test, _ = prepare_xy(split.test)
    mae, _, r2 = evaluate_model(y_test.to_numpy(), model.predict(x_test))
    if abs(mae - float(rf["mae"])) > 1e-6 or abs(r2 - float(rf["r2"])) > 1e-6:
        failures.append("Independent recompute from saved model differs from stored metrics")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Reproducibility: identical ml_model_metrics hash")
    LOGGER.info("- Leakage guard: production/irradiation absent")
    LOGGER.info("- Time-based split confirmed")
    LOGGER.info("- RF test R2=%.4f MAE=%.5f", float(rf["r2"]), float(rf["mae"]))
    LOGGER.info("- Pollution verdict: %s", verdict.iloc[0][:80])
    return True


def main() -> int:
    return 0 if verify_ml() else 1


if __name__ == "__main__":
    sys.exit(main())
