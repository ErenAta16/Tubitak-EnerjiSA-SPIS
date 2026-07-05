"""Tests for synthetic demo plant snapshot."""

from __future__ import annotations

import subprocess

import pytest

from spis.demo_plant import (
    DEMO_PLANT_DIR,
    demo_data_available,
    generate_demo_plant_artifacts,
    load_demo_headline_metrics,
)


def test_demo_plant_snapshot_is_committed() -> None:
    assert demo_data_available()
    assert (DEMO_PLANT_DIR / "master_daily.parquet").exists()


def test_demo_headline_metrics_are_synthetic() -> None:
    metrics = load_demo_headline_metrics()
    assert metrics["clear_sky_rate_pct_per_day"] == pytest.approx(-0.15, abs=0.05)
    assert metrics["daily_energy_kwh"] > 0
    assert metrics["rate_band"].point > 0


def test_generate_demo_plant_is_deterministic(tmp_path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    generate_demo_plant_artifacts(output_dir=out_a, seed=42)
    generate_demo_plant_artifacts(output_dir=out_b, seed=42)
    hash_a = (out_a / "master_daily.parquet").read_bytes()
    hash_b = (out_b / "master_daily.parquet").read_bytes()
    assert hash_a == hash_b


def test_only_approved_example_data_is_tracked() -> None:
    tracked = subprocess.check_output(["git", "ls-files", "data/"], text=True).splitlines()
    tracked = [line for line in tracked if line.strip()]
    allowed = (
        "data/examples/demo_plant/",
        "data/examples/pvdaq_2107/",
        "data/examples/dkasc/",
    )
    assert tracked, "Expected committed examples under data/"
    assert all(line.startswith(allowed) or line.endswith(".gitkeep") for line in tracked)
    assert all(any(line.startswith(prefix) for line in tracked) for prefix in allowed)
