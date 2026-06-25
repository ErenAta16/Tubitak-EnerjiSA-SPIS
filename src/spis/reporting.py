"""P7 consolidated reporting: tables, figures, and FINAL_REPORT from processed data."""

from __future__ import annotations

import logging
import re
from typing import Any

import matplotlib as mpl
import pandas as pd

from spis import config
from spis.io import read_interim, read_processed
from spis.ml import run_ml_analysis
from spis.optimize import (
    load_soiling_rate_band,
    optimal_interval_grid_search,
    plot_actual_vs_optimal,
    plot_cost_curve,
    plot_t_star_heatmap,
)
from spis.robustness import (
    attach_clearness_index,
    attach_ground_pollution,
    build_daily_residual_frame,
    load_canakkale_ground_pollution,
    plot_ground_pollution_daily,
    plot_pollution_daily,
    plot_rain_recovery,
    plot_slope_comparison,
    quantify_rain_recovery,
)
from spis.soiling import (
    compute_wash_recovery,
    plot_pollution_scatter,
    plot_recovery,
    plot_segment_rates,
    plot_timeline,
)

LOGGER = logging.getLogger(__name__)

RESULTS_TABLE_CSV = "FINAL_RESULTS_TABLE.csv"
RESULTS_TABLE_MD = "FINAL_RESULTS_TABLE.md"
FINAL_REPORT = "FINAL_REPORT.md"

FIGURE_MANIFEST: tuple[tuple[str, str], ...] = (
    ("soiling_timeline_slopes", "PI timeline with wash lines and segment slopes"),
    ("soiling_rate_by_segment", "Per-segment soiling rate with CIs by season"),
    ("soiling_recovery_by_wash", "Washing recovery per event"),
    ("robustness_residual_vs_pm10", "Daily PI residual vs accumulated CAMS PM10"),
    ("robustness_residual_vs_ground_pm10", "Daily PI residual vs accumulated ground PM10"),
    ("robustness_residual_vs_dust", "Daily PI residual vs accumulated dust"),
    ("robustness_rain_recovery", "Rain-event PI recovery distribution"),
    ("optimize_cost_vs_interval", "Total cost vs wash interval at real 2023 PTF central case"),
    ("optimize_t_star_heatmap", "T* heatmap over wash cost and ASSUMED PTF sweep"),
    ("optimize_actual_vs_optimal", "Actual vs model-optimal inter-wash cadence"),
    ("ml_permutation_importance", "RF permutation importance (model test R2 negative)"),
)

FORBIDDEN_REPORT_PATTERNS: tuple[str, ...] = (
    r"pollution causes",
    r"proven causation",
    r"confirms pollution",
    r"CAMS drives soiling",
    r"pollution is the driver",
)


def apply_report_style() -> None:
    """Set consistent matplotlib style for publication figures."""
    mpl.rcParams.update(
        {
            "figure.dpi": 100,
            "savefig.dpi": 300,
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "legend.fontsize": 8,
        }
    )


