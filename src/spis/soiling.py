"""Per-segment soiling rate and washing recovery analysis.

Rain handling (methodology rule): soiling slopes are fit only on **rain-free**
clean observations within each segment. Rain days are excluded from the robust
regression so a single line is not pulled across natural washing events; rain days
remain visible on segment plots. This implements option (a) from the methodology.

Baseline rule: within each post-wash segment, ``baseline`` is the median
``pi_temp_corrected`` of the first ``SOILING_BASELINE_CLEAN_DAYS`` clean days with
the smallest ``days_since_wash`` values strictly after the wash window. All segment
PI values are expressed as ``soiling_ratio = 100 * pi / baseline``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import r2_score

from spis import config
from spis.io import read_interim, read_processed, write_processed

LOGGER = logging.getLogger(__name__)

SOILING_OUTPUT_NAME = "soiling_segments"
MASTER_INPUT_NAME = "master_daily"


@dataclass(frozen=True)
class SegmentFit:
    """Container for one segment's soiling fit outputs."""

    segment_id: int
    slope_pct_per_day: float
    intercept: float
    ci_lower: float
    ci_upper: float
    r2: float
    n_fit: int
    baseline_pi_temp: float
    baseline_pi_raw: float
    slope_raw_pct_per_day: float


def season_label(dates: pd.Series) -> str:
    """Assign a meteorological season label from the month of the segment midpoint."""
    midpoint = dates.median()
    month = int(pd.Timestamp(midpoint).month)
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def prepare_segment_frame(master: pd.DataFrame) -> pd.DataFrame:
    """Return clean observations for segments with segment_id >= 1."""
    frame = master.loc[master["segment_id"].notna() & (master["segment_id"] > 0)].copy()
    LOGGER.info(
        "Segment prep: excluded segment 0 (%s days); retained %s segment-tagged days",
        int((master["segment_id"] == 0).sum()),
        len(frame),
    )
    return frame


def segment_clean_days(master: pd.DataFrame, segment_id: int) -> pd.DataFrame:
    """Clean observations for one segment."""
    mask = (master["segment_id"] == segment_id) & master["is_clean_observation"]
    return master.loc[mask].sort_values("days_since_wash")


def compute_baseline(clean: pd.DataFrame, value_col: str) -> float:
    """Median of the first N clean days after wash by days_since_wash."""
    positive = clean.loc[clean["days_since_wash"] > 0].sort_values("days_since_wash")
    head = positive.head(config.SOILING_BASELINE_CLEAN_DAYS)
    if len(head) < config.SOILING_BASELINE_CLEAN_DAYS:
        head = positive.head(max(1, len(positive)))
    if head.empty:
        raise ValueError("Cannot compute baseline without post-wash clean days")
    return float(head[value_col].median())


def rain_free_clean(clean: pd.DataFrame) -> pd.DataFrame:
    """Clean days excluding rain (used for robust slope fitting)."""
    return clean.loc[~clean["rain_day"]].copy()


def fit_segment_slope(
    clean: pd.DataFrame,
    baseline_temp: float,
    baseline_raw: float,
    segment_id: int,
    *,
    day_mask: pd.Series | None = None,
) -> SegmentFit:
    """Fit Theil-Sen slope of soiling ratio vs days_since_wash on rain-free clean days."""
    fit_frame = rain_free_clean(clean)
    fit_frame = fit_frame.loc[fit_frame["days_since_wash"] > 0].copy()
    if day_mask is not None:
        fit_frame = fit_frame.loc[day_mask.loc[fit_frame.index]].copy()
    fit_frame["soiling_ratio"] = 100.0 * fit_frame["pi_temp_corrected"] / baseline_temp
    fit_frame["soiling_ratio_raw"] = 100.0 * fit_frame["pi"] / baseline_raw

    if len(fit_frame) < 2:
        return SegmentFit(
            segment_id=segment_id,
            slope_pct_per_day=float("nan"),
            intercept=float("nan"),
            ci_lower=float("nan"),
            ci_upper=float("nan"),
            r2=float("nan"),
            n_fit=len(fit_frame),
            baseline_pi_temp=baseline_temp,
            baseline_pi_raw=baseline_raw,
            slope_raw_pct_per_day=float("nan"),
        )

    x_flat = fit_frame["days_since_wash"].to_numpy(dtype=float)
    y = fit_frame["soiling_ratio"].to_numpy(dtype=float)
    ts = stats.theilslopes(y, x_flat)
    slope = float(ts.slope)
    intercept = float(ts.intercept)
    ci_lower = float(ts.low_slope)
    ci_upper = float(ts.high_slope)
    y_pred = intercept + slope * x_flat
    r2 = float(r2_score(y, y_pred))

    raw_ts = stats.theilslopes(
        fit_frame["soiling_ratio_raw"].to_numpy(dtype=float),
        x_flat,
    )
    slope_raw = float(raw_ts.slope)

    return SegmentFit(
        segment_id=segment_id,
        slope_pct_per_day=slope,
        intercept=intercept,
        ci_lower=float(ci_lower),
        ci_upper=float(ci_upper),
        r2=r2,
        n_fit=len(fit_frame),
        baseline_pi_temp=baseline_temp,
        baseline_pi_raw=baseline_raw,
        slope_raw_pct_per_day=slope_raw,
    )


