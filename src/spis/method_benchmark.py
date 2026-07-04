"""P17 Phase B: benchmark SPIS clear-sky soiling vs RdTools stochastic rate and recovery."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from spis import config
from spis.clean import MASTER_OUTPUT_NAME
from spis.external_validation import (
    CANAKKALE_SITE_KEY,
    CANONICAL_CI_METHOD,
    detect_inferred_cleaning_events,
    load_canakkale_baseline,
)
from spis.io import read_processed, write_processed
from spis.pvdaq_validation import PVDAQ_2107_SITE_KEY, PVDAQ_VALIDATION_OUTPUT
from spis.robustness import (
    attach_clearness_index,
    canonical_clear_sky_pooled,
    compare_clear_sky_slopes,
)
from spis.sites import get_site
from spis.soiling import build_soiling_segments

LOGGER = logging.getLogger(__name__)

METHOD_BENCHMARK_OUTPUT = "method_benchmark"


def _require_rdtools():
    try:
        import rdtools
        from rdtools import soiling
    except ImportError as exc:
        raise ImportError(
            "rdtools is required for method benchmark. "
            "Install with: pip install -r requirements-bench.txt"
        ) from exc
    return rdtools, soiling


def _to_rdtools_daily(series: pd.Series) -> pd.Series:
    """Normalize to regular daily DatetimeIndex required by RdTools."""
    daily = series.copy()
    daily.index = pd.to_datetime(daily.index).normalize()
    daily = daily.groupby(level=0).mean().sort_index()
    full_index = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    return daily.reindex(full_index)


def _daily_series_for_srr(master: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series | None]:
    """Prepare daily PI, insolation, and precipitation for RdTools SRR."""
    frame = master.sort_values("date").copy()
    frame = frame.set_index(pd.to_datetime(frame["date"]))
    pi = _to_rdtools_daily(frame["pi_temp_corrected"].astype(float))
    insolation = _to_rdtools_daily(frame["irradiation"].astype(float))
    precip: pd.Series | None = None
    if "onsite_rainfall_mm" in frame.columns:
        precip = _to_rdtools_daily(frame["onsite_rainfall_mm"].astype(float))
    elif "nasa_precip_mm" in frame.columns:
        precip = _to_rdtools_daily(frame["nasa_precip_mm"].astype(float))
    return pi, insolation, precip


def run_rdtools_srr(
    master: pd.DataFrame,
    *,
    reps: int = 300,
) -> dict[str, Any]:
    """Run RdTools soiling_srr and return headline metrics."""
    _rdtools, soiling = _require_rdtools()
    pi, insolation, precip = _daily_series_for_srr(master)
    kwargs: dict[str, Any] = {
        "energy_normalized_daily": pi,
        "insolation_daily": insolation,
        "reps": reps,
        "clean_criterion": "shift",
    }
    if precip is not None:
        kwargs["precipitation_daily"] = precip.fillna(0.0)

    with np.errstate(all="ignore"):
        sratio, ci, soiling_info = soiling.soiling_srr(**kwargs)

    interval_summary = soiling_info.get("soiling_interval_summary")
    median_interval_slope = float("nan")
    if interval_summary is not None and not interval_summary.empty:
        valid_intervals = interval_summary.loc[interval_summary.get("valid", True)]
        if "soiling_rate" in valid_intervals.columns and not valid_intervals.empty:
            # RdTools soiling_rate is fractional loss per day; SPIS reports %/day.
            median_interval_slope = float(valid_intervals["soiling_rate"].median() * 100.0)

    return {
        "srr_soiling_ratio": float(sratio),
        "srr_ci_lower": float(ci[0]),
        "srr_ci_upper": float(ci[1]),
        "srr_median_interval_slope_pct_per_day": median_interval_slope,
        "srr_interval_count": int(len(interval_summary)) if interval_summary is not None else 0,
        "soiling_info": soiling_info,
    }


def spis_clear_sky_metrics(master: pd.DataFrame, site_key: str) -> dict[str, Any]:
    """Compute SPIS canonical clear-sky pooled rate for benchmark comparison."""
    if site_key == CANAKKALE_SITE_KEY:
        baseline = load_canakkale_baseline()
        clear = baseline["clear_pooled"]
        return {
            "spis_rate_pct_per_day": clear["pooled_rate"],
            "spis_ci_lower": clear["pooled_ci_lower"],
            "spis_ci_upper": clear["pooled_ci_upper"],
            "ci_method": clear["ci_method"],
        }

    if site_key == PVDAQ_2107_SITE_KEY:
        export = read_processed(PVDAQ_VALIDATION_OUTPUT, site_key=site_key)
        row = export.loc[
            (export["record_type"] == "utility_comparison")
            & (export["site_key"] == PVDAQ_2107_SITE_KEY)
        ].iloc[0]
        return {
            "spis_rate_pct_per_day": float(row["clear_sky_rate_pct_per_day"]),
            "spis_ci_lower": float(row["clear_sky_ci_lower"]),
            "spis_ci_upper": float(row["clear_sky_ci_upper"]),
            "ci_method": row["ci_method"],
        }

    washing = detect_inferred_cleaning_events(master)
    segments = build_soiling_segments(master, washing)
    master_clear = attach_clearness_index(master)
    segment_compare = compare_clear_sky_slopes(master_clear, segments)
    clear = canonical_clear_sky_pooled(segment_compare)
    return {
        "spis_rate_pct_per_day": clear["pooled_rate"],
        "spis_ci_lower": clear["pooled_ci_lower"],
        "spis_ci_upper": clear["pooled_ci_upper"],
        "ci_method": clear["ci_method"],
    }


def srr_slope_from_ratio(ratio: float, interval_days: float = 30.0) -> float:
    """Convert RdTools soiling ratio to equivalent linear %/day over an interval."""
    if ratio <= 0 or interval_days <= 0:
        return float("nan")
    return float((1.0 - ratio) * 100.0 / interval_days)


def benchmark_site(
    site_key: str,
    master: pd.DataFrame | None = None,
    *,
    srr_reps: int = 300,
) -> dict[str, Any]:
    """Run SPIS and RdTools metrics for one site."""
    if master is None:
        master = read_processed(MASTER_OUTPUT_NAME, site_key=site_key)

    spis = spis_clear_sky_metrics(master, site_key)
    srr = run_rdtools_srr(master, reps=srr_reps)

    spis_rate = float(spis["spis_rate_pct_per_day"])
    srr_equiv_slope = srr_slope_from_ratio(float(srr["srr_soiling_ratio"]))
    median_interval = srr["srr_median_interval_slope_pct_per_day"]

    sign_agree = (
        pd.notna(spis_rate)
        and pd.notna(median_interval)
        and np.sign(spis_rate) == np.sign(median_interval)
    )
    magnitude_close = (
        pd.notna(spis_rate)
        and pd.notna(median_interval)
        and abs(spis_rate - median_interval) < max(0.05, abs(spis_rate) * 0.5)
    )

    if sign_agree and magnitude_close:
        agreement = "qualitative agreement on sign and order of magnitude"
    elif sign_agree:
        agreement = "sign agreement only; magnitudes differ (expected under different segmentation)"
    else:
        agreement = "methods disagree on sign — investigate rain/cleaning segmentation"

    return {
        "site_key": site_key,
        "site_name": get_site(site_key).name,
        **spis,
        **srr,
        "srr_equiv_slope_pct_per_day_30d": srr_equiv_slope,
        "agreement_verdict": agreement,
    }


def benchmark_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Tabular SPIS vs RdTools comparison."""
    records: list[dict[str, Any]] = []
    for row in rows:
        records.append(
            {
                "site": row["site_name"],
                "site_key": row["site_key"],
                "spis_clear_sky_rate_pct_per_day": row["spis_rate_pct_per_day"],
                "spis_ci_lower": row["spis_ci_lower"],
                "spis_ci_upper": row["spis_ci_upper"],
                "spis_ci_method": row["ci_method"],
                "rdtools_srr_ratio": row["srr_soiling_ratio"],
                "rdtools_srr_ci_lower": row["srr_ci_lower"],
                "rdtools_srr_ci_upper": row["srr_ci_upper"],
                "rdtools_median_interval_slope_pct_per_day": row[
                    "srr_median_interval_slope_pct_per_day"
                ],
                "rdtools_interval_count": row["srr_interval_count"],
                "agreement_verdict": row["agreement_verdict"],
            }
        )
    return pd.DataFrame(records)