def collect_headline_metrics() -> pd.DataFrame:
    """Build one-row-per-metric table from processed parquets."""
    segments = read_processed("soiling_segments")
    robustness = read_processed("soiling_robustness")
    optimize = read_processed("washing_optimization")
    ml = read_processed("ml_model_metrics")

    p4 = robustness.loc[robustness["record_type"] == "p4_verdict"].iloc[0]
    rain = robustness.loc[robustness["record_type"] == "rain_natural_washing"].iloc[0]
    central = optimize.loc[optimize["record_type"] == "central_estimate"].iloc[0]
    price_cmp = optimize.loc[optimize["record_type"] == "price_comparison"].iloc[0]
    bench = optimize.loc[optimize["record_type"] == "benchmark_summary"].iloc[0]
    rf = ml.loc[
        (ml["record_type"] == "test_metrics")
        & (ml["model_name"] == "random_forest")
        & (ml["target_framing"] == "soiling_ratio")
    ].iloc[0]
    rf_abs = ml.loc[
        (ml["record_type"] == "test_metrics")
        & (ml["model_name"] == "random_forest")
        & (ml["target_framing"] == "pi_temp_corrected")
    ].iloc[0]
    baseline = ml.loc[
        (ml["record_type"] == "test_metrics")
        & (ml["model_name"] == "days_since_wash_linear")
        & (ml["target_framing"] == "soiling_ratio")
    ].iloc[0]
    rf_cv = ml.loc[
        (ml["record_type"] == "cv_metrics")
        & (ml["model_name"] == "random_forest")
        & (ml["target_framing"] == "soiling_ratio")
    ].iloc[0]
    ml_verdict_row = ml.loc[ml["record_type"] == "ml_verdict"].iloc[0]
    pm10 = robustness.loc[robustness["record_type"] == "pollution_pm10"].iloc[0]
    ground_pm10 = robustness.loc[
        robustness["record_type"] == "pollution_ground_pm10_accumulated"
    ]
    ground_p = (
        f"{ground_pm10.iloc[0]['p_value']:.3f}"
        if not ground_pm10.empty and pd.notna(ground_pm10.iloc[0]["p_value"])
        else "n/a"
    )
    ground_pairs = (
        str(int(p4.get("ground_pm10_accumulated_pairs", 0)))
        if pd.notna(p4.get("ground_pm10_accumulated_pairs"))
        else "n/a"
    )
    recovery_median = float(segments["recovery_pct"].median())

    rate = f"{p4['recommended_rate_pct_per_day']:.4f}"
    rate_hw = f"{p4['recommended_uncertainty_half_width']:.4f}"
    ci_lo = f"{central['t_star_ci_low_days']:.0f}"
    ci_hi = f"{central['t_star_ci_high_days']:.0f}"
    rows = [
        ("soiling_rate_pct_per_day", rate, "%/day", "P3.5 clear-sky pooled"),
        ("soiling_rate_ci_half_width", rate_hw, "%/day", "P3.5"),
        ("median_wash_recovery_pct", f"{recovery_median:.2f}", "%", "P3 segment median"),
        (
            "pollution_daily_hac_verdict",
            str(p4["pollution_verdict"]),
            "text",
            "P3.5/P11 in-situ definitive test",
        ),
        ("pollution_pm10_hac_p_value", f"{pm10['p_value']:.3f}", "", "CAMS accumulated"),
        (
            "pollution_ground_pm10_hac_p_value",
            ground_p,
            "",
            "Ground PM10 accumulated (Merkez UHKIA)",
        ),
        (
            "ground_pm10_accumulated_pairs",
            ground_pairs,
            "days",
            "Clean days with observed ground PM10",
        ),
        (
            "optimal_wash_interval_T_star",
            f"{central['t_star_days']:.0f}",
            "days",
            "P4 real_2023 PTF",
        ),
        ("optimal_interval_ci", f"{ci_lo}-{ci_hi}", "days", "P4 rate CI"),
        (
            "T_star_legacy_assumed_2000",
            f"{price_cmp['t_star_legacy_assumed_days']:.0f}",
            "days",
            "Previous assumed PTF",
        ),
        (
            "actual_mean_inter_wash_gap",
            f"{bench['mean_actual_interval_days']:.0f}",
            "days",
            "Enerjisa washing_events",
        ),
        ("rain_mean_pi_recovery", f"{rain['mean_recovery']:.4f}", "PI units", "P3.5 rain"),
        (
            "rain_share_positive_uplift",
            f"{100 * rain['rain_share']:.1f}",
            "%",
            "P3.5 positive recoveries only",
        ),
        (
            "ml_soiling_ratio_rf_test_r2",
            f"{rf['r2']:.4f}",
            "",
            "P12 reframed target",
        ),
        (
            "ml_absolute_pi_rf_test_r2",
            f"{rf_abs['r2']:.4f}",
            "",
            "P5 legacy target (comparison)",
        ),
        (
            "ml_soiling_ratio_rf_cv_r2",
            f"{rf_cv['r2_mean']:.4f} +/- {rf_cv['r2_std']:.4f}",
            "",
            "P12 blocked TimeSeriesSplit",
        ),
        (
            "ml_soiling_ratio_trend_test_r2",
            f"{baseline['r2']:.4f}",
            "",
            "days_since_wash linear baseline",
        ),
        (
            "ml_verdict",
            str(ml_verdict_row["verdict"])[:120],
            "text",
            "P12 soiling_ratio framing",
        ),
        ("rf_test_mae", f"{rf['mae']:.4f}", "", "P12 soiling_ratio RF held-out"),
        ("rf_test_r2", f"{rf['r2']:.4f}", "", "P12 soiling_ratio RF held-out"),
        (
            "baseline_days_since_wash_r2",
            f"{baseline['r2']:.4f}",
            "",
            "P12 days_since_wash on soiling_ratio",
        ),
        (
            "central_ptf_tl_mwh",
            f"{central['price_tl_mwh']:.2f}",
            "TL/MWh",
            str(central["price_source"]),
        ),
    ]
    return pd.DataFrame(rows, columns=["metric", "value", "unit", "source"])


