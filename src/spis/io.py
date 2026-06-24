"""Parquet I/O for interim and processed artifacts."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from spis.sites import DEFAULT_SITE, site_interim_path, site_processed_path

LOGGER = logging.getLogger(__name__)


def write_interim(
    name: str,
    frame: pd.DataFrame,
    site_key: str = DEFAULT_SITE,
) -> Path:
    """Write a validated frame to site interim storage."""
    path = site_interim_path(site_key, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    LOGGER.info("Wrote %s rows to %s", len(frame), path)
    return path


def read_interim(name: str, site_key: str = DEFAULT_SITE) -> pd.DataFrame:
    """Read an interim Parquet artifact by basename and site."""
    path = site_interim_path(site_key, name)
    if not path.exists():
        raise FileNotFoundError(f"Interim artifact not found: {path}")
    frame = pd.read_parquet(path)
    LOGGER.info("Read %s rows from %s", len(frame), path)
    return frame


def write_processed(
    name: str,
    frame: pd.DataFrame,
    site_key: str = DEFAULT_SITE,
) -> Path:
    """Write a validated frame to site processed storage."""
    path = site_processed_path(site_key, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    LOGGER.info("Wrote %s rows to %s", len(frame), path)
    return path


def read_processed(name: str, site_key: str = DEFAULT_SITE) -> pd.DataFrame:
    """Read a processed Parquet artifact by basename and site."""
    path = site_processed_path(site_key, name)
    if not path.exists():
        raise FileNotFoundError(f"Processed artifact not found: {path}")
    frame = pd.read_parquet(path)
    LOGGER.info("Read %s rows from %s", len(frame), path)
    return frame
