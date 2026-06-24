"""Two-site environmental comparison (CAMS + NASA POWER only)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from spis import config
from spis.data_sources.nasa_power import fetch_nasa_power_daily, validate_nasa_power
from spis.data_sources.open_meteo_aq import fetch_open_meteo_air_quality, validate_open_meteo_aq
from spis.io import write_processed
from spis.sites import get_site, provisional_label

LOGGER = logging.getLogger(__name__)

SITE_COMPARISON_OUTPUT = "site_comparison"
POLLUTION_VARS = ("pm10", "pm2_5", "dust", "aerosol_optical_depth")
COMPARISON_SITE_KEYS = ("canakkale", "balikesir")
BOOTSTRAP_SAMPLES = 2000


def _site_env_frame(site_key: str, force_refresh: bool = False) -> pd.DataFrame:
    """Pull or load NASA + CAMS daily series for one site."""
    nasa, _ = fetch_nasa_power_daily(site_key=site_key, force_refresh=force_refresh)
    cams, _ = fetch_open_meteo_air_quality(site_key=site_key, force_refresh=force_refresh)
    validate_nasa_power(nasa)
    validate_open_meteo_aq(cams)

    merged = nasa.merge(cams, on="date", how="outer")
    merged = merged.sort_values("date").reset_index(drop=True)
    merged["site_key"] = site_key
    merged["provisional"] = get_site(site_key).coordinates_provisional
    return merged


def build_site_comparison_frames(
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build daily wide, monthly wide, and long-form comparison tables."""
    site_frames: dict[str, pd.DataFrame] = {}
    for site_key in COMPARISON_SITE_KEYS:
        site_frames[site_key] = _site_env_frame(site_key, force_refresh=force_refresh)

    daily_parts: list[pd.DataFrame] = []
    for site_key, frame in site_frames.items():
        part = frame.copy()
        rename = {
            col: f"{site_key}_{col}"
            for col in part.columns
            if col not in {"date", "site_key", "provisional"}
        }
        part = part.rename(columns=rename)
        part = part.drop(columns=["site_key", "provisional"], errors="ignore")
        daily_parts.append(part)

    daily = daily_parts[0]
    for part in daily_parts[1:]:
        daily = daily.merge(part, on="date", how="outer")
    daily = daily.sort_values("date").reset_index(drop=True)

    monthly_rows: list[dict[str, Any]] = []
    for site_key, frame in site_frames.items():
        monthly = frame.copy()
        monthly["month"] = monthly["date"].dt.to_period("M").dt.to_timestamp()
        numeric_cols = [
            c for c in monthly.columns if c not in {"date", "month", "site_key", "provisional"}
        ]
        grouped = monthly.groupby("month", as_index=False)[numeric_cols].mean(numeric_only=True)
        grouped["site_key"] = site_key
        grouped["provisional"] = get_site(site_key).coordinates_provisional
        monthly_rows.append(grouped)

    monthly_long = pd.concat(monthly_rows, ignore_index=True).sort_values(["month", "site_key"])

    long_rows: list[pd.DataFrame] = []
    for site_key, frame in site_frames.items():
        long_part = frame.copy()
        long_part["site_key"] = site_key
        long_part["provisional_label"] = provisional_label(site_key)
        long_rows.append(long_part)
    daily_long = pd.concat(long_rows, ignore_index=True).sort_values(["date", "site_key"])

    return daily, monthly_long, daily_long


def bootstrap_median_difference_ci(
    sample_a: np.ndarray,
    sample_b: np.ndarray,
    n_samples: int = BOOTSTRAP_SAMPLES,
    seed: int = config.RANDOM_STATE,
) -> tuple[float, float, float]:
    """Bootstrap 95% CI for median(a) - median(b)."""
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_samples)
    for idx in range(n_samples):
        boot_a = rng.choice(sample_a, size=len(sample_a), replace=True)
        boot_b = rng.choice(sample_b, size=len(sample_b), replace=True)
        diffs[idx] = float(np.median(boot_a) - np.median(boot_b))
    return (
        float(np.percentile(diffs, 2.5)),
        float(np.median(diffs)),
        float(np.percentile(diffs, 97.5)),
    )


def distribution_overlap(a: np.ndarray, b: np.ndarray, bins: int = 50) -> float:
    """Histogram overlap coefficient in [0, 1] for two samples."""
    combined = np.concatenate([a, b])
    edges = np.histogram_bin_edges(combined, bins=bins)
    ha, _ = np.histogram(a, bins=edges, density=True)
    hb, _ = np.histogram(b, bins=edges, density=True)
    return float(np.minimum(ha, hb).sum() * np.diff(edges).mean())