def compute_wash_recovery(
    master: pd.DataFrame,
    washing: pd.DataFrame,
    wash_index: int,
) -> dict[str, Any]:
    """Recovery across one wash using pre/post clean-day windows."""
    event = washing.sort_values("start").iloc[wash_index]
    window = config.SOILING_RECOVERY_WINDOW_DAYS
    before = master.loc[
        (master["date"] < event["start"]) & master["is_clean_observation"] & (~master["rain_day"])
    ].sort_values("date")
    after = master.loc[
        (master["date"] > event["end"]) & master["is_clean_observation"] & (~master["rain_day"])
    ].sort_values("date")

    before_window = before.tail(window)
    after_window = after.head(window)
    if before_window.empty or after_window.empty:
        return {
            "event_index_by_date": int(event["event_index_by_date"]),
            "recovery_abs": float("nan"),
            "recovery_pct": float("nan"),
            "recovery_positive": False,
            "recovery_note": "insufficient clean days in before/after windows",
        }

    before_median = float(before_window["pi_temp_corrected"].median())
    after_median = float(after_window["pi_temp_corrected"].median())
    recovery_abs = after_median - before_median
    recovery_pct = 100.0 * recovery_abs / before_median if before_median else float("nan")
    positive = recovery_abs > 0
    note = "" if positive else "recovery not positive; check wash overlap with exclusions"
    return {
        "event_index_by_date": int(event["event_index_by_date"]),
        "recovery_abs": recovery_abs,
        "recovery_pct": recovery_pct,
        "recovery_positive": positive,
        "recovery_note": note,
        "before_median_pi_temp": before_median,
        "after_median_pi_temp": after_median,
    }


def pollution_accumulation(clean: pd.DataFrame) -> dict[str, float]:
    """Sum CAMS pollution variables over clean days in a segment."""
    return {
        "pm10_accumulated": float(clean["pm10"].sum(skipna=True)),
        "dust_accumulated": float(clean["dust"].sum(skipna=True)),
        "aod_accumulated": float(clean["aerosol_optical_depth"].sum(skipna=True)),
    }


def correlation_with_ci(x: pd.Series, y: pd.Series) -> dict[str, float]:
    """Pearson correlation with bootstrap CI across segment-level pairs."""
    valid = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(valid) < 3:
        return {
            "r": float("nan"),
            "p": float("nan"),
            "ci_lower": float("nan"),
            "ci_upper": float("nan"),
        }
    r, p = stats.pearsonr(valid["x"], valid["y"])
    rng = np.random.default_rng(config.RANDOM_STATE)
    boot_r: list[float] = []
    values = valid.to_numpy()
    for _ in range(config.SOILING_BOOTSTRAP_SAMPLES):
        idx = rng.integers(0, len(values), len(values))
        sample = values[idx]
        boot_r.append(stats.pearsonr(sample[:, 0], sample[:, 1]).statistic)
    ci_lower, ci_upper = np.percentile(boot_r, [2.5, 97.5])
    return {
        "r": float(r),
        "p": float(p),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "n": float(len(valid)),
    }


