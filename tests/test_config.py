"""Tests for P18 plant coordinate resolution."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

import spis.config as config_module


def test_coarse_default_coordinates_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLANT_LAT", raising=False)
    monkeypatch.delenv("PLANT_LON", raising=False)
    assert config_module.PLANT_COORD_SOURCE in {"coarse_default", "env"}
    if config_module.PLANT_COORD_SOURCE == "coarse_default":
        assert config_module.PLANT_LAT == pytest.approx(39.9)
        assert config_module.PLANT_LON == pytest.approx(26.2)


def test_exact_coordinates_from_env_subprocess() -> None:
    lat = str(round(39 + 86857 / 100_000, 5))
    lon = str(round(26 + 24152 / 100_000, 5))
    env = dict(os.environ)
    env["PLANT_LAT"] = lat
    env["PLANT_LON"] = lon
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib; import spis.config as c; importlib.reload(c); "
            "print(c.PLANT_COORD_SOURCE, c.PLANT_LAT, c.PLANT_LON)",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    source, out_lat, out_lon = result.stdout.strip().split()
    assert source == "env"
    assert out_lat == lat
    assert out_lon == lon
