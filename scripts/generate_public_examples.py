"""Build compact public PVDAQ 2107 and DKASC array 14 dashboard snapshots."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spis import config  # noqa: E402
from spis.data_sources.dkasc import VALIDATION_ARRAYS  # noqa: E402
from spis.external_validation import (  # noqa: E402
    EXTERNAL_VALIDATION_OUTPUT,
    _analyze_dkasc_array,
    build_dkasc_array_master,
)
from spis.public_examples import (  # noqa: E402
    DKASC_KEY,
    PVDAQ_2107_KEY,
    public_artifact_path,
    public_example_dir,
)
from spis.robustness import ROBUSTNESS_OUTPUT_NAME  # noqa: E402
from spis.soiling import MASTER_INPUT_NAME, SOILING_OUTPUT_NAME  # noqa: E402

MASTER_COLUMNS = (
    "date",
    "production",
    "irradiation",
    "pi",
    "pi_temp_corrected",
    "is_clean_observation",
    "segment_id",
    "days_since_wash",
)
FORBIDDEN_FIELD_TOKENS = ("enerjisa", "canakkale", "çanakkale", "latitude", "longitude")


def _public_master(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in MASTER_COLUMNS if column not in frame]
    if missing:
        raise ValueError(f"Public master is missing dashboard columns: {missing}")
    return frame.loc[:, MASTER_COLUMNS].copy()


def _robustness_row(
    *, rate: float, lower: float, upper: float, basis: str, pollution_verdict: str
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "p4_verdict",
                "recommended_rate_pct_per_day": rate,
                "recommended_uncertainty_half_width": (upper - lower) / 2.0,
                "rate_basis": basis,
                "pollution_verdict": pollution_verdict,
            }
        ]
    )


def _assert_public_only(frames: dict[str, pd.DataFrame]) -> None:
    for name, frame in frames.items():
        normalized_columns = " ".join(str(column).lower() for column in frame.columns)
        if any(token in normalized_columns for token in FORBIDDEN_FIELD_TOKENS):
            raise ValueError(f"Forbidden field found in {name}")
        text_columns = frame.select_dtypes(include=["object", "string"])
        text = " ".join(text_columns.fillna("").astype(str).to_numpy().ravel()).lower()
        if any(token in text for token in FORBIDDEN_FIELD_TOKENS):
            raise ValueError(f"Forbidden value found in {name}")


def _write_bundle(site_key: str, frames: dict[str, pd.DataFrame]) -> None:
    _assert_public_only(frames)
    public_example_dir(site_key).mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_parquet(public_artifact_path(site_key, name), index=False)


def generate_pvdaq_2107() -> None:
    processed = config.DATA_PROCESSED / PVDAQ_2107_KEY
    master = pd.read_parquet(processed / f"{MASTER_INPUT_NAME}.parquet")
    segments = pd.read_parquet(processed / f"{SOILING_OUTPUT_NAME}.parquet")
    validation = pd.read_parquet(processed / "pvdaq_validation.parquet")
    row = validation.loc[
        (validation["record_type"] == "utility_comparison")
        & (validation["site_key"] == PVDAQ_2107_KEY)
    ].iloc[0]
    pollution_verdict = (
        "Daily accumulated CAMS pollution does NOT significantly predict PI decay "
        "residuals (HAC p>=0.05 or wrong sign)."
    )
    robustness = _robustness_row(
        rate=float(row["clear_sky_rate_pct_per_day"]),
        lower=float(row["clear_sky_ci_lower"]),
        upper=float(row["clear_sky_ci_upper"]),
        basis="NREL PVDAQ 2107 clear-sky pooled (inferred cleanings)",
        pollution_verdict=pollution_verdict,
    )
    _write_bundle(
        PVDAQ_2107_KEY,
        {
            MASTER_INPUT_NAME: _public_master(master),
            SOILING_OUTPUT_NAME: segments,
            ROBUSTNESS_OUTPUT_NAME: robustness,
        },
    )


def generate_dkasc() -> None:
    array = next(item for item in VALIDATION_ARRAYS if item.array_number == "14")
    master, _ = build_dkasc_array_master(array, force_refresh=False)
    analysis = _analyze_dkasc_array(master, array)
    validated = pd.read_parquet(
        config.DATA_PROCESSED / DKASC_KEY / f"{EXTERNAL_VALIDATION_OUTPUT}.parquet"
    )
    row = validated.loc[
        (validated["record_type"] == "site_comparison")
        & (validated["site_key"] == DKASC_KEY)
        & (validated["array_number"].astype(str) == array.array_number)
    ].iloc[0]
    clear = analysis["clear_pooled"]
    for generated_key, validated_key in (
        ("pooled_rate", "clear_sky_pooled_rate_pct_per_day"),
        ("pooled_ci_lower", "clear_sky_ci_lower"),
        ("pooled_ci_upper", "clear_sky_ci_upper"),
    ):
        if not np.isclose(float(clear[generated_key]), float(row[validated_key]), atol=1e-12):
            raise ValueError(f"DKASC array 14 {generated_key} differs from validation report")
    robustness = _robustness_row(
        rate=float(clear["pooled_rate"]),
        lower=float(clear["pooled_ci_lower"]),
        upper=float(clear["pooled_ci_upper"]),
        basis="DKASC Alice Springs array 14 clear-sky pooled (inferred cleanings)",
        pollution_verdict=str(analysis["pollution_summary"]["pollution_verdict"]),
    )
    _write_bundle(
        DKASC_KEY,
        {
            MASTER_INPUT_NAME: _public_master(master),
            SOILING_OUTPUT_NAME: analysis["segments"],
            ROBUSTNESS_OUTPUT_NAME: robustness,
        },
    )


def main() -> int:
    generate_pvdaq_2107()
    generate_dkasc()
    print("Wrote public PVDAQ 2107 and DKASC array 14 example bundles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