def build_soiling_segments(master: pd.DataFrame, washing: pd.DataFrame) -> pd.DataFrame:
    """Build one summary row per post-wash segment."""
    segment_ids = sorted(int(v) for v in master["segment_id"].dropna().unique() if int(v) > 0)
    rows: list[dict[str, Any]] = []
    recoveries = {
        int(item["event_index_by_date"]): item
        for item in (compute_wash_recovery(master, washing, idx) for idx in range(len(washing)))
    }

    for segment_id in segment_ids:
        seg_all = master.loc[master["segment_id"] == segment_id]
        clean = segment_clean_days(master, segment_id)
        n_clean = len(clean)
        low_confidence = n_clean < config.SOILING_MIN_CLEAN_DAYS
        if low_confidence:
            LOGGER.warning(
                "Segment %s: only %s clean days (< %s); low_confidence=True",
                segment_id,
                n_clean,
                config.SOILING_MIN_CLEAN_DAYS,
            )

        baseline_temp = compute_baseline(clean, "pi_temp_corrected")
        baseline_raw = compute_baseline(clean, "pi")
        fit = fit_segment_slope(clean, baseline_temp, baseline_raw, segment_id)
        pollution = pollution_accumulation(clean)
        recovery = recoveries.get(segment_id, {})

        rows.append(
            {
                "segment_id": segment_id,
                "date_start": seg_all["date"].min(),
                "date_end": seg_all["date"].max(),
                "season": season_label(clean["date"]),
                "washing_method": seg_all["washing_method"].dropna().iloc[0]
                if seg_all["washing_method"].notna().any()
                else pd.NA,
                "is_open_segment": bool(seg_all["is_open_segment"].any()),
                "n_clean_days": n_clean,
                "n_fit_rain_free": fit.n_fit,
                "baseline_pi_temp_corrected": fit.baseline_pi_temp,
                "baseline_pi_raw": fit.baseline_pi_raw,
                "soiling_rate_pct_per_day": fit.slope_pct_per_day,
                "soiling_rate_ci_lower": fit.ci_lower,
                "soiling_rate_ci_upper": fit.ci_upper,
                "soiling_rate_r2": fit.r2,
                "soiling_rate_raw_pi_pct_per_day": fit.slope_raw_pct_per_day,
                "recovery_abs": recovery.get("recovery_abs"),
                "recovery_pct": recovery.get("recovery_pct"),
                "recovery_positive": recovery.get("recovery_positive"),
                "recovery_note": recovery.get("recovery_note", ""),
                "low_confidence": low_confidence,
                "unexpected_positive_slope": fit.slope_pct_per_day >= 0
                if not pd.isna(fit.slope_pct_per_day)
                else False,
                **pollution,
            }
        )

    return pd.DataFrame(rows)


def pooled_soiling_rate(segments: pd.DataFrame) -> dict[str, float]:
    """Variance-weighted pooled rate excluding low-confidence segments."""
    valid = segments.loc[~segments["low_confidence"]].dropna(
        subset=["soiling_rate_pct_per_day", "n_fit_rain_free"]
    )
    if valid.empty:
        return {
            "pooled_rate": float("nan"),
            "pooled_ci_lower": float("nan"),
            "pooled_ci_upper": float("nan"),
        }
    weights = valid["n_fit_rain_free"].to_numpy(dtype=float)
    rates = valid["soiling_rate_pct_per_day"].to_numpy(dtype=float)
    pooled = float(np.average(rates, weights=weights))
    var = float(np.average((rates - pooled) ** 2, weights=weights))
    se = float(np.sqrt(var / len(valid)))
    return {
        "pooled_rate": pooled,
        "pooled_ci_lower": pooled - 1.96 * se,
        "pooled_ci_upper": pooled + 1.96 * se,
        "n_segments": float(len(valid)),
    }


def seasonal_rates(segments: pd.DataFrame) -> pd.DataFrame:
    """Aggregate soiling rate by season with mean and bootstrap CI."""
    valid = segments.loc[~segments["low_confidence"]].dropna(subset=["soiling_rate_pct_per_day"])
    rows: list[dict[str, Any]] = []
    for season, group in valid.groupby("season"):
        rates = group["soiling_rate_pct_per_day"].to_numpy(dtype=float)
        rows.append(
            {
                "season": season,
                "mean_rate_pct_per_day": float(np.mean(rates)),
                "ci_lower": float(np.percentile(rates, 2.5)) if len(rates) > 1 else float(rates[0]),
                "ci_upper": float(np.percentile(rates, 97.5))
                if len(rates) > 1
                else float(rates[0]),
                "n_segments": int(len(group)),
            }
        )
    return pd.DataFrame(rows)


