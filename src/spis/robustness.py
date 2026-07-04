"""P3.5 soiling robustness: clear-sky slopes, daily pollution test, rain quantification.

Clearness filtering uses k = ALLSKY_SFC_SW_DWN / CLRSKY_SFC_SW_DWN from NASA POWER.
Days with k >= CLEARNESS_INDEX_MIN (default 0.7) are retained for re-fitted slopes.
This removes cloudy days whose diffuse fraction distorts the PI ratio.

Daily pollution inference uses PI residuals after removing each segment's fitted trend,
regressed on CAMS pollution accumulated since the last wash, with Newey-West HAC SEs.
"""

from __future__ import annotations

import logging
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from spis import config
from spis.data_sources.nasa_power import fetch_nasa_power_daily
from spis.data_sources.national_aq import fetch_national_aq_daily
from spis.io import read_processed, write_processed
from spis.soiling import (
    MASTER_INPUT_NAME,
    SOILING_OUTPUT_NAME,
    compute_baseline,
    fit_segment_slope,
    segment_clean_days,
)

LOGGER = logging.getLogger(__name__)

ROBUSTNESS_OUTPUT_NAME = "soiling_robustness"


def attach_clearness_index(master: pd.DataFrame) -> pd.DataFrame:
    """Join NASA clear-sky irradiance and compute clearness index k."""
    nasa, _ = fetch_nasa_power_daily(force_refresh=False)
    if "clrsky_sfc_sw_dwn" not in nasa.columns:
        nasa, _ = fetch_nasa_power_daily(force_refresh=True)
    nasa = nasa.rename(columns={"clrsky_sfc_sw_dwn": "nasa_clrsky_kwh_m2"})
    frame = master.drop(columns=["nasa_clrsky_kwh_m2", "clearness_index"], errors="ignore")
    frame = frame.merge(
        nasa[["date", "nasa_clrsky_kwh_m2"]],
        on="date",
        how="left",
        validate="one_to_one",
    )
    frame["clearness_index"] = frame["nasa_allsky_kwh_m2"] / frame["nasa_clrsky_kwh_m2"]
    frame.loc[frame["nasa_clrsky_kwh_m2"] <= 0, "clearness_index"] = pd.NA
    return frame


def high_clearness_mask(frame: pd.DataFrame) -> pd.Series:
    """Return boolean mask for high-clearness days (k >= threshold)."""
    return frame["clearness_index"] >= config.CLEARNESS_INDEX_MIN


