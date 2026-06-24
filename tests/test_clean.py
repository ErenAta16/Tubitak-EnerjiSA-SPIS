"""Unit tests for the day-level master table builder."""

from __future__ import annotations

import pandas as pd
import pytest

from spis import config
from spis.clean import (
    add_quality_flags,
    apply_temperature_correction,
    build_master_spine,
    compute_low_irradiation_cutoff,
    join_downtime_flags,
    join_washing_segments,
)


def _sample_irradiance() -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", "2023-01-05", freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "eflatun_production": [pd.NA] * len(dates),
            "hipokrat_production": [pd.NA] * len(dates),
            "production": [1000.0, 1100.0, 1200.0, 1300.0, 1400.0],
            "irradiation": [500.0, 600.0, 700.0, 800.0, 900.0],
            "pi": [2.0, 2.0, 2.0, 2.0, 2.0],
        }
    )


def test_build_master_spine_complete(monkeypatch) -> None:
    monkeypatch.setattr(config, "IRRADIANCE_START_DATE", "2023-01-01")
    monkeypatch.setattr(config, "IRRADIANCE_END_DATE", "2023-01-05")
    master = build_master_spine(_sample_irradiance())
    assert len(master) == 5
    assert master["date"].is_monotonic_increasing
    assert master["production"].notna().all()


def test_join_downtime_flags_sets_reason_set() -> None:
    downtime_days = pd.DataFrame(
        {
            "date": [pd.Timestamp("2023-01-02"), pd.Timestamp("2023-01-02")],
            "duration_hours": [2.0, 3.5],
            "reason": ["Kisitlama", "Ariza"],
            "event_id": [1, 2],
            "start_datetime": pd.to_datetime(["2023-01-02", "2023-01-02"]),
            "end_datetime": pd.to_datetime(["2023-01-02", "2023-01-02"]),
            "affected_systems": ["Santral", "Inverter"],
            "curtailment_mw": [pd.NA, pd.NA],
        }
    )
    master = pd.DataFrame({"date": pd.date_range("2023-01-01", "2023-01-03", freq="D")})
    merged = join_downtime_flags(master, downtime_days)
    row = merged.loc[merged["date"] == "2023-01-02"].iloc[0]
    assert row["is_downtime"]
    assert row["is_curtailment"]
    assert row["is_fault"]
    assert row["downtime_hours"] == pytest.approx(5.5)
    assert "Ariza" in row["downtime_reasons"]


def test_temperature_correction_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(config, "NOCT_PEAK_SUN_HOURS", 6.0)
    frame = pd.DataFrame(
        {
            "pi": [2.0, 2.0],
            "nasa_t2m": [5.0, 35.0],
            "nasa_allsky_kwh_m2": [4.0, 4.0],
        }
    )
    corrected = apply_temperature_correction(frame)
    assert corrected["pi_temp_corrected"].between(1.5, 2.5).all()
    assert corrected.loc[1, "pi_temp_corrected"] > corrected.loc[0, "pi_temp_corrected"]


def test_join_washing_segments_resets_and_marks_pre_first_wash() -> None:
    master = pd.DataFrame({"date": pd.date_range("2023-09-10", "2023-10-10", freq="D")})
    washing = pd.DataFrame(
        {
            "start": [pd.Timestamp("2023-09-18"), pd.Timestamp("2023-10-01")],
            "end": [pd.Timestamp("2023-09-20"), pd.Timestamp("2023-10-03")],
            "method": ["brush_solution", "robot_no_solution"],
            "event_index_by_date": [1, 2],
            "segment_id": [1, 2],
        }
    )
    merged = join_washing_segments(master, washing)
    assert merged.loc[merged["date"] == "2023-09-15", "pre_first_wash"].item()
    assert pd.isna(merged.loc[merged["date"] == "2023-09-15", "days_since_wash"].item())
    assert merged.loc[merged["date"] == "2023-09-25", "days_since_wash"].item() == 5
    assert merged.loc[merged["date"] == "2023-10-05", "is_open_segment"].item()


def test_is_clean_observation_logic() -> None:
    frame = pd.DataFrame(
        {
            "is_downtime": [False, True, False, False, False],
            "is_curtailment": [False, False, True, False, False],
            "is_fault": [False, False, False, True, False],
            "irradiation": [1000.0, 1000.0, 1000.0, 1000.0, 100.0],
            "nasa_precip_mm": [0.0, 0.0, 0.0, 0.0, 0.0],
        }
    )
    cleaned, counts = add_quality_flags(frame, cutoff=500.0)
    assert cleaned["is_clean_observation"].tolist() == [True, False, False, False, False]
    assert counts["is_clean_observation"] == 1


def test_compute_low_irradiation_cutoff_uses_percentile(monkeypatch) -> None:
    monkeypatch.setattr(config, "LOW_IRRADIATION_PERCENTILE", 0.2)
    series = pd.Series([100.0, 200.0, 300.0, 400.0, 500.0])
    assert compute_low_irradiation_cutoff(series) == pytest.approx(180.0)
