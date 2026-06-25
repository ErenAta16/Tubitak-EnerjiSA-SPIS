"""P5/P12 machine learning corroboration with strict leakage control.

Production and irradiation are excluded from features because they define PI =
production/irradiation. P12 reframes the target to within-segment soiling_ratio
(100 * pi / post-wash segment baseline) so ML matches the physical soiling question
and is not penalized by segment-level PI resets at each wash.
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
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import partial_dependence, permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit

from spis import config
from spis.io import read_processed, write_processed
from spis.robustness import attach_clearness_index
from spis.soiling import MASTER_INPUT_NAME, SOILING_OUTPUT_NAME

LOGGER = logging.getLogger(__name__)

TARGET_ABSOLUTE = "pi_temp_corrected"
TARGET_SOILING_RATIO = "soiling_ratio"

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

MODEL_MEAN_BASELINE = "mean_baseline"
MODEL_DAYS_SINCE_WASH = "days_since_wash_linear"
MODEL_RANDOM_FOREST = "random_forest"
MODEL_HIST_GB = "hist_gradient_boosting"

ALL_MODELS: tuple[str, ...] = (
    MODEL_MEAN_BASELINE,
    MODEL_DAYS_SINCE_WASH,
    MODEL_RANDOM_FOREST,
    MODEL_HIST_GB,
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
    """Held-out test metrics for one model and target framing."""

    model_name: str
    target_framing: str
    mae: float
    rmse: float
    r2: float
    n_train: int
    n_test: int


@dataclass(frozen=True)
class CvMetrics:
    """Blocked time-series CV metrics (train span only)."""

    model_name: str
    target_framing: str
    mae_mean: float
    mae_std: float
    rmse_mean: float
    rmse_std: float
    r2_mean: float
    r2_std: float
    n_folds: int


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


def attach_soiling_ratio(frame: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    """Add within-segment soiling_ratio using each segment's P3 post-wash baseline."""
    baseline_map = segments.set_index("segment_id")["baseline_pi_temp_corrected"]
    working = frame.copy()
    working["segment_baseline_pi"] = working["segment_id"].map(baseline_map)
    missing = working.loc[working["segment_baseline_pi"].isna(), "segment_id"].unique()
    if len(missing):
        raise ValueError(f"Missing P3 segment baseline for segment_ids: {missing.tolist()}")
    working[TARGET_SOILING_RATIO] = (
        100.0 * working[TARGET_ABSOLUTE] / working["segment_baseline_pi"]
    )
    return working


def build_modelling_frame(master: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    """Construct the tidy ML frame with exogenous features and both targets."""
    frame = attach_clearness_index(master)
    frame = frame.loc[
        frame["is_clean_observation"]
        & ~frame["pre_first_wash"]
        & frame["segment_id"].notna()
        & (frame["segment_id"] > 0)
    ].copy()
    frame = compute_accumulated_pollutants(frame)
    frame = attach_soiling_ratio(frame, segments)
    frame["days_since_rain"] = compute_days_since_rain(frame)
    month = frame["date"].dt.month
    frame["month_sin"] = np.sin(2.0 * np.pi * month / 12.0)
    frame["month_cos"] = np.cos(2.0 * np.pi * month / 12.0)
    feature_cols = list(FEATURE_COLUMNS)
    before = len(frame)
    frame = frame.dropna(
        subset=feature_cols + [TARGET_ABSOLUTE, TARGET_SOILING_RATIO]
    )
    frame = frame.sort_values("date").reset_index(drop=True)
    LOGGER.info(
        "ML modelling frame: %s rows (%s dropped for null features/targets)",
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


def prepare_xy(
    frame: pd.DataFrame,
    target_col: str = TARGET_SOILING_RATIO,
) -> tuple[pd.DataFrame, pd.Series]:
    """Extract feature matrix X and target y."""
    features = list(FEATURE_COLUMNS)
    assert_no_leakage(features)
    x_frame = frame[features].astype(float).copy()
    if x_frame.isna().any().any():
        missing = x_frame.columns[x_frame.isna().any()].tolist()
        raise ValueError(f"ML features contain nulls (no imputation): {missing}")
    if target_col not in frame.columns:
        raise ValueError(f"Unknown target column: {target_col}")
    return x_frame, frame[target_col]


def evaluate_model(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    """Return MAE, RMSE, R2."""
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred))
    return mae, rmse, r2


def _fixed_random_forest() -> RandomForestRegressor:
    return RandomForestRegressor(
        n_estimators=100,
        max_depth=5,
        min_samples_leaf=5,
        random_state=config.RANDOM_STATE,
    )


def _fixed_hist_gradient_boosting() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_depth=5,
        max_iter=100,
        random_state=config.RANDOM_STATE,
    )