def run_pollution_difference_tests(daily_long: pd.DataFrame) -> pd.DataFrame:
    """Robust two-sample tests: is Balikesir lower than Canakkale on pollution vars?"""
    can = daily_long.loc[daily_long["site_key"] == "canakkale"]
    bal = daily_long.loc[daily_long["site_key"] == "balikesir"]
    overlap_dates = can["date"].isin(bal["date"])
    can = can.loc[overlap_dates].sort_values("date")
    bal = bal.loc[bal["date"].isin(can["date"])].sort_values("date")

    rows: list[dict[str, Any]] = []
    for var in POLLUTION_VARS:
        a = can[var].dropna().to_numpy()
        b = bal[var].dropna().to_numpy()
        if len(a) < 30 or len(b) < 30:
            raise ValueError(f"Insufficient paired coverage for {var}: {len(a)}, {len(b)}")

        median_can = float(np.median(a))
        median_bal = float(np.median(b))
        ci_low, diff_point, ci_high = bootstrap_median_difference_ci(b, a)
        mw = stats.mannwhitneyu(b, a, alternative="less")
        overlap = distribution_overlap(a, b)
        bal_lower = median_bal < median_can and mw.pvalue < 0.05
        rows.append(
            {
                "variable": var,
                "median_canakkale": median_can,
                "median_balikesir": median_bal,
                "median_difference_bal_minus_can": diff_point,
                "median_diff_ci_low": ci_low,
                "median_diff_ci_high": ci_high,
                "distribution_overlap": overlap,
                "mannwhitney_u": float(mw.statistic),
                "mannwhitney_p_less": float(mw.pvalue),
                "balikesir_lower_significant": bal_lower,
                "n_canakkale": len(a),
                "n_balikesir": len(b),
            }
        )
    return pd.DataFrame(rows)


def environmental_verdict(tests: pd.DataFrame) -> str:
    """Plain-language verdict on the pollution premise."""
    core = tests.loc[tests["variable"].isin(("pm10", "dust", "aerosol_optical_depth"))]
    n_lower = int(core["balikesir_lower_significant"].sum())
    if n_lower == len(core):
        return (
            "Balikesir PROVISIONAL coordinates show significantly lower PM10, dust, and AOD "
            "than Canakkale over the shared window (Mann-Whitney one-sided, p<0.05)."
        )
    if n_lower == 0:
        return (
            "Balikesir PROVISIONAL coordinates do NOT show consistently lower pollution than "
            "Canakkale; the proposal premise that Balikesir is cleaner is NOT supported "
            "at this placeholder location."
        )
    return (
        "Mixed result: some pollution metrics favor Balikesir PROVISIONAL coordinates, "
        "others do not. The proposal premise is only partially supported and remains "
        "coordinate-sensitive."
    )


def write_site_comparison_report(
    tests: pd.DataFrame,
    daily_long: pd.DataFrame,
    path: Path | None = None,
) -> Path:
    """Write SITE_COMPARISON.md with verdict and data gaps."""
    out = path or (config.REPORTS / "SITE_COMPARISON.md")
    bal_site = get_site("balikesir")
    verdict = environmental_verdict(tests)

    lines = [
        "# Site environmental comparison (Canakkale vs Balikesir)",
        "",
        "## Status flags",
        "",
        f"- Canakkale: **{provisional_label('canakkale')}** (operational SCADA available).",
        f"- Balikesir: **{provisional_label('balikesir')}** — {bal_site.coordinates_note}",
        "",
        "## Verdict",
        "",
        verdict,
        "",
        "## Pollution test summary",
        "",
        "| Variable | Median Canakkale | Median Balikesir | Med diff (Bal-Can) | "
        "95% CI | Overlap | p (Bal<Can) | Bal lower? |",
        "|---|---:|---:|---:|---|---:|---:|---|",
    ]
    for _, row in tests.iterrows():
        lines.append(
            f"| {row['variable']} | {row['median_canakkale']:.3f} | "
            f"{row['median_balikesir']:.3f} | {row['median_difference_bal_minus_can']:.3f} | "
            f"[{row['median_diff_ci_low']:.3f}, {row['median_diff_ci_high']:.3f}] | "
            f"{row['distribution_overlap']:.3f} | {row['mannwhitney_p_less']:.4g} | "
            f"{'yes' if row['balikesir_lower_significant'] else 'no'} |"
        )

    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Balikesir coordinates are **PROVISIONAL** (no KMZ confirmed; no operational data).",
            "- Comparison is **environmental only** — no performance or soiling "
            "metrics for Balikesir.",
            "- CAMS/Open-Meteo are reanalysis/gridded products, not on-site measurements.",
            "",
            "## Enerjisa data needed for full two-site performance comparison",
            "",
            "1. Confirmed plant coordinates (KMZ or as-built layout).",
            "2. Daily production + plane-of-array irradiance (same schema as Canakkale workbook).",
            "3. Downtime/curtailment log and washing event dates for Balikesir.",
            "4. Inverter-level daily production if feeder/inverter diagnostics are required.",
            "5. Reference irradiance sensor maintenance/cleaning log (both sites).",
            "",
            f"- Analysis window: {config.IRRADIANCE_START_DATE} .. {config.IRRADIANCE_END_DATE}",
            f"- Daily rows compared: Canakkale {tests['n_canakkale'].iloc[0]}, "
            f"Balikesir {tests['n_balikesir'].iloc[0]}",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", out)
    return out


