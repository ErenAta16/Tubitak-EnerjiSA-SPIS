"""P6 descriptive inverter relative-performance anomaly detection (Canakkale)."""

from __future__ import annotations

import logging
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from spis import config
from spis.io import read_interim, write_processed

LOGGER = logging.getLogger(__name__)

INVERTER_ANOMALY_OUTPUT = "inverter_anomaly"
MEANINGFUL_METEO_WH_M2 = 500.0
UNDERPERFORMER_MEDIAN_THRESHOLD = 0.95
UNDERPERFORMER_FRACTION_THRESHOLD = 0.25


def compute_relative_performance(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize each inverter to the cross-inverter median on meaningful-irradiance days."""
    deduped = frame.groupby(["date", "inverter"], as_index=False).agg(
        active_power=("active_power", "max"),
        meteo_irradiance=("meteo_irradiance", "max"),
    )
    meaningful = deduped.loc[
        (deduped["meteo_irradiance"] >= MEANINGFUL_METEO_WH_M2) & (deduped["active_power"] > 0)
    ].copy()
    if meaningful.empty:
        raise ValueError("No rows meet meaningful irradiance and production thresholds")

    daily_median = (
        meaningful.groupby("date", as_index=False)["active_power"]
        .median()
        .rename(columns={"active_power": "daily_cross_median_power"})
    )
    daily_median = daily_median.loc[daily_median["daily_cross_median_power"] > 0]
    merged = meaningful.merge(daily_median, on="date", how="inner")
    merged["relative_performance"] = merged["active_power"] / merged["daily_cross_median_power"]
    if (merged["relative_performance"] <= 0).any():
        raise ValueError("relative_performance must be positive")
    return merged.sort_values(["date", "inverter"]).reset_index(drop=True)


def rank_inverters(relative: pd.DataFrame) -> pd.DataFrame:
    """Rank inverters by median relative performance and flag underperformers."""
    summary = (
        relative.groupby("inverter", as_index=False)
        .agg(
            median_relative=("relative_performance", "median"),
            mean_relative=("relative_performance", "mean"),
            std_relative=("relative_performance", "std"),
            n_days=("relative_performance", "count"),
            fraction_below_threshold=(
                "relative_performance",
                lambda s: float((s < UNDERPERFORMER_MEDIAN_THRESHOLD).mean()),
            ),
        )
        .sort_values("median_relative", ascending=False)
        .reset_index(drop=True)
    )
    summary["rank"] = range(1, len(summary) + 1)
    summary["candidate_underperformer"] = (
        summary["median_relative"] < UNDERPERFORMER_MEDIAN_THRESHOLD
    ) & (summary["fraction_below_threshold"] >= UNDERPERFORMER_FRACTION_THRESHOLD)
    summary["analysis_note"] = "Descriptive peer comparison only; not fault diagnosis."
    return summary


def write_inverter_anomaly_report(summary: pd.DataFrame, relative: pd.DataFrame) -> None:
    """Write INVERTER_ANOMALY.md."""
    path = config.REPORTS / "INVERTER_ANOMALY.md"
    flagged = summary.loc[summary["candidate_underperformer"]]
    lines = [
        "# Inverter relative-performance screening (Canakkale)",
        "",
        "## Method (descriptive, not diagnostic)",
        "",
        f"- Days with meteo irradiance >= {MEANINGFUL_METEO_WH_M2:.0f} Wh/m2/day only.",
        "- Each inverter daily output divided by the cross-inverter median that day.",
        f"- Candidate underperformer if median relative < {UNDERPERFORMER_MEDIAN_THRESHOLD:.2f} "
        f"and >= {UNDERPERFORMER_FRACTION_THRESHOLD:.0%} of days below threshold.",
        "- **This ranks peers; it does not diagnose root cause (soiling, fault, curtailment).**",
        "",
        "## Ranking (best to worst median relative performance)",
        "",
        "| Rank | Inverter | Median rel. | Mean rel. | Days | Frac below thresh | Flag |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for _, row in summary.iterrows():
        flag = "candidate" if row["candidate_underperformer"] else "-"
        lines.append(
            f"| {int(row['rank'])} | {row['inverter']} | {row['median_relative']:.3f} | "
            f"{row['mean_relative']:.3f} | {int(row['n_days'])} | "
            f"{row['fraction_below_threshold']:.2%} | {flag} |"
        )

    lines.extend(
        [
            "",
            "## Candidate underperformers",
            "",
        ]
    )
    if flagged.empty:
        lines.append("None flagged at the documented thresholds.")
    else:
        for _, row in flagged.iterrows():
            lines.append(f"- **{row['inverter']}**: median relative {row['median_relative']:.3f}")

    lines.extend(
        [
            "",
            f"- Window: {relative['date'].min().date()} .. {relative['date'].max().date()}",
            f"- Meaningful-irradiance day-rows: {len(relative)}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def save_inverter_anomaly_figures(relative: pd.DataFrame, summary: pd.DataFrame) -> None:
    """Write time-series and ranking bar figures."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 5))
    for inverter, group in relative.groupby("inverter"):
        ax.plot(group["date"], group["relative_performance"], label=inverter, alpha=0.8)
    ax.axhline(1.0, color="black", linestyle="--", linewidth=0.8, label="peer median")
    ax.axhline(
        UNDERPERFORMER_MEDIAN_THRESHOLD,
        color="red",
        linestyle=":",
        linewidth=0.8,
        label=f"threshold={UNDERPERFORMER_MEDIAN_THRESHOLD}",
    )
    ax.set_ylabel("Relative performance (vs daily peer median)")
    ax.set_title("Canakkale inverter relative performance over time (descriptive)")
    ax.legend(ncol=3, fontsize=8)
    fig.autofmt_xdate()
    ts_png = config.FIGURES / "inverter_relative_performance_timeseries.png"
    ts_csv = config.FIGURES / "inverter_relative_performance_timeseries.csv"
    fig.savefig(ts_png, dpi=300, bbox_inches="tight")
    plt.close(fig)
    relative[["date", "inverter", "relative_performance", "meteo_irradiance"]].to_csv(
        ts_csv, index=False
    )

    fig, ax = plt.subplots(figsize=(8, 4))
    colors = ["C3" if flag else "C0" for flag in summary["candidate_underperformer"]]
    ax.bar(summary["inverter"], summary["median_relative"], color=colors)
    ax.axhline(1.0, color="black", linestyle="--", linewidth=0.8)
    ax.axhline(
        UNDERPERFORMER_MEDIAN_THRESHOLD,
        color="red",
        linestyle=":",
        linewidth=0.8,
    )
    ax.set_ylabel("Median relative performance")
    ax.set_title("Inverter ranking by median relative performance")
    rank_png = config.FIGURES / "inverter_relative_performance_ranking.png"
    rank_csv = config.FIGURES / "inverter_relative_performance_ranking.csv"
    fig.savefig(rank_png, dpi=300, bbox_inches="tight")
    plt.close(fig)
    summary.to_csv(rank_csv, index=False)


def run_inverter_anomaly_analysis() -> dict[str, Any]:
    """Execute Phase C descriptive inverter screening."""
    raw = read_interim("inverter_daily_long")
    relative = compute_relative_performance(raw)
    summary = rank_inverters(relative)

    detail = relative.copy()
    detail["record_type"] = "daily_relative"
    summary_export = summary.copy()
    summary_export["record_type"] = "inverter_summary"
    export = pd.concat([detail, summary_export], ignore_index=True, sort=False)
    write_processed(INVERTER_ANOMALY_OUTPUT, export)

    write_inverter_anomaly_report(summary, relative)
    save_inverter_anomaly_figures(relative, summary)

    flagged = summary.loc[summary["candidate_underperformer"], "inverter"].tolist()
    return {
        "ranking": summary,
        "candidate_underperformers": flagged,
        "threshold": UNDERPERFORMER_MEDIAN_THRESHOLD,
    }