def predict_mean_baseline(train: pd.DataFrame, test: pd.DataFrame, target_col: str) -> np.ndarray:
    """Trivial baseline: predict the training-set mean."""
    return np.full(len(test), float(train[target_col].mean()))


def fit_days_since_wash_linear(
    train: pd.DataFrame,
    target_col: str,
) -> LinearRegression:
    """Simple physical baseline: target ~ days_since_wash."""
    model = LinearRegression()
    model.fit(train[["days_since_wash"]].astype(float), train[target_col])
    return model


def fit_feature_model(model_name: str, x_train: pd.DataFrame, y_train: pd.Series) -> Any:
    """Fit RF or HistGradientBoosting with fixed hyperparameters (no test tuning)."""
    if model_name == MODEL_RANDOM_FOREST:
        model = _fixed_random_forest()
    elif model_name == MODEL_HIST_GB:
        model = _fixed_hist_gradient_boosting()
    else:
        raise ValueError(f"Unsupported feature model: {model_name}")
    model.fit(x_train, y_train)
    return model


def predict_model(
    model_name: str,
    train: pd.DataFrame,
    test: pd.DataFrame,
    target_col: str,
) -> np.ndarray:
    """Generate predictions for one model on a test fold or held-out set."""
    if model_name == MODEL_MEAN_BASELINE:
        return predict_mean_baseline(train, test, target_col)
    if model_name == MODEL_DAYS_SINCE_WASH:
        model = fit_days_since_wash_linear(train, target_col)
        return model.predict(test[["days_since_wash"]].astype(float))
    x_train, y_train = prepare_xy(train, target_col)
    x_test, _ = prepare_xy(test, target_col)
    model = fit_feature_model(model_name, x_train, y_train)
    return model.predict(x_test)


def blocked_cv_metrics(
    train: pd.DataFrame,
    target_col: str,
    model_name: str,
    n_splits: int | None = None,
) -> CvMetrics:
    """Blocked TimeSeriesSplit CV on the training span (time-ordered, not shuffled)."""
    splits = n_splits or config.ML_CV_SPLITS
    ordered = train.sort_values("date").reset_index(drop=True)
    tscv = TimeSeriesSplit(n_splits=splits)
    fold_mae: list[float] = []
    fold_rmse: list[float] = []
    fold_r2: list[float] = []
    for train_idx, val_idx in tscv.split(ordered):
        fold_train = ordered.iloc[train_idx]
        fold_val = ordered.iloc[val_idx]
        y_pred = predict_model(model_name, fold_train, fold_val, target_col)
        y_true = fold_val[target_col].to_numpy()
        mae, rmse, r2 = evaluate_model(y_true, y_pred)
        fold_mae.append(mae)
        fold_rmse.append(rmse)
        fold_r2.append(r2)

    def _std(values: list[float]) -> float:
        return float(np.std(values, ddof=1)) if len(values) > 1 else 0.0

    framing = (
        TARGET_SOILING_RATIO if target_col == TARGET_SOILING_RATIO else TARGET_ABSOLUTE
    )
    return CvMetrics(
        model_name=model_name,
        target_framing=framing,
        mae_mean=float(np.mean(fold_mae)),
        mae_std=_std(fold_mae),
        rmse_mean=float(np.mean(fold_rmse)),
        rmse_std=_std(fold_rmse),
        r2_mean=float(np.mean(fold_r2)),
        r2_std=_std(fold_r2),
        n_folds=len(fold_mae),
    )


