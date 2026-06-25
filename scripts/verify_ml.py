"""Verification gate for P5/P12 machine-learning analysis."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

import joblib
import numpy as np

from spis import config
from spis.io import read_processed
from spis.ml import (
    ALL_MODELS,
    FEATURE_COLUMNS,
    MODEL_RANDOM_FOREST,
    TARGET_SOILING_RATIO,
    assert_no_leakage,
    blocked_cv_metrics,
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
    segments = read_processed("soiling_segments")
    frame = build_modelling_frame(master, segments)
    split = time_based_split(frame)
    if split.train["date"].max() >= split.test["date"].min():
        failures.append("Split is not strictly time-based")

    baseline_map = segments.set_index("segment_id")["baseline_pi_temp_corrected"]
    expected = frame["segment_id"].map(baseline_map)
    if not np.allclose(frame["segment_baseline_pi"], expected, equal_nan=False):
        failures.append("Segment baseline must come from P3 post-wash baselines only")

    output = read_processed(config.ML_METRICS_OUTPUT_NAME)
    for framing in ("pi_temp_corrected", TARGET_SOILING_RATIO):
        test_rows = output.loc[
            (output["record_type"] == "test_metrics")
            & (output["target_framing"] == framing)
        ]
        if len(test_rows) != len(ALL_MODELS):
            failures.append(
                f"Expected {len(ALL_MODELS)} test_metrics rows for {framing}, "
                f"got {len(test_rows)}"
            )
        cv_rows = output.loc[
            (output["record_type"] == "cv_metrics") & (output["target_framing"] == framing)
        ]
        if len(cv_rows) != len(ALL_MODELS):
            failures.append(
                f"Expected {len(ALL_MODELS)} cv_metrics rows for {framing}, got {len(cv_rows)}"
            )
        if "mean_baseline" not in set(test_rows["model_name"]):
            failures.append(f"mean_baseline missing from test_metrics for {framing}")

    cv = blocked_cv_metrics(split.train, TARGET_SOILING_RATIO, MODEL_RANDOM_FOREST)
    stored_cv = output.loc[
        (output["record_type"] == "cv_metrics")
        & (output["model_name"] == MODEL_RANDOM_FOREST)
        & (output["target_framing"] == TARGET_SOILING_RATIO)
    ].iloc[0]
    if abs(float(stored_cv["r2_mean"]) - cv.r2_mean) > 1e-6:
        failures.append("Independent blocked CV recompute differs from stored RF CV R2")

    verdict = output.loc[output["record_type"] == "ml_verdict", "verdict"]
    if verdict.isna().any() or verdict.empty:
        failures.append("ML verdict missing")

    rf = output.loc[
        (output["record_type"] == "test_metrics")
        & (output["model_name"] == MODEL_RANDOM_FOREST)
        & (output["target_framing"] == TARGET_SOILING_RATIO)
    ].iloc[0]
    model = joblib.load(config.DATA_PROCESSED / config.ML_MODEL_FILENAME)
    x_test, y_test = prepare_xy(split.test, TARGET_SOILING_RATIO)
    mae, _, r2 = evaluate_model(y_test.to_numpy(), model.predict(x_test))
    if abs(mae - float(rf["mae"])) > 1e-6 or abs(r2 - float(rf["r2"])) > 1e-6:
        failures.append("Independent recompute from saved model differs from stored metrics")

    importance = output.loc[
        (output["record_type"] == "permutation_importance")
        & (output["target_framing"] == TARGET_SOILING_RATIO)
    ]
    rf_cv_row = output.loc[
        (output["record_type"] == "cv_metrics")
        & (output["model_name"] == MODEL_RANDOM_FOREST)
        & (output["target_framing"] == TARGET_SOILING_RATIO)
    ].iloc[0]
    if float(rf_cv_row["r2_mean"]) >= 0 and len(importance) != len(FEATURE_COLUMNS):
        failures.append(
            f"Non-negative CV R2 but expected {len(FEATURE_COLUMNS)} importances, "
            f"got {len(importance)}"
        )
    if float(rf_cv_row["r2_mean"]) < 0 and not importance.empty:
        failures.append(
            "Permutation importance present despite negative blocked CV R2 (untrusted)"
        )

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Reproducibility: identical ml_model_metrics hash")
    LOGGER.info("- Leakage guard: production/irradiation/soiling_ratio absent from features")
    LOGGER.info("- Time-based split and blocked CV confirmed")
    LOGGER.info(
        "- soiling_ratio RF test R2=%.4f MAE=%.5f; CV R2=%.4f +/- %.4f",
        float(rf["r2"]),
        float(rf["mae"]),
        float(rf_cv_row["r2_mean"]),
        float(rf_cv_row["r2_std"]),
    )
    LOGGER.info("- ML verdict: %s", verdict.iloc[0][:100])
    return True


def main() -> int:
    return 0 if verify_ml() else 1


if __name__ == "__main__":
    sys.exit(main())
