"""P5 Random Forest corroboration of the soiling model with strict leakage control.

Production and irradiation are excluded from features because they define PI =
production/irradiation; including them would leak the target ratio. The RF is
secondary to the physical soiling fit; it re-tests pollution nonlinearly via
permutation importance on exogenous weather and CAMS variables.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import partial_dependence, permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit

from spis import config
from spis.io import read_processed, write_processed
from spis.robustness import attach_clearness_index
from spis.soiling import MASTER_INPUT_NAME, SOILING_OUTPUT_NAME

LOGGER = logging.getLogger(__name__)

FEATURE_COLUMNS: tuple[str, ...] = (
    "days_since_wash",
    "month_sin",
    "month_cos",
    "clearness_index",
    "nasa_t2m",
    "nasa_t2m_max",
    "nasa_ws2m",
    "nasa_precip_mm",
    "days_since_rain",
    "pm10",
    "dust",
    "aerosol_optical_depth",
    "pm10_accumulated",
    "dust_accumulated",
    "aod_accumulated",
)

POLLUTION_FEATURES: frozenset[str] = frozenset(
    {
        "pm10",
        "dust",
        "aerosol_optical_depth",
        "pm10_accumulated",
        "dust_accumulated",
        "aod_accumulated",
    }
)


@dataclass(frozen=True)
class TimeSplit:
    """Chronological train/test partition."""

    train: pd.DataFrame
    test: pd.DataFrame
    split_date: pd.Timestamp
    test_fraction: float


@dataclass(frozen=True)
class ModelMetrics:
    """Held-out test metrics for one model."""

    model_name: str
    mae: float
    rmse: float
    r2: float
    n_train: int
    n_test: int


def assert_no_leakage(feature_names: list[str]) -> None:
    """Raise if any forbidden production/irradiance column appears in features."""
    forbidden = set(feature_names) & set(config.ML_LEAKAGE_FORBIDDEN)
    if forbidden:
        raise ValueError(f"Leakage guard failed: forbidden columns {forbidden}")


def compute_days_since_rain(frame: pd.DataFrame) -> pd.Series:
    """Days since the last rain day (PRECTOTCORR >= threshold)."""
    rain_dates = frame.loc[frame["rain_day"], "date"]
    if rain_dates.empty:
        return pd.Series(len(frame), index=frame.index, dtype="float64")
    out = pd.Series(index=frame.index, dtype="float64")
    for idx, row in frame.iterrows():
        prior = rain_dates.loc[rain_dates <= row["date"]]
        if prior.empty:
            out.loc[idx] = float((row["date"] - frame["date"].min()).days)
        else:
            out.loc[idx] = float((row["date"] - prior.max()).days)
    return out


def compute_accumulated_pollutants(frame: pd.DataFrame) -> pd.DataFrame:
    """Cumulative CAMS pollutants since the last wash within each segment."""
    working = frame.sort_values(["segment_id", "date"]).copy()
    for raw, acc in (
        ("pm10", "pm10_accumulated"),
        ("dust", "dust_accumulated"),
        ("aerosol_optical_depth", "aod_accumulated"),
    ):
        working[acc] = working.groupby("segment_id", group_keys=False)[raw].transform(
            lambda s: s.fillna(0.0).cumsum()
        )
    return working


def build_modelling_frame(master: pd.DataFrame) -> pd.DataFrame:
    """Construct the tidy ML frame with exogenous features only."""
    frame = attach_clearness_index(master)
    frame = frame.loc[
        frame["is_clean_observation"]
        & ~frame["pre_first_wash"]
        & frame["segment_id"].notna()
        & (frame["segment_id"] > 0)
    ].copy()
    frame = compute_accumulated_pollutants(frame)
    frame["days_since_rain"] = compute_days_since_rain(frame)
    month = frame["date"].dt.month
    frame["month_sin"] = np.sin(2.0 * np.pi * month / 12.0)
    frame["month_cos"] = np.cos(2.0 * np.pi * month / 12.0)
    feature_cols = list(FEATURE_COLUMNS)
    before = len(frame)
    frame = frame.dropna(subset=feature_cols + ["pi_temp_corrected"])
    frame = frame.sort_values("date").reset_index(drop=True)
    LOGGER.info(
        "ML modelling frame: %s rows (%s dropped for null features/target)",
        len(frame),
        before - len(frame),
    )
    return frame


def time_based_split(frame: pd.DataFrame, test_fraction: float | None = None) -> TimeSplit:
    """Hold out the latest chronological span for testing."""
    frac = test_fraction or config.ML_TEST_FRACTION
    n_test = max(1, int(round(len(frame) * frac)))
    split_idx = len(frame) - n_test
    split_date = frame.iloc[split_idx]["date"]
    train = frame.iloc[:split_idx].copy()
    test = frame.iloc[split_idx:].copy()
    LOGGER.info(
        "Time split at %s: train=%s test=%s (fraction=%.2f)",
        split_date.date(),
        len(train),
        len(test),
        frac,
    )
    return TimeSplit(train=train, test=test, split_date=split_date, test_fraction=frac)


def prepare_xy(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Extract feature matrix X and target y."""
    features = list(FEATURE_COLUMNS)
    assert_no_leakage(features)
    x_frame = frame[features].astype(float).copy()
    if x_frame.isna().any().any():
        missing = x_frame.columns[x_frame.isna().any()].tolist()
        raise ValueError(f"ML features contain nulls (no imputation): {missing}")
    return x_frame, frame["pi_temp_corrected"]