def evaluate_test_models(
    split: TimeSplit,
    target_col: str,
) -> tuple[list[ModelMetrics], list[CvMetrics], RandomForestRegressor | None]:
    """Run all models for one target framing; return test metrics and CV table."""
    test_metrics: list[ModelMetrics] = []
    cv_metrics: list[CvMetrics] = []
    framing = (
        TARGET_SOILING_RATIO if target_col == TARGET_SOILING_RATIO else TARGET_ABSOLUTE
    )
    rf_model: RandomForestRegressor | None = None

    for model_name in ALL_MODELS:
        cv_metrics.append(blocked_cv_metrics(split.train, target_col, model_name))
        y_pred = predict_model(model_name, split.train, split.test, target_col)
        _, y_test = prepare_xy(split.test, target_col)
        mae, rmse, r2 = evaluate_model(y_test.to_numpy(), y_pred)
        test_metrics.append(
            ModelMetrics(
                model_name=model_name,
                target_framing=framing,
                mae=mae,
                rmse=rmse,
                r2=r2,
                n_train=len(split.train),
                n_test=len(split.test),
            )
        )
        if model_name == MODEL_RANDOM_FOREST:
            x_train, y_train = prepare_xy(split.train, target_col)
            rf_model = fit_feature_model(MODEL_RANDOM_FOREST, x_train, y_train)

    return test_metrics, cv_metrics, rf_model


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


def ml_beats_trend_verdict(
    rf_metrics: ModelMetrics,
    trend_metrics: ModelMetrics,
    rf_cv: CvMetrics,
) -> str:
    """Plain verdict on whether ML adds value over the simple soiling trend."""
    if rf_metrics.r2 <= trend_metrics.r2 + 0.01 and rf_metrics.mae >= trend_metrics.mae * 0.99:
        return (
            "Random Forest does **not** meaningfully beat the days_since_wash linear "
            "baseline on held-out test metrics. The simple physical trend model suffices."
        )
    if rf_cv.r2_mean < 0:
        return (
            "Random Forest modestly beats the trend baseline on the held-out window, "
            "but blocked CV R2 remains negative — treat ML gains as fragile."
        )
    return (
        "Random Forest beats the days_since_wash baseline on held-out R2/MAE with "
        "non-negative blocked CV R2; weather/pollution features add modest explanatory "
        "power beyond the linear trend."
    )


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
            "corroborates P3.5/P11 (pollution not a daily driver)."
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
        "pollution thesis, consistent with P3.5/P11."
    )


def _format_cv_cell(cv: CvMetrics, metric: str) -> str:
    if metric == "mae":
        return f"{cv.mae_mean:.5f} +/- {cv.mae_std:.5f}"
    if metric == "rmse":
        return f"{cv.rmse_mean:.5f} +/- {cv.rmse_std:.5f}"
    return f"{cv.r2_mean:.4f} +/- {cv.r2_std:.4f}"


def _metrics_row(model_name: str, metrics: ModelMetrics) -> str:
    return (
        f"| {model_name} | {metrics.mae:.5f} | {metrics.rmse:.5f} | {metrics.r2:.4f} |"
    )