def compare_clear_sky_slopes(master: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    """Re-fit segment slopes on high-clearness rain-free clean days."""
    rows: list[dict[str, Any]] = []
    tercile = float(master["clearness_index"].quantile(2 / 3))
    LOGGER.info(
        "Clearness filter: k >= %.2f (top tercile cutoff %.3f)",
        config.CLEARNESS_INDEX_MIN,
        tercile,
    )

    for _, seg in segments.iterrows():
        sid = int(seg["segment_id"])
        clean = segment_clean_days(master, sid)
        baseline_temp = compute_baseline(clean, "pi_temp_corrected")
        baseline_raw = compute_baseline(clean, "pi")
        clear_mask = high_clearness_mask(clean)
        fit_clear = fit_segment_slope(
            clean,
            baseline_temp,
            baseline_raw,
            sid,
            day_mask=clear_mask,
        )
        rows.append(
            {
                "record_type": "segment_comparison",
                "segment_id": sid,
                "original_rate_pct_per_day": seg["soiling_rate_pct_per_day"],
                "original_ci_lower": seg["soiling_rate_ci_lower"],
                "original_ci_upper": seg["soiling_rate_ci_upper"],
                "original_r2": seg["soiling_rate_r2"],
                "original_n_fit": seg["n_fit_rain_free"],
                "clear_rate_pct_per_day": fit_clear.slope_pct_per_day,
                "clear_ci_lower": fit_clear.ci_lower,
                "clear_ci_upper": fit_clear.ci_upper,
                "clear_r2": fit_clear.r2,
                "clear_n_fit": fit_clear.n_fit,
                "clearness_threshold": config.CLEARNESS_INDEX_MIN,
                "clearness_tercile_cutoff": tercile,
                "rate_delta": fit_clear.slope_pct_per_day - seg["soiling_rate_pct_per_day"],
                "ci_tightened": abs(fit_clear.ci_upper - fit_clear.ci_lower)
                < abs(seg["soiling_rate_ci_upper"] - seg["soiling_rate_ci_lower"]),
            }
        )
    return pd.DataFrame(rows)


def build_daily_residual_frame(master: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    """Compute PI residuals after removing each segment's fitted trend."""
    clean = master.loc[master["is_clean_observation"] & (master["segment_id"] > 0)].copy()
    clean = clean.sort_values(["segment_id", "date"])
    residuals: list[pd.DataFrame] = []

    for _, seg in segments.iterrows():
        sid = int(seg["segment_id"])
        seg_clean = clean.loc[clean["segment_id"] == sid].copy()
        if seg_clean.empty:
            continue
        baseline = float(seg["baseline_pi_temp_corrected"])
        baseline_raw = float(seg["baseline_pi_raw"])
        fit = fit_segment_slope(
            segment_clean_days(master, sid),
            baseline,
            baseline_raw,
            sid,
        )
        seg_clean["predicted_pi"] = (
            baseline
            * (fit.intercept + fit.slope_pct_per_day * seg_clean["days_since_wash"])
            / 100.0
        )
        seg_clean["pi_residual"] = seg_clean["pi_temp_corrected"] - seg_clean["predicted_pi"]
        for pollutant in ("pm10", "dust", "aerosol_optical_depth"):
            seg_clean[f"{pollutant}_accumulated"] = seg_clean[pollutant].cumsum()
        residuals.append(seg_clean)

    frame = pd.concat(residuals, ignore_index=True)
    LOGGER.info("Daily residual frame: %s clean days", len(frame))
    return frame


def _pollution_result_row(
    record_type: str,
    pollutant: str,
    x_col: str,
    data_source: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    coef = result["coefficients"].get(x_col, {})
    return {
        "record_type": record_type,
        "segment_id": pd.NA,
        "pollutant": pollutant,
        "data_source": data_source,
        "x_variable": x_col,
        "n_obs": result["n"],
        "r2": result["r2"],
        "partial_r2": coef.get("partial_r2", result.get("partial_r2")),
        "coef": coef.get("coef"),
        "hac_ci_lower": coef.get("hac_ci_lower"),
        "hac_ci_upper": coef.get("hac_ci_upper"),
        "p_value": coef.get("p_value"),
        "hac_se_wider_than_naive": result.get("hac_se_wider_than_naive"),
    }


def load_canakkale_ground_pollution() -> pd.DataFrame:
    """Load cached national AQ daily PM for Canakkale Merkez UHKIA (no imputation)."""
    ground, _ = fetch_national_aq_daily(site_key="canakkale", force_refresh=False)
    frame = ground[["date", "pm10", "pm2_5", "station_code", "station_name"]].copy()
    frame = frame.sort_values("date").reset_index(drop=True)
    LOGGER.info(
        "Ground AQ Canakkale %s: %s calendar rows, PM10 observed %s, PM2.5 observed %s",
        frame["station_code"].iloc[0],
        len(frame),
        int(frame["pm10"].notna().sum()),
        int(frame["pm2_5"].notna().sum()),
    )
    return frame


def attach_ground_pollution(
    daily: pd.DataFrame,
    ground: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Join in-situ PM onto the daily residual frame; accumulate within each segment."""
    merged = daily.merge(
        ground.rename(
            columns={
                "pm10": "ground_pm10",
                "pm2_5": "ground_pm2_5",
            }
        )[["date", "ground_pm10", "ground_pm2_5", "station_code", "station_name"]],
        on="date",
        how="left",
    )
    merged["ground_pm10_accumulated"] = np.nan
    merged["ground_pm2_5_accumulated"] = np.nan
    for _, group in merged.groupby("segment_id", sort=False):
        idx = group.index
        for raw_col, acc_col in (
            ("ground_pm10", "ground_pm10_accumulated"),
            ("ground_pm2_5", "ground_pm2_5_accumulated"),
        ):
            observed = merged.loc[idx, raw_col].notna()
            if observed.any():
                merged.loc[idx[observed], acc_col] = (
                    merged.loc[idx[observed], raw_col].cumsum().to_numpy()
                )

    paired = {
        "ground_pm10_daily_pairs": int(
            merged.loc[merged["ground_pm10"].notna(), "pi_residual"].notna().sum()
        ),
        "ground_pm10_accumulated_pairs": int(
            merged.loc[merged["ground_pm10_accumulated"].notna(), "pi_residual"].notna().sum()
        ),
        "ground_pm2_5_daily_pairs": int(
            merged.loc[merged["ground_pm2_5"].notna(), "pi_residual"].notna().sum()
        ),
        "ground_pm2_5_accumulated_pairs": int(
            merged.loc[merged["ground_pm2_5_accumulated"].notna(), "pi_residual"].notna().sum()
        ),
    }
    LOGGER.info("Ground pollution paired-day counts: %s", paired)
    return merged, paired


def _partial_r2(full: sm.regression.linear_model.RegressionResultsWrapper, reduced) -> float:
    return float(full.rsquared - reduced.rsquared)


def hac_regression(
    frame: pd.DataFrame,
    y_col: str,
    x_cols: list[str],
) -> dict[str, Any]:
    """OLS with Newey-West HAC standard errors."""
    data = frame[[y_col, *x_cols]].dropna()
    if len(data) < len(x_cols) + 5:
        return {
            "n": len(data),
            "r2": float("nan"),
            "partial_r2": float("nan"),
            "coefficients": {},
        }

    y = data[y_col]
    x = sm.add_constant(data[x_cols])
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": config.HAC_MAX_LAGS})
    naive = sm.OLS(y, x).fit()

    coefs: dict[str, dict[str, float]] = {}
    for name in x_cols:
        coefs[name] = {
            "coef": float(model.params[name]),
            "hac_se": float(model.bse[name]),
            "hac_ci_lower": float(model.conf_int().loc[name, 0]),
            "hac_ci_upper": float(model.conf_int().loc[name, 1]),
            "naive_se": float(naive.bse[name]),
            "p_value": float(model.pvalues[name]),
        }

    partial_r2 = float("nan")
    if len(x_cols) == 1:
        reduced = sm.OLS(y, sm.add_constant(np.ones(len(y)))).fit()
        partial_r2 = _partial_r2(model, reduced)
    else:
        for target in x_cols:
            reduced_cols = [c for c in x_cols if c != target]
            x_reduced = sm.add_constant(data[reduced_cols])
            reduced = sm.OLS(y, x_reduced).fit()
            coefs[target]["partial_r2"] = _partial_r2(model, reduced)

    return {
        "n": len(data),
        "r2": float(model.rsquared),
        "partial_r2": partial_r2,
        "coefficients": coefs,
        "hac_se_wider_than_naive": any(coefs[c]["hac_se"] > coefs[c]["naive_se"] for c in x_cols),
    }


def pollution_daily_tests(frame: pd.DataFrame) -> pd.DataFrame:
    """Run daily-level pollution regressions on PI residuals (CAMS + in-situ)."""
    rows: list[dict[str, Any]] = []

    cams_specs = {
        "pm10": "pm10_accumulated",
        "dust": "dust_accumulated",
        "aod": "aerosol_optical_depth_accumulated",
    }
    for name, col in cams_specs.items():
        result = hac_regression(frame, "pi_residual", [col])
        rows.append(_pollution_result_row(f"pollution_{name}", name, col, "cams", result))

    combined = hac_regression(frame, "pi_residual", list(cams_specs.values()))
    for name, col in cams_specs.items():
        coef = combined["coefficients"].get(col, {})
        rows.append(
            {
                **_pollution_result_row("pollution_combined", name, col, "cams", combined),
                "partial_r2": coef.get("partial_r2"),
                "coef": coef.get("coef"),
                "hac_ci_lower": coef.get("hac_ci_lower"),
                "hac_ci_upper": coef.get("hac_ci_upper"),
                "p_value": coef.get("p_value"),
            }
        )

    ground_specs = (
        ("pollution_ground_pm10_accumulated", "ground_pm10", "ground_pm10_accumulated"),
        ("pollution_ground_pm10_daily", "ground_pm10", "ground_pm10"),
        ("pollution_ground_pm2_5_accumulated", "ground_pm2_5", "ground_pm2_5_accumulated"),
        ("pollution_ground_pm2_5_daily", "ground_pm2_5", "ground_pm2_5"),
    )
    for record_type, pollutant, x_col in ground_specs:
        if x_col not in frame.columns:
            continue
        result = hac_regression(frame, "pi_residual", [x_col])
        rows.append(_pollution_result_row(record_type, pollutant, x_col, "ground_uhki", result))

    return pd.DataFrame(rows)


def identify_rain_events(master: pd.DataFrame) -> pd.DataFrame:
    """Group consecutive rainy days into events."""
    ordered = master.sort_values("date")
    events: list[dict[str, Any]] = []
    in_event = False
    start = end = None
    for _, row in ordered.iterrows():
        if row["nasa_precip_mm"] >= config.RAIN_EVENT_PRECIP_MM:
            if not in_event:
                start = row["date"]
                in_event = True
            end = row["date"]
        elif in_event:
            events.append({"start": start, "end": end})
            in_event = False
    if in_event:
        events.append({"start": start, "end": end})
    return pd.DataFrame(events)


def quantify_rain_recovery(master: pd.DataFrame) -> dict[str, Any]:
    """Estimate PI recovery attributable to rain events on clean days."""
    events = identify_rain_events(master)
    window = config.RAIN_RECOVERY_WINDOW_DAYS
    recoveries: list[float] = []

    for _, event in events.iterrows():
        before = master.loc[
            (master["date"] < event["start"])
            & master["is_clean_observation"]
            & (~master["rain_day"])
        ].tail(window)
        after = master.loc[
            (master["date"] > event["end"]) & master["is_clean_observation"] & (~master["rain_day"])
        ].head(window)
        if before.empty or after.empty:
            continue
        recoveries.append(
            float(after["pi_temp_corrected"].median() - before["pi_temp_corrected"].median())
        )

    if not recoveries:
        return {
            "n_events": len(events),
            "n_quantified": 0,
            "mean_recovery": float("nan"),
            "ci_lower": float("nan"),
            "ci_upper": float("nan"),
        }

    rng = np.random.default_rng(config.RANDOM_STATE)
    boot_means: list[float] = []
    values = np.array(recoveries)
    for _ in range(config.BLOCK_BOOTSTRAP_SAMPLES):
        sample = rng.choice(values, size=len(values), replace=True)
        boot_means.append(float(sample.mean()))

    return {
        "n_events": len(events),
        "n_quantified": len(recoveries),
        "mean_recovery": float(np.mean(recoveries)),
        "ci_lower": float(np.percentile(boot_means, 2.5)),
        "ci_upper": float(np.percentile(boot_means, 97.5)),
        "recoveries": recoveries,
    }


def compare_rain_vs_wash_cleaning(
    rain_stats: dict[str, Any], segments: pd.DataFrame
) -> dict[str, float]:
    """Compare total PI uplift from rain vs scheduled washing."""
    rain_total = float(np.sum([r for r in rain_stats.get("recoveries", []) if r > 0]))
    wash_total = float(segments.loc[segments["recovery_abs"] > 0, "recovery_abs"].sum())
    total = rain_total + wash_total
    if total <= 0:
        return {
            "rain_share": float("nan"),
            "wash_share": float("nan"),
            "rain_total_pi_uplift": rain_total,
            "wash_total_pi_uplift": wash_total,
        }
    return {
        "rain_share": rain_total / total,
        "wash_share": wash_total / total,
        "rain_total_pi_uplift": rain_total,
        "wash_total_pi_uplift": wash_total,
    }


def canonical_clear_sky_pooled(segment_compare: pd.DataFrame) -> dict[str, float]:
    """P4 canonical clear-sky pooled rate and CI (weighted mean + mean segment CI width)."""
    valid = segment_compare.dropna(subset=["clear_rate_pct_per_day", "clear_n_fit"])
    if valid.empty:
        return {
            "pooled_rate": float("nan"),
            "pooled_ci_lower": float("nan"),
            "pooled_ci_upper": float("nan"),
            "ci_half_width": float("nan"),
            "ci_method": "clear_sky_pooled_weighted_by_n_fit",
            "n_segments": 0.0,
        }
    weights = valid["clear_n_fit"].to_numpy(dtype=float)
    rates = valid["clear_rate_pct_per_day"].to_numpy(dtype=float)
    pooled = float(np.average(rates, weights=weights))
    ci_width = float(valid["clear_ci_upper"].mean() - valid["clear_ci_lower"].mean())
    half = ci_width / 2.0
    return {
        "pooled_rate": pooled,
        "pooled_ci_lower": pooled - half,
        "pooled_ci_upper": pooled + half,
        "ci_half_width": half,
        "ci_method": "clear_sky_pooled_weighted_by_n_fit",
        "n_segments": float(len(valid)),
    }


def p4_verdict(
    segment_compare: pd.DataFrame,
    pollution: pd.DataFrame,
    rain_stats: dict[str, Any],
    rain_vs_wash: dict[str, float],
    ground_pairs: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Summarise robustness for P4 and the written report."""
    canonical = canonical_clear_sky_pooled(segment_compare)
    clear_pooled = canonical["pooled_rate"]
    valid_clear = segment_compare.dropna(subset=["clear_rate_pct_per_day"])

    pm10 = pollution.loc[pollution["record_type"] == "pollution_pm10"].iloc[0]
    ground_acc = pollution.loc[pollution["record_type"] == "pollution_ground_pm10_accumulated"]
    ground_pm10 = ground_acc.iloc[0] if not ground_acc.empty else None

    def _pollution_supported(row: pd.Series) -> bool:
        return bool(
            pd.notna(row["p_value"])
            and row["p_value"] < 0.05
            and row["coef"] is not None
            and row["coef"] < 0
        )

    cams_supported = _pollution_supported(pm10)
    ground_supported = _pollution_supported(ground_pm10) if ground_pm10 is not None else False

    if ground_pm10 is not None:
        ground_daily = pollution.loc[pollution["record_type"] == "pollution_ground_pm10_daily"]
        ground_daily_row = ground_daily.iloc[0] if not ground_daily.empty else None
        daily_significant = ground_daily_row is not None and _pollution_supported(ground_daily_row)

        if ground_supported:
            pollution_verdict = "partially supported (in-situ PM10 accumulated)"
            insitu_note = (
                f"Ground PM10 accumulated HAC coef {ground_pm10['coef']:.2e}, "
                f"partial R2 {ground_pm10['partial_r2']:.4f}"
            )
        elif pd.notna(ground_pm10["p_value"]) and ground_pm10["p_value"] >= 0.05:
            pollution_verdict = "not supported at daily resolution (confirmed with in-situ PM10)"
            insitu_note = "CAMS attenuation concern resolved: ground PM10 accumulated also null"
            if daily_significant and ground_daily_row is not None:
                insitu_note += (
                    f". Sensitivity: daily raw ground PM10 HAC p="
                    f"{ground_daily_row['p_value']:.3f} "
                    "(not the accumulated-pollution specification)"
                )
        else:
            pollution_verdict = "inconclusive (in-situ PM10)"
            insitu_note = "Ground PM10 regression inconclusive"
    elif cams_supported:
        pollution_verdict = "partially supported"
        insitu_note = "In-situ PM10 unavailable; CAMS-only verdict"
    elif pd.notna(pm10["p_value"]) and pm10["p_value"] >= 0.05:
        pollution_verdict = "not supported at daily resolution (n~750)"
        insitu_note = "In-situ PM10 unavailable; CAMS-only verdict"
    else:
        pollution_verdict = "inconclusive"
        insitu_note = "Pollution regressions inconclusive"

    half_width = canonical["ci_half_width"]
    ci_width = half_width * 2.0 if pd.notna(half_width) else float("nan")
    robust_enough = (
        not valid_clear.empty
        and pd.notna(ci_width)
        and ci_width < 0.25
        and valid_clear["clear_rate_pct_per_day"].median() < 0
    )

    verdict: dict[str, Any] = {
        "record_type": "p4_verdict",
        "robust_enough_for_scheduling": bool(robust_enough),
        "recommended_rate_pct_per_day": clear_pooled,
        "recommended_uncertainty_half_width": canonical["ci_half_width"],
        "rate_basis": canonical["ci_method"],
        "pollution_verdict": pollution_verdict,
        "insitu_pollution_note": insitu_note,
        "pm10_coef": pm10.get("coef"),
        "pm10_hac_ci_lower": pm10.get("hac_ci_lower"),
        "pm10_hac_ci_upper": pm10.get("hac_ci_upper"),
        "pm10_p_value": pm10.get("p_value"),
        "rain_mean_recovery": rain_stats.get("mean_recovery"),
        "rain_share_of_cleaning": rain_vs_wash.get("rain_share"),
        "report_framing": (
            "Frame soiling as a robust seasonal loss rate corrected for clear days, "
            "with rain as a parallel natural-cleaning pathway. Do not claim pollution "
            "causality unless daily HAC coefficients are significant; emphasise "
            "irradiance-sensor co-soiling as an upward bias bound on true loss."
        ),
    }
    if ground_pm10 is not None:
        verdict.update(
            {
                "ground_pm10_coef": ground_pm10.get("coef"),
                "ground_pm10_hac_ci_lower": ground_pm10.get("hac_ci_lower"),
                "ground_pm10_hac_ci_upper": ground_pm10.get("hac_ci_upper"),
                "ground_pm10_p_value": ground_pm10.get("p_value"),
                "ground_pm10_partial_r2": ground_pm10.get("partial_r2"),
                "ground_pm10_n_obs": ground_pm10.get("n_obs"),
            }
        )
    if ground_pairs:
        verdict.update(ground_pairs)
    return verdict


def _save_figure(name: str, fig: plt.Figure, plot_frame: pd.DataFrame) -> None:
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(config.FIGURES / f"{name}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    plot_frame.to_csv(config.FIGURES / f"{name}.csv", index=False)


def plot_slope_comparison(segment_compare: pd.DataFrame) -> None:
    """Original vs clear-sky slopes by segment."""
    frame = segment_compare.sort_values("segment_id")
    x = np.arange(len(frame))
    width = 0.35
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(x - width / 2, frame["original_rate_pct_per_day"], width, label="Original")
    ax.bar(x + width / 2, frame["clear_rate_pct_per_day"], width, label="Clear-sky")
    ax.set_xticks(x)
    ax.set_xticklabels(frame["segment_id"].astype(int))
    ax.axhline(0, color="0.4", linewidth=0.8)
    ax.set_xlabel("Segment ID")
    ax.set_ylabel("Soiling rate (%/day)")
    ax.set_title("Original vs clear-sky filtered soiling rates")
    ax.legend()
    fig.tight_layout()
    _save_figure("robustness_slope_comparison", fig, frame)


def plot_pollution_daily(frame: pd.DataFrame, pollutant: str = "pm10") -> None:
    """Daily PI residual vs accumulated pollution with HAC fit line."""
    col = f"{pollutant}_accumulated"
    data = frame[[col, "pi_residual"]].dropna()
    result = hac_regression(frame, "pi_residual", [col])
    coef = result["coefficients"][col]
    x_line = np.linspace(data[col].min(), data[col].max(), 50)
    y_line = coef["coef"] * x_line + float(
        data["pi_residual"].mean() - coef["coef"] * data[col].mean()
    )

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(data[col], data["pi_residual"], s=8, alpha=0.4)
    ax.plot(x_line, y_line, color="tab:red", label="HAC OLS fit")
    ax.set_xlabel(f"Accumulated {pollutant} since wash")
    ax.set_ylabel("PI residual (temp corrected)")
    ax.set_title(f"Daily residual vs accumulated {pollutant} (n={len(data)})")
    ax.legend()
    fig.tight_layout()
    _save_figure(f"robustness_residual_vs_{pollutant}", fig, data.reset_index(drop=True))


def plot_ground_pollution_daily(
    frame: pd.DataFrame,
    x_col: str = "ground_pm10_accumulated",
    title_pollutant: str = "ground PM10",
) -> None:
    """Daily PI residual vs in-situ accumulated PM with HAC fit line."""
    data = frame[[x_col, "pi_residual"]].dropna()
    result = hac_regression(frame, "pi_residual", [x_col])
    coef = result["coefficients"][x_col]
    x_line = np.linspace(data[x_col].min(), data[x_col].max(), 50)
    y_line = coef["coef"] * x_line + float(
        data["pi_residual"].mean() - coef["coef"] * data[x_col].mean()
    )

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(data[x_col], data["pi_residual"], s=8, alpha=0.4)
    ax.plot(x_line, y_line, color="tab:red", label="HAC OLS fit")
    ax.set_xlabel(f"Accumulated {title_pollutant} since wash (ug/m3-days)")
    ax.set_ylabel("PI residual (temp corrected)")
    ax.set_title(f"Daily residual vs accumulated {title_pollutant} (n={len(data)})")
    ax.legend()
    fig.tight_layout()
    _save_figure("robustness_residual_vs_ground_pm10", fig, data.reset_index(drop=True))


def plot_rain_recovery(recoveries: list[float]) -> None:
    """Distribution of rain-attributable PI recovery."""
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(recoveries, bins=min(15, max(3, len(recoveries))), edgecolor="black")
    ax.axvline(np.mean(recoveries), color="tab:red", label=f"mean={np.mean(recoveries):.3f}")
    ax.set_xlabel("PI recovery (temp corrected)")
    ax.set_ylabel("Rain event count")
    ax.set_title("Rain-attributable PI recovery distribution")
    ax.legend()
    fig.tight_layout()
    _save_figure("robustness_rain_recovery", fig, pd.DataFrame({"recovery": recoveries}))


def run_robustness_analysis() -> dict[str, Any]:
    """Execute the P3.5 robustness workflow."""
    master = read_processed(MASTER_INPUT_NAME)
    segments = read_processed(SOILING_OUTPUT_NAME)
    master = attach_clearness_index(master)

    segment_compare = compare_clear_sky_slopes(master, segments)
    daily = build_daily_residual_frame(master, segments)
    ground = load_canakkale_ground_pollution()
    daily, ground_pairs = attach_ground_pollution(daily, ground)
    pollution = pollution_daily_tests(daily)
    rain_stats = quantify_rain_recovery(master)
    rain_vs_wash = compare_rain_vs_wash_cleaning(rain_stats, segments)
    verdict = p4_verdict(segment_compare, pollution, rain_stats, rain_vs_wash, ground_pairs)

    rain_row = pd.DataFrame(
        [
            {
                "record_type": "rain_natural_washing",
                "segment_id": pd.NA,
                **{k: v for k, v in rain_stats.items() if k != "recoveries"},
                **rain_vs_wash,
            }
        ]
    )
    verdict_row = pd.DataFrame([verdict])
    output = pd.concat(
        [segment_compare, pollution, rain_row, verdict_row],
        ignore_index=True,
        sort=False,
    )
    write_processed(ROBUSTNESS_OUTPUT_NAME, output)

    plot_slope_comparison(segment_compare)
    plot_pollution_daily(daily, "pm10")
    plot_pollution_daily(daily, "dust")
    plot_ground_pollution_daily(daily)
    if rain_stats.get("recoveries"):
        plot_rain_recovery(rain_stats["recoveries"])

    write_robustness_report(segment_compare, pollution, rain_stats, rain_vs_wash, verdict, master)

    return {
        "segment_compare": segment_compare,
        "pollution": pollution,
        "rain_stats": rain_stats,
        "rain_vs_wash": rain_vs_wash,
        "verdict": verdict,
        "daily_n": len(daily),
        "ground_pairs": ground_pairs,
    }


def write_robustness_report(
    segment_compare: pd.DataFrame,
    pollution: pd.DataFrame,
    rain_stats: dict[str, Any],
    rain_vs_wash: dict[str, float],
    verdict: dict[str, Any],
    master: pd.DataFrame,
) -> None:
    """Write reports/SOILING_ROBUSTNESS.md."""
    pm10 = pollution.loc[pollution["record_type"] == "pollution_pm10"].iloc[0]
    ground_acc = pollution.loc[pollution["record_type"] == "pollution_ground_pm10_accumulated"]
    ground_daily = pollution.loc[pollution["record_type"] == "pollution_ground_pm10_daily"]
    ground_pm25_acc = pollution.loc[
        pollution["record_type"] == "pollution_ground_pm2_5_accumulated"
    ]
    ground_pm25_daily = pollution.loc[pollution["record_type"] == "pollution_ground_pm2_5_daily"]
    path = config.REPORTS / "SOILING_ROBUSTNESS.md"
    sensor_note = (
        "The SCADA irradiance column (ISINIM) is a plant-level daily integrated "
        "irradiation signal, likely from an in-plane reference sensor. If that "
        "sensor soiling tracks module soiling, true panel degradation is partially "
        "cancelled in PI = production/irradiation, so observed soiling rates are "
        "a lower bound on physical soiling. No sensor datasheet was found in the "
        "repository; this limitation is not corrected, only flagged."
    )
    spatial_note = (
        "In-situ PM10/PM2.5 comes from Canakkale Merkez UHKIA (TR170141), an urban "
        "monitor ~40-60 km from the rural hybrid plant. Even ground readings are a "
        "spatial proxy for field soiling; on-site reference dust instrumentation "
        "(recommended future work for Enerjisa) would be the only direct measure."
    )

    def _pollution_line(row: pd.Series, label: str) -> str:
        return (
            f"| {label} | {int(row.get('n_obs', 0))} | {row.get('coef')} | "
            f"[{row.get('hac_ci_lower')}, {row.get('hac_ci_upper')}] | "
            f"{row.get('partial_r2')} | {row.get('p_value')} |"
        )

    comparison_lines = [
        "| Source / variable | n | HAC coef | 95% CI | partial R2 | p |",
        "|---|---:|---:|---|---:|---:|",
        _pollution_line(pm10, "CAMS PM10 accumulated"),
    ]
    if not ground_acc.empty:
        comparison_lines.append(_pollution_line(ground_acc.iloc[0], "Ground PM10 accumulated"))
    if not ground_daily.empty:
        comparison_lines.append(_pollution_line(ground_daily.iloc[0], "Ground PM10 daily"))
    if not ground_pm25_acc.empty:
        comparison_lines.append(
            _pollution_line(ground_pm25_acc.iloc[0], "Ground PM2.5 accumulated")
        )
    if not ground_pm25_daily.empty:
        comparison_lines.append(_pollution_line(ground_pm25_daily.iloc[0], "Ground PM2.5 daily"))

    paired_note = ""
    if verdict.get("ground_pm10_accumulated_pairs") is not None:
        paired_note = (
            f"Ground PM10 accumulated paired days: "
            f"{int(verdict['ground_pm10_accumulated_pairs'])}; "
            f"ground PM10 daily: {int(verdict.get('ground_pm10_daily_pairs', 0))}; "
            f"ground PM2.5 accumulated: "
            f"{int(verdict.get('ground_pm2_5_accumulated_pairs', 0))}."
        )

    content = "\n".join(
        [
            "# Soiling Robustness Verdict",
            "",
            "## Clear-sky slope sharpening",
            "",
            f"Clearness index k = ALLSKY/CLRSKY from NASA POWER. "
            f"High-clearness days use k >= {config.CLEARNESS_INDEX_MIN}.",
            "",
            "## Daily pollution test (CAMS vs in-situ)",
            "",
            f"Clean-day input: {int(master['is_clean_observation'].sum())}; "
            f"regression n after trend removal (CAMS PM10): "
            f"{int(pm10.get('n_obs', 0))}.",
            paired_note,
            "",
            "Side-by-side HAC regressions on trend-removed PI residuals:",
            "",
            *comparison_lines,
            "",
            f"Verdict: **{verdict['pollution_verdict']}**. "
            f"{verdict.get('insitu_pollution_note', '')}. "
            "Association only; not proven causation.",
            "",
            "## Spatial proxy caveat (in-situ PM)",
            "",
            spatial_note,
            "",
            "## Rain natural washing",
            "",
            f"Mean PI recovery per rain event: {rain_stats.get('mean_recovery')} "
            f"(95% CI {rain_stats.get('ci_lower')} .. {rain_stats.get('ci_upper')}).",
            f"Rain share of positive cleaning uplift: "
            f"{rain_vs_wash.get('rain_share', float('nan')):.1%} "
            f"vs washing {rain_vs_wash.get('wash_share', float('nan')):.1%}.",
            "",
            "## Irradiance-sensor caveat",
            "",
            sensor_note,
            "",
            "## Scheduling recommendation",
            "",
            f"Robust enough to schedule: **{verdict['robust_enough_for_scheduling']}**.",
            "",
            f"Use rate **{verdict['recommended_rate_pct_per_day']:.4f} %/day** "
            f"({verdict['rate_basis']}) with uncertainty half-width "
            f"~{verdict['recommended_uncertainty_half_width']:.4f}.",
            "",
            "## Report framing",
            "",
            str(verdict["report_framing"]),
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    LOGGER.info("Wrote %s", path)