def write_method_benchmark_report(table: pd.DataFrame) -> str:
    """Write reports/METHOD_BENCHMARK.md and return overall verdict text."""
    path = config.REPORTS / "METHOD_BENCHMARK.md"
    can = table.loc[table["site_key"] == CANAKKALE_SITE_KEY].iloc[0]
    pv = table.loc[table["site_key"] == PVDAQ_2107_SITE_KEY].iloc[0]

    overall = (
        "RdTools SRR (Deceglie et al. 2018) targets a sawtooth of dry accumulation plus "
        "sharp cleaning events. Canakkale's frequent rain and logged washes may yield "
        "little SRR-detected soiling — consistent with our rain-as-cleaning finding. "
        f"Canakkale: SPIS {can['spis_clear_sky_rate_pct_per_day']:.4f} %/day vs "
        f"RdTools median interval slope "
        f"{can['rdtools_median_interval_slope_pct_per_day']:.4f} %/day "
        f"({can['agreement_verdict']}). "
        f"PVDAQ 2107: SPIS {pv['spis_clear_sky_rate_pct_per_day']:.4f} %/day vs "
        f"RdTools {pv['rdtools_median_interval_slope_pct_per_day']:.4f} %/day "
        f"({pv['agreement_verdict']}). "
        "SPIS clear-sky Theil-Sen pooled rate and RdTools SRR interval slopes are not "
        "identical estimands: SPIS uses logged/inferred wash segments with clearness "
        "filtering; SRR uses stochastic cleaning detection on daily PI. Compare sign "
        "and order of magnitude, not point equality."
    )

    lines = [
        "# Method benchmark — SPIS vs RdTools SRR",
        "",
        "## Verdict",
        "",
        overall,
        "",
        "## Representation conversion",
        "",
        "- **SPIS:** segment Theil-Sen slopes on clear-sky days, pooled with "
        f"`{CANONICAL_CI_METHOD}` CI half-width.",
        "- **RdTools SRR:** insolation-weighted daily PI (`pi_temp_corrected`) with "
        "stochastic cleaning detection (`clean_criterion='shift'`); headline outputs are "
        "soiling ratio (energy lost fraction) plus per-interval `%/day` slopes in "
        "`soiling_interval_summary`.",
        "- **Comparison rule:** qualitative sign agreement and order-of-magnitude check; "
        "no parameter tuning to force match.",
        "",
        "## Side-by-side table",
        "",
        "| Site | SPIS rate (%/day) | SPIS 95% CI | RdTools SRR ratio | RdTools ratio CI | "
        "RdTools median interval slope (%/day) | Intervals | Agreement |",
        "|---|---:|---|---:|---|---:|---:|---|",
    ]
    for _, row in table.iterrows():
        lines.append(
            f"| {row['site']} | {row['spis_clear_sky_rate_pct_per_day']:.4f} | "
            f"[{row['spis_ci_lower']:.4f}, {row['spis_ci_upper']:.4f}] | "
            f"{row['rdtools_srr_ratio']:.4f} | "
            f"[{row['rdtools_srr_ci_lower']:.4f}, {row['rdtools_srr_ci_upper']:.4f}] | "
            f"{row['rdtools_median_interval_slope_pct_per_day']:.4f} | "
            f"{int(row['rdtools_interval_count'])} | {row['agreement_verdict']} |"
        )

    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- Canakkale uses horizontal SCADA irradiance; PVDAQ uses POA — RdTools expects "
            "POA insolation; Canakkale comparison is approximate.",
            "- Neither method uses operator wash logs for PVDAQ or DKASC; cleaning inference "
            "differs between SPIS segments and SRR stochastic detection.",
            "- RdTools installed from `requirements-bench.txt`; core SPIS pipeline does not "
            "import rdtools.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)
    return overall


def run_method_benchmark(srr_reps: int = 300) -> dict[str, Any]:
    """Execute P17 Phase B benchmark for Canakkale and PVDAQ 2107."""
    can_master = read_processed(MASTER_OUTPUT_NAME, site_key=CANAKKALE_SITE_KEY)
    pv_master = read_processed(MASTER_OUTPUT_NAME, site_key=PVDAQ_2107_SITE_KEY)

    rows = [
        benchmark_site(CANAKKALE_SITE_KEY, can_master, srr_reps=srr_reps),
        benchmark_site(PVDAQ_2107_SITE_KEY, pv_master, srr_reps=srr_reps),
    ]
    table = benchmark_table(rows)
    verdict = write_method_benchmark_report(table)

    export = table.copy()
    export["record_type"] = "spis_vs_rdtools"
    write_processed(
        METHOD_BENCHMARK_OUTPUT,
        export,
        site_key=PVDAQ_2107_SITE_KEY,
    )

    return {"table": table, "verdict": verdict, "rows": rows}