def p4_recommendation(segments: pd.DataFrame, seasonal: pd.DataFrame) -> dict[str, Any]:
    """Recommend a soiling rate for P4 optimization."""
    pooled = pooled_soiling_rate(segments)
    summer = seasonal.loc[seasonal["season"] == "summer"]
    winter = seasonal.loc[seasonal["season"] == "winter"]
    summer_rate = (
        float(summer["mean_rate_pct_per_day"].iloc[0]) if not summer.empty else float("nan")
    )
    winter_rate = (
        float(winter["mean_rate_pct_per_day"].iloc[0]) if not winter.empty else float("nan")
    )
    return {
        **pooled,
        "summer_rate_pct_per_day": summer_rate,
        "winter_rate_pct_per_day": winter_rate,
        "p4_recommended_rate_pct_per_day": summer_rate
        if not np.isnan(summer_rate)
        else pooled["pooled_rate"],
        "p4_rationale": (
            "Use the summer segment mean rate for P4 scheduling because soiling loss "
            "accumulates fastest in dry summer months when wash timing is most costly; "
            "pooled rate is reported as a conservative cross-season fallback."
        ),
    }


def _save_figure(name: str, fig: plt.Figure, plot_frame: pd.DataFrame) -> None:
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    png_path = config.FIGURES / f"{name}.png"
    csv_path = config.FIGURES / f"{name}.csv"
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    plot_frame.to_csv(csv_path, index=False)
    LOGGER.info("Saved figure %s", png_path)


def plot_timeline(master: pd.DataFrame, segments: pd.DataFrame, washing: pd.DataFrame) -> None:
    """PI timeline with wash lines, rain markers, and fitted segment slopes."""
    plot_rows: list[dict[str, Any]] = []
    fig, ax = plt.subplots(figsize=(12, 5))
    clean = master.loc[master["is_clean_observation"] & (master["segment_id"] > 0)]
    ax.plot(
        master["date"],
        master["pi_temp_corrected"],
        color="0.85",
        linewidth=0.8,
        label="All days",
    )
    ax.scatter(
        clean.loc[~clean["rain_day"], "date"],
        clean.loc[~clean["rain_day"], "pi_temp_corrected"],
        s=8,
        c="tab:blue",
        label="Clean, rain-free",
    )
    ax.scatter(
        clean.loc[clean["rain_day"], "date"],
        clean.loc[clean["rain_day"], "pi_temp_corrected"],
        s=12,
        c="tab:cyan",
        marker="x",
        label="Rain day (clean)",
    )
    for _, wash in washing.iterrows():
        ax.axvline(wash["end"], color="tab:green", linestyle="--", alpha=0.4)

    for _, seg in segments.iterrows():
        sid = int(seg["segment_id"])
        if pd.isna(seg["soiling_rate_pct_per_day"]):
            continue
        seg_clean = rain_free_clean(segment_clean_days(master, sid))
        seg_clean = seg_clean.loc[seg_clean["days_since_wash"] > 0].copy()
        if seg_clean.empty:
            continue
        baseline = float(seg["baseline_pi_temp_corrected"])
        slope = float(seg["soiling_rate_pct_per_day"])
        intercept = 100.0 - slope * float(seg_clean["days_since_wash"].min())
        seg_clean["fitted_pi_temp"] = (
            baseline * (intercept + slope * seg_clean["days_since_wash"]) / 100.0
        )
        ax.plot(
            seg_clean["date"],
            seg_clean["fitted_pi_temp"],
            color="tab:red",
            linewidth=1.2,
            alpha=0.8,
        )
        for _, row in seg_clean.iterrows():
            plot_rows.append(
                {
                    "date": row["date"],
                    "pi_temp_corrected": row["pi_temp_corrected"],
                    "fitted_pi_temp": row["fitted_pi_temp"],
                    "segment_id": sid,
                    "rain_day": bool(row["rain_day"]),
                }
            )

    ax.set_title("Temperature-corrected PI with wash events and rain-free segment slopes")
    ax.set_xlabel("Date")
    ax.set_ylabel("PI (temp corrected)")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    _save_figure("soiling_timeline_slopes", fig, pd.DataFrame(plot_rows))


