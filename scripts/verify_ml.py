"""Verification gate for P5/P12/P13 machine-learning analysis."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from spis import config
from spis.io import read_processed
from spis.ml import (
    FEATURE_COLUMNS,
    LEGACY_MODELS,
    MODEL_RANDOM_FOREST,
    PANEL_MODELS,
    SCALED_PANEL_MODELS,
    TARGET_ABSOLUTE,
    TARGET_SOILING_RATIO,
    assert_no_leakage,
    blocked_cv_metrics,
    build_modelling_frame,
    evaluate_model,
    fit_panel_model,
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
    panel_rows = output.loc[output["record_type"] == "panel_comparison"]
    if len(panel_rows) != len(PANEL_MODELS):
        failures.append(
            f"Expected {len(PANEL_MODELS)} panel_comparison rows, got {len(panel_rows)}"
        )

    for framing, models in (
        (TARGET_SOILING_RATIO, PANEL_MODELS),
        (TARGET_ABSOLUTE, LEGACY_MODELS),
    ):
        test_rows = output.loc[
            (output["record_type"] == "test_metrics")
            & (output["target_framing"] == framing)
        ]
        if len(test_rows) != len(models):
            failures.append(
                f"Expected {len(models)} test_metrics rows for {framing}, got {len(test_rows)}"
            )
        cv_rows = output.loc[
            (output["record_type"] == "cv_metrics") & (output["target_framing"] == framing)
        ]
        if len(cv_rows) != len(models):
            failures.append(
                f"Expected {len(models)} cv_metrics rows for {framing}, got {len(cv_rows)}"
            )

    if "mean_baseline" not in set(
        output.loc[
            (output["record_type"] == "test_metrics")
            & (output["target_framing"] == TARGET_SOILING_RATIO)
        ]["model_name"]
    ):
        failures.append("mean_baseline missing from soiling_ratio test_metrics")

    cv = blocked_cv_metrics(split.train, TARGET_SOILING_RATIO, MODEL_RANDOM_FOREST)
    stored_cv = output.loc[
        (output["record_type"] == "cv_metrics")
        & (output["model_name"] == MODEL_RANDOM_FOREST)
        & (output["target_framing"] == TARGET_SOILING_RATIO)
    ].iloc[0]
    if abs(float(stored_cv["r2_mean"]) - cv.r2_mean) > 1e-6:
        failures.append("Independent blocked CV recompute differs from stored RF CV R2")

    x_train, y_train = prepare_xy(split.train.iloc[:120], TARGET_SOILING_RATIO)
    pipe = fit_panel_model("ridge", x_train, y_train)
    if "ridge" in SCALED_PANEL_MODELS:
        scaler = pipe.named_steps["scaler"]
        if not np.allclose(scaler.mean_, x_train.mean().to_numpy(), rtol=1e-5):
            failures.append("StandardScaler must be fit on fold-local training rows only")

    verdict = output.loc[output["record_type"] == "ml_verdict", "verdict"]
    if verdict.isna().any() or verdict.empty:
        failures.append("ML verdict missing")

    panel_cmp = output.loc[output["record_type"] == "panel_comparison"].sort_values(
        "cv_r2_mean", ascending=False
    )
    if not panel_cmp["cv_r2_mean"].is_monotonic_decreasing:
        failures.append("panel_comparison rows must be sorted by cv_r2_mean descending")

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

    figure_png = config.FIGURES / "ml_panel_cv_r2_comparison.png"
    figure_csv = config.FIGURES / "ml_panel_cv_r2_comparison.csv"
    if not figure_png.exists() or not figure_csv.exists():
        failures.append("P13 panel comparison figure PNG/CSV missing")

    investigation = output.loc[output["record_type"] == "ml_verdict", "investigation_model"]
    inv_model = (
        None
        if investigation.isna().all() or pd.isna(investigation.iloc[0])
        else str(investigation.iloc[0])
    )
    importance = output.loc[
        (output["record_type"] == "permutation_importance")
        & (output["target_framing"] == TARGET_SOILING_RATIO)
    ]
    any_non_negative = bool((panel_cmp["cv_r2_mean"] >= 0).any())
    if inv_model and len(importance) != len(FEATURE_COLUMNS):
        failures.append(
            f"Investigation model set but expected {len(FEATURE_COLUMNS)} importances"
        )
    if not inv_model and not importance.empty:
        failures.append("Permutation importance present without investigation model")
    if not any_non_negative and inv_model:
        failures.append("Investigation model set despite all panel CV R2 negative")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    best = panel_cmp.iloc[0]
    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Reproducibility: identical ml_model_metrics hash")
    LOGGER.info("- Leakage guard and fold-local scaling confirmed")
    LOGGER.info(
        "- Panel models reported: %s soiling_ratio + %s legacy absolute",
        len(PANEL_MODELS),
        len(LEGACY_MODELS),
    )
    LOGGER.info(
        "- Best panel CV R2=%s (%.4f +/- %.4f); any CV>=0: %s",
        best["model_name"],
        float(best["cv_r2_mean"]),
        float(best["cv_r2_std"]),
        any_non_negative,
    )
    LOGGER.info("- ML verdict: %s", verdict.iloc[0][:120])
    return True


def main() -> int:
    return 0 if verify_ml() else 1


if __name__ == "__main__":
    sys.exit(main())
