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
from spis.data_sources.national_aq import fetch_national_aq_daily, get_national_station
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


def compare_ground_to_cams(
    ground: pd.DataFrame,
    cams: pd.DataFrame,
    site_key: str,
    pollutant: str = "pm10",
) -> dict[str, Any]:
    """Compare in-situ ground PM with CAMS PM at daily scale."""
    cams_col = pollutant
    ground_col = pollutant
    merged = ground[["date", ground_col]].merge(
        cams[["date", cams_col]].rename(columns={cams_col: "cams_value"}),
        on="date",
        how="inner",
    )
    merged = merged.dropna(subset=[ground_col, "cams_value"])
    if len(merged) < 30:
        raise ValueError(
            f"Insufficient paired ground/CAMS days for {site_key} {pollutant}: {len(merged)}"
        )

    ground_vals = merged[ground_col].to_numpy()
    cams_vals = merged["cams_value"].to_numpy()
    bias = ground_vals - cams_vals
    pearson = float(stats.pearsonr(ground_vals, cams_vals).statistic)
    spearman = float(stats.spearmanr(ground_vals, cams_vals).statistic)
    return {
        "site_key": site_key,
        "pollutant": pollutant,
        "station_code": ground["station_code"].iloc[0],
        "station_name": ground["station_name"].iloc[0],
        "n_pairs": len(merged),
        "pearson_r": pearson,
        "spearman_r": spearman,
        "median_bias_ground_minus_cams": float(np.median(bias)),
        "mean_bias_ground_minus_cams": float(np.mean(bias)),
        "mae": float(np.mean(np.abs(bias))),
        "ground_median": float(np.median(ground_vals)),
        "cams_median": float(np.median(cams_vals)),
        "paired_frame": merged.rename(columns={ground_col: "ground_value"}),
    }


def ground_cams_verdict(row: pd.Series) -> str:
    """Plain-language statement on CAMS representativeness vs ground PM."""
    label = str(row["pollutant"]).upper().replace("_", ".")
    if row["median_bias_ground_minus_cams"] > 10 and row["pearson_r"] < 0.4:
        return (
            f"Ground {label} is materially higher than CAMS with weak daily correlation; "
            "gridded CAMS likely understates local particulate loading."
        )
    if row["median_bias_ground_minus_cams"] > 5:
        return (
            f"Ground {label} exceeds CAMS on median; CAMS captures direction but may "
            f"underestimate absolute local {label}."
        )
    if abs(row["median_bias_ground_minus_cams"]) <= 5 and row["pearson_r"] >= 0.4:
        return (
            f"Ground and CAMS {label} agree in magnitude and covary on daily scale; "
            "CAMS is a reasonable proxy for relative pollution context."
        )
    return (
        f"Mixed agreement for {label}: CAMS tracks some ground variability but bias and "
        "correlation do not support treating CAMS as a precise local substitute."
    )


