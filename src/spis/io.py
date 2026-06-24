"""Parquet I/O for interim and processed artifacts."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from spis import config

LOGGER = logging.getLogger(__name__)


def write_interim(name: str, frame: pd.DataFrame) -> Path:
    """Write a validated frame to ``data/interim/{name}.parquet``.

    Args:
        name: Basename without extension.
        frame: DataFrame to persist.

    Returns:
        Path to the written Parquet file.
    """
    config.DATA_INTERIM.mkdir(parents=True, exist_ok=True)
    path = config.DATA_INTERIM / f"{name}.parquet"
    frame.to_parquet(path, index=False)
    LOGGER.info("Wrote %s rows to %s", len(frame), path)
    return path


def read_interim(name: str) -> pd.DataFrame:
    """Read an interim Parquet artifact by basename."""
    path = config.DATA_INTERIM / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Interim artifact not found: {path}")
    frame = pd.read_parquet(path)
    LOGGER.info("Read %s rows from %s", len(frame), path)
    return frame