def plot_segment_rates(segments: pd.DataFrame) -> None:
    """Soiling rate by segment with error bars, colored by season."""
    plot_frame = segments.sort_values("segment_id").copy()
    season_colors = {
        "spring": "tab:green",
        "summer": "tab:red",
        "autumn": "tab:orange",
        "winter": "tab:blue",
    }
    colors = plot_frame["season"].map(season_colors).fillna("0.5")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.errorbar(
        plot_frame["segment_id"],
        plot_frame["soiling_rate_pct_per_day"],
        yerr=[
            plot_frame["soiling_rate_pct_per_day"] - plot_frame["soiling_rate_ci_lower"],
            plot_frame["soiling_rate_ci_upper"] - plot_frame["soiling_rate_pct_per_day"],
        ],
        fmt="o",
        ecolor="0.3",
        capsize=4,
        linestyle="none",
    )
    for sid, rate, color in zip(
        plot_frame["segment_id"],
        plot_frame["soiling_rate_pct_per_day"],
        colors,
        strict=True,
    ):
        ax.scatter(sid, rate, c=[color], s=60, zorder=3)
    ax.axhline(0, color="0.5", linewidth=0.8)
    ax.set_xlabel("Segment ID")
    ax.set_ylabel("Soiling rate (%/day)")
    ax.set_title("Robust soiling rate by segment (rain-free clean days)")
    fig.tight_layout()
    _save_figure("soiling_rate_by_segment", fig, plot_frame)


def plot_recovery(recovery_rows: pd.DataFrame) -> None:
    """Recovery per wash event."""
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(recovery_rows["event_index_by_date"], recovery_rows["recovery_pct"], color="tab:purple")
    ax.axhline(0, color="0.4", linewidth=0.8)
    ax.set_xlabel("Wash event (date order)")
    ax.set_ylabel("Recovery (% vs pre-wash median)")
    ax.set_title("Washing recovery (temp-corrected PI)")
    fig.tight_layout()
    _save_figure("soiling_recovery_by_wash", fig, recovery_rows)


def plot_pollution_scatter(segments: pd.DataFrame) -> None:
    """Soiling rate vs accumulated PM10/dust."""
    valid = segments.dropna(subset=["soiling_rate_pct_per_day", "pm10_accumulated"])
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(valid["pm10_accumulated"], valid["soiling_rate_pct_per_day"], s=60)
    ax.scatter(valid["dust_accumulated"], valid["soiling_rate_pct_per_day"], s=60, marker="x")
    if len(valid) >= 3:
        slope, intercept, _, _, _ = stats.linregress(
            valid["pm10_accumulated"], valid["soiling_rate_pct_per_day"]
        )
        x_line = np.linspace(valid["pm10_accumulated"].min(), valid["pm10_accumulated"].max(), 50)
        ax.plot(x_line, intercept + slope * x_line, color="tab:red", label="PM10 linear fit")
    ax.set_xlabel("Accumulated PM10 over segment clean days (ug/m3 * days)")
    ax.set_ylabel("Soiling rate (%/day)")
    ax.set_title("Association: segment soiling rate vs accumulated PM10")
    ax.legend()
    fig.tight_layout()
    _save_figure("soiling_rate_vs_pm10", fig, valid)


def run_soiling_analysis() -> dict[str, Any]:
    """Execute the full P3 soiling workflow."""
    master = read_processed(MASTER_INPUT_NAME)
    washing = read_interim("washing_events")
    segments = build_soiling_segments(master, washing)
    seasonal = seasonal_rates(segments)
    p4 = p4_recommendation(segments, seasonal)

    pollution_corr = {
        "pm10": correlation_with_ci(
            segments["pm10_accumulated"], segments["soiling_rate_pct_per_day"]
        ),
        "dust": correlation_with_ci(
            segments["dust_accumulated"], segments["soiling_rate_pct_per_day"]
        ),
        "aod": correlation_with_ci(
            segments["aod_accumulated"], segments["soiling_rate_pct_per_day"]
        ),
    }

    recovery_rows = pd.DataFrame(
        [compute_wash_recovery(master, washing, idx) for idx in range(len(washing))]
    )

    write_processed(SOILING_OUTPUT_NAME, segments)
    plot_timeline(master, segments, washing)
    plot_segment_rates(segments)
    plot_recovery(recovery_rows)
    plot_pollution_scatter(segments)

    LOGGER.info("P4 recommendation: %s", p4)
    LOGGER.info("Pollution correlation (association, not causation): %s", pollution_corr)

    return {
        "segments": segments,
        "seasonal": seasonal,
        "p4": p4,
        "pollution_corr": pollution_corr,
        "recovery_rows": recovery_rows,
    }