def evaluate_model(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    """Return MAE, RMSE, R2."""
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred))
    return mae, rmse, r2


def fit_baseline_trend(split: TimeSplit) -> LinearRegression:
    """Simple physical baseline: PI ~ days_since_wash (P3 trend proxy)."""
    x_train = split.train[["days_since_wash"]].astype(float)
    y_train = split.train["pi_temp_corrected"]
    model = LinearRegression()
    model.fit(x_train, y_train)
    return model


def fit_random_forest(split: TimeSplit) -> tuple[RandomForestRegressor, dict[str, Any]]:
    """GridSearchCV with TimeSeriesSplit on the training span only."""
    x_train, y_train = prepare_xy(split.train)
    tscv = TimeSeriesSplit(n_splits=config.ML_CV_SPLITS)
    search = GridSearchCV(
        RandomForestRegressor(random_state=config.RANDOM_STATE),
        config.ML_RF_PARAM_GRID,
        cv=tscv,
        scoring="neg_mean_absolute_error",
        n_jobs=-1,
        refit=True,
    )
    search.fit(x_train, y_train)
    LOGGER.info(
        "RF GridSearch best params: %s MAE=%.5f",
        search.best_params_,
        -search.best_score_,
    )
    return search.best_estimator_, {
        "best_params": search.best_params_,
        "cv_mae": -search.best_score_,
    }


def permutation_importance_with_ci(
    model: RandomForestRegressor,
    x_test: pd.DataFrame,
    y_test: pd.Series,
) -> pd.DataFrame:
    """Permutation importance on held-out test set with approximate 95% CIs."""
    result = permutation_importance(
        model,
        x_test,
        y_test,
        n_repeats=config.ML_PERMUTATION_REPEATS,
        random_state=config.RANDOM_STATE,
        n_jobs=-1,
    )
    rows = []
    for idx, name in enumerate(x_test.columns):
        mean = float(result.importances_mean[idx])
        std = float(result.importances_std[idx])
        rows.append(
            {
                "feature": name,
                "importance_mean": mean,
                "importance_std": std,
                "ci_lower": mean - 1.96 * std,
                "ci_upper": mean + 1.96 * std,
            }
        )
    return pd.DataFrame(rows).sort_values("importance_mean", ascending=False)


def p35_soiling_rate_pct(segments: pd.DataFrame, robustness: pd.DataFrame | None) -> float:
    """P3.5 clear-sky pooled rate (%/day) for partial-dependence comparison."""
    if robustness is not None:
        verdict = robustness.loc[robustness["record_type"] == "p4_verdict"]
        if not verdict.empty:
            return float(verdict.iloc[0]["recommended_rate_pct_per_day"])
    return float(segments["soiling_rate_pct_per_day"].median())