def save_site_comparison_figures(
    daily: pd.DataFrame,
    monthly_long: pd.DataFrame,
    tests: pd.DataFrame,
) -> None:
    """Write PNG (300 dpi) and CSV figure sidecars."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)

    monthly_can = monthly_long.loc[monthly_long["site_key"] == "canakkale"]
    monthly_bal = monthly_long.loc[monthly_long["site_key"] == "balikesir"]

    for var, stem in (
        ("pm10", "site_comparison_pm10_monthly"),
        ("dust", "site_comparison_dust_monthly"),
        ("aerosol_optical_depth", "site_comparison_aod_monthly"),
    ):
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(monthly_can["month"], monthly_can[var], label="Canakkale", marker="o", ms=3)
        ax.plot(
            monthly_bal["month"],
            monthly_bal[var],
            label="Balikesir (PROVISIONAL)",
            marker="s",
            ms=3,
        )
        ax.set_ylabel(var)
        ax.set_title(f"Monthly mean {var} — Canakkale vs Balikesir PROVISIONAL")
        ax.legend()
        fig.autofmt_xdate()
        png = config.FIGURES / f"{stem}.png"
        csv = config.FIGURES / f"{stem}.csv"
        fig.savefig(png, dpi=300, bbox_inches="tight")
        plt.close(fig)
        export = monthly_long[["month", "site_key", var, "provisional"]].copy()
        export.to_csv(csv, index=False)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(
        monthly_can["month"],
        monthly_can["prectotcorr"],
        label="Canakkale",
        marker="o",
        ms=3,
    )
    ax.plot(
        monthly_bal["month"],
        monthly_bal["prectotcorr"],
        label="Balikesir (PROVISIONAL)",
        marker="s",
        ms=3,
    )
    ax.set_ylabel("PRECTOTCORR (mm/day)")
    ax.set_title("Monthly mean rainfall — Canakkale vs Balikesir PROVISIONAL")
    ax.legend()
    fig.autofmt_xdate()
    rain_png = config.FIGURES / "site_comparison_rainfall_monthly.png"
    rain_csv = config.FIGURES / "site_comparison_rainfall_monthly.csv"
    fig.savefig(rain_png, dpi=300, bbox_inches="tight")
    plt.close(fig)
    monthly_long[["month", "site_key", "prectotcorr", "provisional"]].to_csv(rain_csv, index=False)

    fig, ax = plt.subplots(figsize=(8, 4))
    core = tests.loc[tests["variable"].isin(("pm10", "dust", "aerosol_optical_depth"))]
    x = np.arange(len(core))
    width = 0.35
    ax.bar(x - width / 2, core["median_canakkale"], width, label="Canakkale")
    ax.bar(x + width / 2, core["median_balikesir"], width, label="Balikesir PROVISIONAL")
    ax.set_xticks(x)
    ax.set_xticklabels(core["variable"])
    ax.set_ylabel("Median daily value")
    ax.set_title("Median pollution — Canakkale vs Balikesir PROVISIONAL")
    ax.legend()
    bar_png = config.FIGURES / "site_comparison_median_pollution_bar.png"
    bar_csv = config.FIGURES / "site_comparison_median_pollution_bar.csv"
    fig.savefig(bar_png, dpi=300, bbox_inches="tight")
    plt.close(fig)
    core.to_csv(bar_csv, index=False)


def run_site_comparison(force_refresh: bool = False) -> dict[str, Any]:
    """Execute Phase B environmental comparison end-to-end."""
    daily, monthly_long, daily_long = build_site_comparison_frames(force_refresh=force_refresh)
    tests = run_pollution_difference_tests(daily_long)

    stats_block = tests.copy()
    stats_block["record_type"] = "pollution_test"
    export = pd.concat(
        [
            daily.assign(record_type="daily_wide"),
            monthly_long.assign(record_type="monthly_long"),
            daily_long.assign(record_type="daily_long"),
            stats_block,
        ],
        ignore_index=True,
        sort=False,
    )
    write_processed(SITE_COMPARISON_OUTPUT, export)

    write_site_comparison_report(tests, daily_long)
    save_site_comparison_figures(daily, monthly_long, tests)

    return {
        "verdict": environmental_verdict(tests),
        "tests": tests,
        "daily_rows": len(daily),
        "sites": {k: provisional_label(k) for k in COMPARISON_SITE_KEYS},
    }