def cross_check_metrics(metrics: pd.DataFrame) -> list[str]:
    """Assert results table matches parquet sources."""
    failures: list[str] = []
    optimize = read_processed("washing_optimization")
    central = optimize.loc[optimize["record_type"] == "central_estimate"].iloc[0]
    t_star_row = metrics.loc[metrics["metric"] == "optimal_wash_interval_T_star", "value"].iloc[0]
    if abs(float(t_star_row) - float(central["t_star_days"])) > 0.5:
        failures.append("T* in results table does not match washing_optimization parquet")
    robustness = read_processed("soiling_robustness")
    p4 = robustness.loc[robustness["record_type"] == "p4_verdict"].iloc[0]
    rate_row = metrics.loc[metrics["metric"] == "soiling_rate_pct_per_day", "value"].iloc[0]
    if abs(float(rate_row) - float(p4["recommended_rate_pct_per_day"])) > 1e-4:
        failures.append("Soiling rate in results table does not match soiling_robustness parquet")
    return failures


def regenerate_figures() -> None:
    """Regenerate publication figure set from processed artifacts."""
    apply_report_style()
    master = read_processed("master_daily")
    segments = read_processed("soiling_segments")
    washing = read_interim("washing_events")
    robustness = read_processed("soiling_robustness")
    optimize = read_processed("washing_optimization")

    plot_timeline(master, segments, washing)
    plot_segment_rates(segments)
    washing_sorted = washing.sort_values("start").reset_index(drop=True)
    recovery_rows = pd.DataFrame(
        [compute_wash_recovery(master, washing_sorted, i) for i in range(len(washing_sorted))]
    )
    plot_recovery(recovery_rows)
    plot_pollution_scatter(segments)

    seg_cmp = robustness.loc[robustness["record_type"] == "segment_comparison"]
    plot_slope_comparison(seg_cmp)
    master_clr = attach_clearness_index(master)
    daily = build_daily_residual_frame(master_clr, segments)
    ground = load_canakkale_ground_pollution()
    daily, _ = attach_ground_pollution(daily, ground)
    plot_pollution_daily(daily, "pm10")
    plot_ground_pollution_daily(daily)
    plot_pollution_daily(daily, "dust")
    rain_stats = quantify_rain_recovery(master_clr)
    if rain_stats["recoveries"]:
        plot_rain_recovery(rain_stats["recoveries"])

    rate_band = load_soiling_rate_band(robustness)
    central = optimize.loc[optimize["record_type"] == "central_estimate"]
    actual = optimize.loc[optimize["record_type"] == "actual_interval"]
    sweep = optimize.loc[optimize["record_type"] == "sweep_point"]
    pooled = float(
        optimize.loc[optimize["segment_id"] == -1, "clean_baseline_kwh_day"].iloc[0]
    )
    central_price = float(central.iloc[0]["price_tl_mwh"])
    _, curve = optimal_interval_grid_search(
        config.WASH_COST_TL_CENTRAL, pooled, central_price, rate_band.point
    )
    plot_cost_curve(curve, central, rate_band, central_price)
    plot_t_star_heatmap(sweep)
    plot_actual_vs_optimal(actual, central)

    run_ml_analysis()
    LOGGER.info("Regenerated publication figure set")


def write_results_table(metrics: pd.DataFrame) -> None:
    """Write CSV and markdown results tables."""
    csv_path = config.REPORTS / RESULTS_TABLE_CSV
    md_path = config.REPORTS / RESULTS_TABLE_MD
    metrics.to_csv(csv_path, index=False)
    lines = ["| metric | value | unit | source |", "|---|---|---|---|"]
    for row in metrics.itertuples(index=False):
        lines.append(f"| {row.metric} | {row.value} | {row.unit} | {row.source} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s and %s", csv_path, md_path)