def plot_permutation_importance(importance: pd.DataFrame) -> None:
    """Bar chart of permutation importance with error bars."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    y_pos = np.arange(len(importance))
    ax.barh(
        y_pos,
        importance["importance_mean"],
        xerr=1.96 * importance["importance_std"],
        color="C0",
        alpha=0.85,
    )
    ax.set_yticks(y_pos)
    ax.set_yticklabels(importance["feature"])
    ax.invert_yaxis()
    ax.set_xlabel("Permutation importance (test set)")
    ax.set_title("P5 RF permutation importance with 95% CI")
    fig.tight_layout()
    png = config.FIGURES / "ml_permutation_importance.png"
    csv = config.FIGURES / "ml_permutation_importance.csv"
    fig.savefig(png, dpi=300)
    plt.close(fig)
    importance.to_csv(csv, index=False)
    LOGGER.info("Wrote %s and %s", png, csv)


def plot_predicted_vs_actual(
    split: TimeSplit,
    y_pred: np.ndarray,
    model_name: str,
) -> None:
    """Time-ordered predicted vs actual on held-out test."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    test = split.test.copy()
    test["predicted"] = y_pred
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(test["date"], test["pi_temp_corrected"], label="actual", color="C0")
    ax.plot(test["date"], test["predicted"], label="predicted", color="C1", alpha=0.8)
    ax.set_xlabel("Date")
    ax.set_ylabel("pi_temp_corrected")
    ax.set_title(f"P5 {model_name}: predicted vs actual (held-out test)")
    ax.legend()
    fig.tight_layout()
    png = config.FIGURES / "ml_predicted_vs_actual.png"
    csv = config.FIGURES / "ml_predicted_vs_actual.csv"
    fig.savefig(png, dpi=300)
    plt.close(fig)
    test[["date", "pi_temp_corrected", "predicted"]].to_csv(csv, index=False)
    LOGGER.info("Wrote %s and %s", png, csv)


