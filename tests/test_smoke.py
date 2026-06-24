"""Smoke tests for project configuration constants."""

from __future__ import annotations

from pathlib import Path

import spis.config as config


def test_project_path_constants_exist() -> None:
    """Project directory constants are defined as Path objects."""
    path_names = (
        "ROOT",
        "DATA_RAW",
        "DATA_INTERIM",
        "DATA_PROCESSED",
        "DATA_EXTERNAL",
        "REPORTS",
        "FIGURES",
    )
    for name in path_names:
        value = getattr(config, name)
        assert isinstance(value, Path), f"{name} must be a pathlib.Path"


def test_raw_file_constants_have_expected_extensions() -> None:
    """Each raw input constant uses the contract filename extension."""
    raw_files = (
        (config.RAW_IRRADIANCE_PRODUCTION, ".xlsx"),
        (config.RAW_DOWNTIME_EVENTS, ".xlsx"),
        (config.RAW_INVERTER_DAILY, ".xlsx"),
        (config.RAW_WASHING_DATES, ".txt"),
    )
    for path, suffix in raw_files:
        assert isinstance(path, Path)
        assert path.name.endswith(suffix), f"{path.name} must end with {suffix}"


def test_config_dataclass_exposes_paths() -> None:
    """The typed config namespace mirrors module-level path constants."""
    assert config.config.root == config.ROOT
    assert config.config.data_raw == config.DATA_RAW
    assert config.config.raw_washing_dates == config.RAW_WASHING_DATES