def run_ground_cams_validation(
    site_frames: dict[str, pd.DataFrame],
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Fetch national ground AQ and compare to CAMS for each configured site."""
    rows: list[dict[str, Any]] = []
    paired: dict[str, pd.DataFrame] = {}
    for site_key in COMPARISON_SITE_KEYS:
        ground, _ = fetch_national_aq_daily(site_key=site_key, force_refresh=force_refresh)
        cams = site_frames[site_key][["date", "pm10", "pm2_5"]]
        for pollutant in ("pm10", "pm2_5"):
            if pollutant == "pm2_5" and ground["pm2_5"].notna().sum() < 30:
                LOGGER.warning(
                    "Skipping ground/CAMS PM2.5 comparison for %s: insufficient ground coverage",
                    site_key,
                )
                continue
            stats = compare_ground_to_cams(ground, cams, site_key, pollutant=pollutant)
            paired_frame = stats.pop("paired_frame")
            if pollutant == "pm10":
                paired[site_key] = paired_frame
            rows.append(stats)
    result = pd.DataFrame(rows)
    result["verdict"] = result.apply(ground_cams_verdict, axis=1)
    return result, paired


def write_site_comparison_report(
    tests: pd.DataFrame,
    daily_long: pd.DataFrame,
    ground_stats: pd.DataFrame | None = None,
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

    if ground_stats is not None and not ground_stats.empty:
        lines.extend(["", "## Ground-station vs CAMS cross-check (national network)", ""])
        lines.append(
            "In-situ PM from sim.csb.gov.tr daily exports (StationDataDownloadNewData). "
            "Canakkale: **TR170141** (Canakkale Merkez UHKIA). "
            "Balikesir proxy: **TR100241** (Bandirma-MTHM; nearest national station to "
            "PROVISIONAL Balikesir coordinates)."
        )
        lines.extend(
            [
                "",
                "| Site | Pollutant | Station | n | Pearson r | Median bias (g-c) | "
                "Ground med. | CAMS med. | Verdict |",
                "|---|---|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for _, row in ground_stats.iterrows():
            prov = " PROVISIONAL" if row["site_key"] == "balikesir" else ""
            lines.append(
                f"| {row['site_key']}{prov} | {row['pollutant']} | {row['station_code']} | "
                f"{int(row['n_pairs'])} | {row['pearson_r']:.3f} | "
                f"{row['median_bias_ground_minus_cams']:.2f} | {row['ground_median']:.1f} | "
                f"{row['cams_median']:.1f} | {row['verdict']} |"
            )
        pm10 = ground_stats.loc[ground_stats["pollutant"] == "pm10"]
        if not pm10.empty:
            lines.extend(["", "### Ground PM10 synthesis", ""])
            for _, row in pm10.iterrows():
                lines.append(f"- **{row['site_key']}**: {row['verdict']}")
            can_row = pm10.loc[pm10["site_key"] == "canakkale"]
            if not can_row.empty:
                ratio = float(can_row.iloc[0]["ground_median"] / can_row.iloc[0]["cams_median"])
                lines.extend(
                    [
                        "",
                        "Implication for SPIS: national ground PM10 at Canakkale exceeds CAMS "
                        f"by ~{ratio:.1f}x on median ({can_row.iloc[0]['ground_median']:.1f} vs "
                        f"{can_row.iloc[0]['cams_median']:.1f} ug/m3). Weak daily pollution–"
                        "performance links remain credible: CAMS supports relative "
                        "context but not absolute local particulate load.",
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


def save_ground_vs_cams_figures(paired: dict[str, pd.DataFrame]) -> None:
    """Scatter + monthly mean overlay of ground PM10 vs CAMS PM10."""
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    export_rows: list[pd.DataFrame] = []

    for site_key, frame in paired.items():
        station = get_national_station(site_key)
        prov = " PROVISIONAL" if site_key == "balikesir" else ""
        label = f"{site_key}{prov} ({station.station_code})"

        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        axes[0].scatter(frame["cams_value"], frame["ground_value"], alpha=0.35, s=12)
        max_val = max(frame["cams_value"].max(), frame["ground_value"].max())
        axes[0].plot([0, max_val], [0, max_val], "k--", linewidth=0.8, label="1:1")
        axes[0].set_xlabel("CAMS PM10 (ug/m3)")
        axes[0].set_ylabel("Ground PM10 (ug/m3)")
        axes[0].set_title(f"Daily ground vs CAMS PM10 — {label}")
        axes[0].legend()

        monthly = frame.copy()
        monthly["month"] = monthly["date"].dt.to_period("M").dt.to_timestamp()
        grouped = monthly.groupby("month", as_index=False)[["ground_value", "cams_value"]].mean()
        axes[1].plot(grouped["month"], grouped["ground_value"], marker="o", label="Ground PM10")
        axes[1].plot(grouped["month"], grouped["cams_value"], marker="s", label="CAMS PM10")
        axes[1].set_title(f"Monthly mean PM10 — {label}")
        axes[1].legend()
        fig.autofmt_xdate()

        stem = f"site_comparison_ground_vs_cams_{site_key}"
        png = config.FIGURES / f"{stem}.png"
        csv = config.FIGURES / f"{stem}.csv"
        fig.savefig(png, dpi=300, bbox_inches="tight")
        plt.close(fig)
        export = grouped.assign(site_key=site_key, station_code=station.station_code)
        export.to_csv(csv, index=False)
        export_rows.append(frame.assign(site_key=site_key, station_code=station.station_code))

    if export_rows:
        combined = pd.concat(export_rows, ignore_index=True)
        combined.to_csv(config.FIGURES / "site_comparison_ground_vs_cams_daily.csv", index=False)


def run_site_comparison(force_refresh: bool = False) -> dict[str, Any]:
    """Execute Phase B environmental comparison end-to-end."""
    daily, monthly_long, daily_long = build_site_comparison_frames(force_refresh=force_refresh)
    tests = run_pollution_difference_tests(daily_long)
    site_frames = {
        site_key: daily_long.loc[daily_long["site_key"] == site_key].copy()
        for site_key in COMPARISON_SITE_KEYS
    }
    ground_stats, paired = run_ground_cams_validation(site_frames, force_refresh=force_refresh)

    stats_block = tests.copy()
    stats_block["record_type"] = "pollution_test"
    ground_block = ground_stats.copy()
    ground_block["record_type"] = "ground_cams_validation"
    export = pd.concat(
        [
            daily.assign(record_type="daily_wide"),
            monthly_long.assign(record_type="monthly_long"),
            daily_long.assign(record_type="daily_long"),
            stats_block,
            ground_block,
        ],
        ignore_index=True,
        sort=False,
    )
    write_processed(SITE_COMPARISON_OUTPUT, export)

    write_site_comparison_report(tests, daily_long, ground_stats=ground_stats)
    save_site_comparison_figures(daily, monthly_long, tests)
    save_ground_vs_cams_figures(paired)

    return {
        "verdict": environmental_verdict(tests),
        "tests": tests,
        "ground_stats": ground_stats,
        "daily_rows": len(daily),
        "sites": {k: provisional_label(k) for k in COMPARISON_SITE_KEYS},
    }