def plot_partial_dependence(
    model: RandomForestRegressor,
    x_train: pd.DataFrame,
    feature: str,
    p35_rate_pct: float | None = None,
    filename_suffix: str = "",
) -> pd.DataFrame:
    """Partial dependence curve for one feature."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    pd_result = partial_dependence(
        model,
        x_train,
        features=[feature],
        grid_resolution=50,
    )
    grid = pd_result["grid_values"][0]
    avg = pd_result["average"][0]
    curve = pd.DataFrame({feature: grid, "partial_dependence": avg})
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(grid, avg, color="C0")
    if feature == "days_since_wash" and p35_rate_pct is not None and len(grid) > 1:
        baseline = float(avg[0])
        slope_pct = (float(avg[-1]) - baseline) / max(float(grid[-1] - grid[0]), 1.0) * 100.0
        ax.set_title(
            f"PD days_since_wash (RF slope ~{slope_pct:.3f}%/day; P3.5={p35_rate_pct:.3f}%/day)"
        )
    else:
        ax.set_title(f"Partial dependence: {feature}")
    ax.set_xlabel(feature)
    ax.set_ylabel("Partial dependence")
    fig.tight_layout()
    suffix = filename_suffix or feature
    png = config.FIGURES / f"ml_partial_dependence_{suffix}.png"
    csv = config.FIGURES / f"ml_partial_dependence_{suffix}.csv"
    fig.savefig(png, dpi=300)
    plt.close(fig)
    curve.to_csv(csv, index=False)
    LOGGER.info("Wrote %s and %s", png, csv)
    return curve


def pollution_verdict(importance: pd.DataFrame) -> str:
    """Plain-language verdict on pollution features in permutation ranking."""
    pollution = POLLUTION_FEATURES
    ranked = importance.reset_index(drop=True)
    ranks = {
        row["feature"]: idx + 1
        for idx, row in ranked.iterrows()
        if row["feature"] in pollution
    }
    top_pollutant = ranked.loc[ranked["feature"].isin(pollution)].iloc[0]
    n_features = len(ranked)
    if top_pollutant["importance_mean"] <= 0 or top_pollutant["ci_upper"] <= 0:
        return (
            "Pollution features rank low with non-positive permutation importance; "
            "corroborates P3.5 (pollution not a daily driver)."
        )
    if ranks.get(top_pollutant["feature"], n_features) <= 3:
        return (
            f"{top_pollutant['feature']} ranks #{ranks[top_pollutant['feature']]} with "
            "positive permutation importance; possible nonlinear effect missed by "
            "linear HAC — quantify via partial dependence, not causation."
        )
    return (
        f"Pollution features present but mid/lower rank (best: {top_pollutant['feature']} "
        f"#{ranks[top_pollutant['feature']]} of {n_features}); weak corroboration of "
        "pollution thesis, consistent with P3.5."
    )


def write_ml_results_report(
    rf_metrics: ModelMetrics,
    baseline_metrics: ModelMetrics,
    importance: pd.DataFrame,
    verdict: str,
    cv_info: dict[str, Any],
    split: TimeSplit,
) -> None:
    """Write reports/ML_RESULTS.md."""
    path = config.REPORTS / "ML_RESULTS.md"
    lines = [
        "# P5 Machine Learning Results",
        "",
        "## Leakage control",
        "",
        "Target: `pi_temp_corrected` on `is_clean_observation` days (post-first-wash).",
        "Features are exogenous only; **production and irradiation are excluded**",
        "because PI = production/irradiation would leak the target ratio.",
        "",
        f"Modelling frame: train={rf_metrics.n_train}, test={rf_metrics.n_test} "
        f"(time split at {split.split_date.date()}, latest "
        f"{split.test_fraction:.0%} held out).",
        "",
        "## Test metrics",
        "",
        "| model | MAE | RMSE | R2 |",
        "|---|---:|---:|---:|",
        f"| Random Forest | {rf_metrics.mae:.5f} | {rf_metrics.rmse:.5f} | {rf_metrics.r2:.4f} |",
        f"| days_since_wash baseline | {baseline_metrics.mae:.5f} | "
        f"{baseline_metrics.rmse:.5f} | {baseline_metrics.r2:.4f} |",
        "",
        "## RF vs simple baseline",
        "",
    ]
    if rf_metrics.r2 <= baseline_metrics.r2 + 0.01:
        lines.append(
            "RF does **not** meaningfully beat the simple soiling-trend baseline "
            "(days_since_wash linear model). A simple physical trend model suffices."
        )
    else:
        lines.append(
            "RF modestly beats the days_since_wash baseline on held-out R2/MAE; "
            "weather adds explanatory power beyond the linear trend alone."
        )
    lines.extend(
        [
            "",
            f"GridSearchCV best params: `{cv_info['best_params']}` "
            f"(TimeSeriesSplit CV MAE={cv_info['cv_mae']:.5f}).",
            "",
            "## Permutation importance (test set, full ranking)",
            "",
            "| rank | feature | mean | 95% CI |",
            "|---:|---|---:|---|",
        ]
    )
    for rank, row in importance.reset_index(drop=True).iterrows():
        lines.append(
            f"| {rank + 1} | {row['feature']} | {row['importance_mean']:.5f} | "
            f"[{row['ci_lower']:.5f}, {row['ci_upper']:.5f}] |"
        )
    lines.extend(["", "## Pollution verdict", "", verdict, ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def persist_model(model: RandomForestRegressor, features: list[str]) -> None:
    """Save fitted model and feature list for reproducibility."""
    model_path = config.DATA_PROCESSED / config.ML_MODEL_FILENAME
    feature_path = config.DATA_PROCESSED / config.ML_FEATURES_FILENAME
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    feature_path.write_text(json.dumps(features, indent=2), encoding="utf-8")
    LOGGER.info("Saved model to %s and features to %s", model_path, feature_path)


def build_metrics_parquet(
    rf_metrics: ModelMetrics,
    baseline_metrics: ModelMetrics,
    importance: pd.DataFrame,
    cv_info: dict[str, Any],
    verdict: str,
    split: TimeSplit,
) -> pd.DataFrame:
    """Assemble ml_model_metrics.parquet rows."""
    rows: list[dict[str, Any]] = [
        {
            "record_type": "split_info",
            "split_date": split.split_date,
            "test_fraction": split.test_fraction,
            "n_train": rf_metrics.n_train,
            "n_test": rf_metrics.n_test,
        },
        {
            "record_type": "test_metrics",
            "model_name": rf_metrics.model_name,
            "mae": rf_metrics.mae,
            "rmse": rf_metrics.rmse,
            "r2": rf_metrics.r2,
        },
        {
            "record_type": "test_metrics",
            "model_name": baseline_metrics.model_name,
            "mae": baseline_metrics.mae,
            "rmse": baseline_metrics.rmse,
            "r2": baseline_metrics.r2,
        },
        {
            "record_type": "cv_results",
            "best_params": str(cv_info["best_params"]),
            "cv_mae": cv_info["cv_mae"],
        },
        {
            "record_type": "pollution_verdict",
            "verdict": verdict,
        },
    ]
    for _, row in importance.iterrows():
        rows.append({"record_type": "permutation_importance", **row.to_dict()})
    return pd.DataFrame(rows)


def run_ml_analysis() -> dict[str, Any]:
    """Execute P5 Random Forest analysis end-to-end."""
    master = read_processed(MASTER_INPUT_NAME)
    segments = read_processed(SOILING_OUTPUT_NAME)
    robustness_path = config.DATA_PROCESSED / "soiling_robustness.parquet"
    robustness = (
        read_processed("soiling_robustness") if robustness_path.exists() else None
    )

    frame = build_modelling_frame(master)
    split = time_based_split(frame)
    x_train, y_train = prepare_xy(split.train)
    x_test, y_test = prepare_xy(split.test)

    baseline = fit_baseline_trend(split)
    baseline_pred = baseline.predict(split.test[["days_since_wash"]].astype(float))
    b_mae, b_rmse, b_r2 = evaluate_model(y_test.to_numpy(), baseline_pred)
    baseline_metrics = ModelMetrics(
        model_name="days_since_wash_linear",
        mae=b_mae,
        rmse=b_rmse,
        r2=b_r2,
        n_train=len(split.train),
        n_test=len(split.test),
    )

    rf_model, cv_info = fit_random_forest(split)
    rf_pred = rf_model.predict(x_test)
    r_mae, r_rmse, r_r2 = evaluate_model(y_test.to_numpy(), rf_pred)
    rf_metrics = ModelMetrics(
        model_name="random_forest",
        mae=r_mae,
        rmse=r_rmse,
        r2=r_r2,
        n_train=len(split.train),
        n_test=len(split.test),
    )

    importance = permutation_importance_with_ci(rf_model, x_test, y_test)
    verdict = pollution_verdict(importance)
    p35_rate = p35_soiling_rate_pct(segments, robustness)

    metrics_df = build_metrics_parquet(
        rf_metrics, baseline_metrics, importance, cv_info, verdict, split
    )
    write_processed(config.ML_METRICS_OUTPUT_NAME, metrics_df)
    persist_model(rf_model, list(FEATURE_COLUMNS))

    plot_permutation_importance(importance)
    plot_predicted_vs_actual(split, rf_pred, "Random Forest")
    plot_partial_dependence(
        rf_model, x_train, "days_since_wash", p35_rate_pct=p35_rate
    )
    top_pollutant = importance.loc[importance["feature"].isin(POLLUTION_FEATURES)].iloc[0][
        "feature"
    ]
    plot_partial_dependence(
        rf_model,
        x_train,
        top_pollutant,
        filename_suffix="top_pollutant",
    )

    write_ml_results_report(
        rf_metrics, baseline_metrics, importance, verdict, cv_info, split
    )

    LOGGER.info(
        "P5 RF test MAE=%.5f RMSE=%.5f R2=%.4f; baseline R2=%.4f",
        r_mae,
        r_rmse,
        r_r2,
        b_r2,
    )
    return {
        "rf_metrics": rf_metrics,
        "baseline_metrics": baseline_metrics,
        "importance": importance,
        "verdict": verdict,
        "split": split,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_ml_analysis()
