"""Shared caching helpers for external API pulls."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)


def cache_path(source: str, name: str) -> Path:
    """Return the cache directory for a named external source artifact.

    ``source`` may include a site subpath, e.g. ``nasa_power/balikesir``.
    """
    from spis import config

    path = config.DATA_EXTERNAL / source
    path.mkdir(parents=True, exist_ok=True)
    return path / name


def write_cache(
    source: str,
    parquet_name: str,
    sidecar_name: str,
    frame: pd.DataFrame,
    metadata: dict[str, Any],
) -> Path:
    """Persist a DataFrame and JSON sidecar with request metadata."""
    parquet_path = cache_path(source, parquet_name)
    sidecar_path = cache_path(source, sidecar_name)
    frame.to_parquet(parquet_path, index=False)
    payload = {
        **metadata,
        "pull_timestamp_utc": datetime.now(UTC).isoformat(),
        "rows": len(frame),
    }
    sidecar_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LOGGER.info("Cached %s rows to %s", len(frame), parquet_path)
    return parquet_path


def read_cache(
    source: str, parquet_name: str, sidecar_name: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read cached DataFrame and sidecar if both exist."""
    parquet_path = cache_path(source, parquet_name)
    sidecar_path = cache_path(source, sidecar_name)
    if parquet_path.exists() and sidecar_path.exists():
        frame = pd.read_parquet(parquet_path)
        metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
        LOGGER.info("Using cached external data from %s", parquet_path)
        return frame, metadata
    raise FileNotFoundError(f"Cache miss for {source}/{parquet_name}")