def write_ml_results_report(
    absolute_test: list[ModelMetrics],
    absolute_cv: list[CvMetrics],
    ratio_test: list[ModelMetrics],
    ratio_cv: list[CvMetrics],
    ml_verdict: str,
    importance: pd.DataFrame | None,
    pollution_note: str,
    split: TimeSplit,
    importance_trusted: bool,
) -> None:
    """Write reports/ML_RESULTS.md with P12 reframed results and old-vs-new comparison."""
    path = config.REPORTS / "ML_RESULTS.md"
    abs_by_name = {m.model_name: m for m in absolute_test}
    ratio_by_name = {m.model_name: m for m in ratio_test}
    abs_cv_by = {m.model_name: m for m in absolute_cv}
    ratio_cv_by = {m.model_name: m for m in ratio_cv}

    lines = [
        "# P5/P12 Machine Learning Results",
        "",
        "## Target reframing (P12)",
        "",
        "**Old (P5):** predict absolute `pi_temp_corrected`. PI resets at each wash, so",
        "segment baseline shifts make this an unfair target (negative held-out R2).",
        "",
        "**New (P12):** predict `soiling_ratio = 100 * pi_temp_corrected / segment_baseline`,",
        "where `segment_baseline` is the P3 median of the first post-wash clean days",
        f"(`SOILING_BASELINE_CLEAN_DAYS={config.SOILING_BASELINE_CLEAN_DAYS}`). That",
        "baseline is operationally known right after a wash; it uses only each segment's",
        "own early post-wash days — not future PI — so this is realistic, not leakage.",
        "",
        "## Leakage control",
        "",
        "Features are exogenous only; **production and irradiation are excluded**",
        "because PI = production/irradiation would leak the target ratio.",
        "",
        f"Modelling frame: train={split.train.shape[0]}, test={split.test.shape[0]} "
        f"(time split at {split.split_date.date()}, latest "
        f"{split.test_fraction:.0%} held out). Pre-first-wash days excluded.",
        "",
        "## Blocked TimeSeriesSplit CV (train span only, mean +/- std)",
        "",
        "| framing | model | MAE | RMSE | R2 |",
        "|---|---|---:|---:|---:|",
    ]
    for framing_label, cv_map in (
        ("absolute PI", abs_cv_by),
        ("soiling_ratio", ratio_cv_by),
    ):
        for model_name in ALL_MODELS:
            cv = cv_map[model_name]
            lines.append(
                f"| {framing_label} | {model_name} | {_format_cv_cell(cv, 'mae')} | "
                f"{_format_cv_cell(cv, 'rmse')} | {_format_cv_cell(cv, 'r2')} |"
            )

    lines.extend(
        [
            "",
            "## Held-out test metrics (same chronological test window)",
            "",
            "| framing | model | MAE | RMSE | R2 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for model_name in ALL_MODELS:
        lines.append(
            f"| absolute PI | {model_name} | "
            f"{abs_by_name[model_name].mae:.5f} | {abs_by_name[model_name].rmse:.5f} | "
            f"{abs_by_name[model_name].r2:.4f} |"
        )
    for model_name in ALL_MODELS:
        lines.append(
            f"| soiling_ratio | {model_name} | "
            f"{ratio_by_name[model_name].mae:.5f} | {ratio_by_name[model_name].rmse:.5f} | "
            f"{ratio_by_name[model_name].r2:.4f} |"
        )

    lines.extend(
        [
            "",
            "## Why scores changed",
            "",
            f"Absolute-PI RF test R2 = {abs_by_name[MODEL_RANDOM_FOREST].r2:.4f}; "
            f"soiling_ratio RF test R2 = {ratio_by_name[MODEL_RANDOM_FOREST].r2:.4f}. "
            "Reframing removes segment-level level shifts so the ML task aligns with "
            "within-segment soiling physics.",
            "",
            "## ML vs simple trend (soiling_ratio framing)",
            "",
            ml_verdict,
            "",
        ]
    )

    if importance_trusted and importance is not None:
        lines.extend(
            [
                "## Permutation importance (soiling_ratio RF, test set)",
                "",
                "Reported because blocked CV R2 mean is non-negative.",
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
        lines.extend(["", "## Pollution verdict", "", pollution_note, ""])
    else:
        rf_cv = ratio_cv_by[MODEL_RANDOM_FOREST]
        lines.extend(
            [
                "## Permutation importance",
                "",
                f"Skipped: blocked CV R2 mean = {rf_cv.r2_mean:.4f} (negative or NaN). "
                "Permutation importances are only trustworthy when the model generalizes.",
                "",
            ]
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


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
    ax.set_title("P12 RF permutation importance (soiling_ratio target)")
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
    target_col: str,
) -> None:
    """Time-ordered predicted vs actual on held-out test."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    test = split.test.copy()
    test["predicted"] = y_pred
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(test["date"], test[target_col], label="actual", color="C0")
    ax.plot(test["date"], test["predicted"], label="predicted", color="C1", alpha=0.8)
    ax.set_xlabel("Date")
    ax.set_ylabel(target_col)
    ax.set_title(f"P12 RF: predicted vs actual {target_col} (held-out test)")
    ax.legend()
    fig.tight_layout()
    png = config.FIGURES / "ml_predicted_vs_actual.png"
    csv = config.FIGURES / "ml_predicted_vs_actual.csv"
    fig.savefig(png, dpi=300)
    plt.close(fig)
    test[["date", target_col, "predicted"]].to_csv(csv, index=False)
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


def persist_model(model: RandomForestRegressor, features: list[str]) -> None:
    """Save fitted model and feature list for reproducibility."""
    model_path = config.DATA_PROCESSED / config.ML_MODEL_FILENAME
    feature_path = config.DATA_PROCESSED / config.ML_FEATURES_FILENAME
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    feature_path.write_text(json.dumps(features, indent=2), encoding="utf-8")
    LOGGER.info("Saved model to %s and features to %s", model_path, feature_path)


def build_metrics_parquet(
    absolute_test: list[ModelMetrics],
    absolute_cv: list[CvMetrics],
    ratio_test: list[ModelMetrics],
    ratio_cv: list[CvMetrics],
    ml_verdict: str,
    pollution_note: str,
    split: TimeSplit,
    importance: pd.DataFrame | None,
) -> pd.DataFrame:
    """Assemble ml_model_metrics.parquet rows."""
    rows: list[dict[str, Any]] = [
        {
            "record_type": "split_info",
            "split_date": split.split_date,
            "test_fraction": split.test_fraction,
            "n_train": len(split.train),
            "n_test": len(split.test),
            "primary_target": TARGET_SOILING_RATIO,
        },
        {
            "record_type": "ml_verdict",
            "target_framing": TARGET_SOILING_RATIO,
            "verdict": ml_verdict,
        },
        {
            "record_type": "pollution_verdict",
            "target_framing": TARGET_SOILING_RATIO,
            "verdict": pollution_note,
        },
    ]

    def _append_metrics(test: list[ModelMetrics], cv: list[CvMetrics]) -> None:
        cv_map = {item.model_name: item for item in cv}
        for item in test:
            cv_item = cv_map[item.model_name]
            rows.append(
                {
                    "record_type": "test_metrics",
                    "model_name": item.model_name,
                    "target_framing": item.target_framing,
                    "mae": item.mae,
                    "rmse": item.rmse,
                    "r2": item.r2,
                    "n_train": item.n_train,
                    "n_test": item.n_test,
                }
            )
            rows.append(
                {
                    "record_type": "cv_metrics",
                    "model_name": cv_item.model_name,
                    "target_framing": cv_item.target_framing,
                    "mae_mean": cv_item.mae_mean,
                    "mae_std": cv_item.mae_std,
                    "rmse_mean": cv_item.rmse_mean,
                    "rmse_std": cv_item.rmse_std,
                    "r2_mean": cv_item.r2_mean,
                    "r2_std": cv_item.r2_std,
                    "n_folds": cv_item.n_folds,
                }
            )

    _append_metrics(absolute_test, absolute_cv)
    _append_metrics(ratio_test, ratio_cv)

    if importance is not None:
        for _, row in importance.iterrows():
            rows.append(
                {
                    "record_type": "permutation_importance",
                    "target_framing": TARGET_SOILING_RATIO,
                    **row.to_dict(),
                }
            )
    return pd.DataFrame(rows)


def run_ml_analysis() -> dict[str, Any]:
    """Execute P5/P12 ML analysis end-to-end."""
    master = read_processed(MASTER_INPUT_NAME)
    segments = read_processed(SOILING_OUTPUT_NAME)
    robustness_path = config.DATA_PROCESSED / "soiling_robustness.parquet"
    robustness = (
        read_processed("soiling_robustness") if robustness_path.exists() else None
    )

    frame = build_modelling_frame(master, segments)
    split = time_based_split(frame)

    absolute_test, absolute_cv, _ = evaluate_test_models(split, TARGET_ABSOLUTE)
    ratio_test, ratio_cv, rf_model = evaluate_test_models(split, TARGET_SOILING_RATIO)

    ratio_by_name = {m.model_name: m for m in ratio_test}
    ratio_cv_by = {m.model_name: m for m in ratio_cv}
    rf_test = ratio_by_name[MODEL_RANDOM_FOREST]
    trend_test = ratio_by_name[MODEL_DAYS_SINCE_WASH]
    rf_cv = ratio_cv_by[MODEL_RANDOM_FOREST]

    ml_verdict = ml_beats_trend_verdict(rf_test, trend_test, rf_cv)
    importance_trusted = rf_cv.r2_mean >= 0 and not np.isnan(rf_cv.r2_mean)
    importance: pd.DataFrame | None = None
    pollution_note = (
        "Permutation importance skipped (blocked CV R2 negative); "
        "consistent with weak ML generalization."
    )

    if importance_trusted and rf_model is not None:
        x_test, y_test = prepare_xy(split.test, TARGET_SOILING_RATIO)
        importance = permutation_importance_with_ci(rf_model, x_test, y_test)
        pollution_note = pollution_verdict(importance)

    metrics_df = build_metrics_parquet(
        absolute_test,
        absolute_cv,
        ratio_test,
        ratio_cv,
        ml_verdict,
        pollution_note,
        split,
        importance,
    )
    write_processed(config.ML_METRICS_OUTPUT_NAME, metrics_df)

    if rf_model is not None:
        persist_model(rf_model, list(FEATURE_COLUMNS))
        rf_pred = rf_model.predict(prepare_xy(split.test, TARGET_SOILING_RATIO)[0])
        plot_predicted_vs_actual(split, rf_pred, TARGET_SOILING_RATIO)
        if importance_trusted and importance is not None:
            plot_permutation_importance(importance)
            x_train, _ = prepare_xy(split.train, TARGET_SOILING_RATIO)
            p35_rate = p35_soiling_rate_pct(segments, robustness)
            plot_partial_dependence(
                rf_model, x_train, "days_since_wash", p35_rate_pct=p35_rate
            )
            top_pollutant = importance.loc[
                importance["feature"].isin(POLLUTION_FEATURES)
            ].iloc[0]["feature"]
            plot_partial_dependence(
                rf_model,
                x_train,
                top_pollutant,
                filename_suffix="top_pollutant",
            )

    write_ml_results_report(
        absolute_test,
        absolute_cv,
        ratio_test,
        ratio_cv,
        ml_verdict,
        importance,
        pollution_note,
        split,
        importance_trusted,
    )

    abs_rf = next(m for m in absolute_test if m.model_name == MODEL_RANDOM_FOREST)
    LOGGER.info(
        "P12 soiling_ratio RF test MAE=%.5f R2=%.4f (CV R2=%.4f +/- %.4f); "
        "absolute PI RF test R2=%.4f",
        rf_test.mae,
        rf_test.r2,
        rf_cv.r2_mean,
        rf_cv.r2_std,
        abs_rf.r2,
    )

    return {
        "absolute_test": absolute_test,
        "ratio_test": ratio_test,
        "ratio_cv": ratio_cv,
        "ml_verdict": ml_verdict,
        "importance": importance,
        "split": split,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_ml_analysis()