def write_final_report(metrics: pd.DataFrame) -> None:
    """Write consolidated FINAL_REPORT.md."""
    segments = read_processed("soiling_segments")
    seg_lines = [
        "| seg | rate %/day | season |",
        "|---:|---:|---|",
    ]
    for row in segments.sort_values("segment_id").itertuples():
        seg_lines.append(
            f"| {int(row.segment_id)} | {row.soiling_rate_pct_per_day:.3f} | {row.season} |"
        )

    m = {row.metric: row for row in metrics.itertuples()}
    captions = "\n".join(f"- **{stem}**: {cap}" for stem, cap in FIGURE_MANIFEST)

    content = f"""# SPIS Final Report (Canakkale Hybrid GES)

## Data and methods

Daily performance index PI = production / irradiation (kWh/day over Wh/m²/day).
Temperature-corrected PI used for soiling fits. Clean observations exclude downtime,
curtailment, fault, low-irradiation, and rain days (750 of 1026 days). Seven post-wash
segments from Enerjisa washing logs. External data: NASA POWER, CAMS air quality,
EPIAS PTF CSV (2023 hourly, annual mean {m['central_ptf_tl_mwh'].value} TL/MWh).

## Soiling rate (P3 / P3.5)

Clear-sky pooled Theil-Sen rate: **{m['soiling_rate_pct_per_day'].value} %/day**
(uncertainty half-width {m['soiling_rate_ci_half_width'].value} %/day).

Per-segment rates:

{chr(10).join(seg_lines)}

Observed rates are a **lower bound** when the reference irradiance sensor co-soils.

## Washing recovery

Median post-wash recovery: **{m['median_wash_recovery_pct'].value} %** across segments.

## Pollution test (honest verdict)

Daily HAC regression on trend-removed PI residuals (P3.5 spec: accumulated since
last wash). CAMS accumulated n~557; ground PM10 accumulated paired days
{m['ground_pm10_accumulated_pairs'].value}:
**{m['pollution_daily_hac_verdict'].value}**.
CAMS PM10 accumulated HAC p = {m['pollution_pm10_hac_p_value'].value}; ground PM10
accumulated HAC p = {m['pollution_ground_pm10_hac_p_value'].value} (Canakkale Merkez
UHKIA, urban proxy ~40-60 km from plant). Daily raw ground PM10 is reported in
SOILING_ROBUSTNESS.md as a sensitivity check only. Segment-level correlations (n=7)
and RF permutation ranks are **weak, non-confirmatory** signals only.

The reframed soiling_ratio RF test R2 is **{m['rf_test_r2'].value}** (legacy
absolute-PI R2 = {m['ml_absolute_pi_rf_test_r2'].value}). Permutation
importances are **not evidence** for a pollution driver; any mid-ranked dust feature
may reflect season/collinearity, not causation.

## Rain natural cleaning

Mean PI recovery per rain event: **{m['rain_mean_pi_recovery'].value}** (near zero).
Rain accounts for **{m['rain_share_positive_uplift'].value} %** of summed positive
cleaning uplift vs scheduled washing (P3.5).

## Economic optimum (P4)

Real central PTF: **{m['central_ptf_tl_mwh'].value} TL/MWh** (2023 annual mean only;
2024-2025 not supplied). Wash cost **150,000 TL remains ASSUMED**.

Optimal interval T* = **{m['optimal_wash_interval_T_star'].value} days**
(CI {m['optimal_interval_ci'].value} days). Previous assumed 2000 TL/MWh central
price gave T* = {m['T_star_legacy_assumed_2000'].value} days.

Actual mean inter-wash gap: **{m['actual_mean_inter_wash_gap'].value} days**. At the
2023 nominal price the plant appears to wash more often than the model optimum
(over-washing), but if Enerjisa supplies a current-TL wash cost without rebasing the
2023 PTF, the nominal price biases T* **longer** — keep the cadence verdict cautious.

## Machine learning corroboration (P5 / P12)

P12 reframes the target to within-segment **soiling_ratio** (fair task; PI no longer
resets between washes). Blocked CV R2 (RF) =
**{m['ml_soiling_ratio_rf_cv_r2'].value}**; held-out test R2 =
**{m['ml_soiling_ratio_rf_test_r2'].value}** vs legacy absolute-PI RF R2 =
**{m['ml_absolute_pi_rf_test_r2'].value}**. Simple trend baseline R2 =
**{m['ml_soiling_ratio_trend_test_r2'].value}**. {m['ml_verdict'].value}

## Limitations

- Single site (Canakkale); no Balikesir comparison data.
- Irradiance-sensor co-soiling cancels part of true module loss in PI.
- PTF central price is 2023-only nominal TL; wash cost assumed.
- Pollution null result and weak ML generalization remain valid findings, not failures.

## Figure captions

{captions}
"""
    path = config.REPORTS / FINAL_REPORT
    path.write_text(content, encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def check_figure_companions() -> list[str]:
    """Every manifest PNG must have a CSV companion."""
    failures: list[str] = []
    for stem, _ in FIGURE_MANIFEST:
        png = config.FIGURES / f"{stem}.png"
        csv = config.FIGURES / f"{stem}.csv"
        if not png.exists():
            failures.append(f"Missing figure PNG: {png.name}")
        if not csv.exists():
            failures.append(f"Missing figure CSV companion: {csv.name}")
    return failures


def check_no_overclaim() -> list[str]:
    """Fail if report contains forbidden causal pollution language."""
    text = (config.REPORTS / FINAL_REPORT).read_text(encoding="utf-8").lower()
    failures: list[str] = []
    for pattern in FORBIDDEN_REPORT_PATTERNS:
        if re.search(pattern, text):
            failures.append(f"Overclaim pattern matched: {pattern}")
    return failures


def run_reporting() -> dict[str, Any]:
    """Execute P7 reporting pipeline."""
    metrics = collect_headline_metrics()
    write_results_table(metrics)
    regenerate_figures()
    write_final_report(metrics)
    return {"metrics": metrics}
