"""Unit tests for EPIAS PTF CSV parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from spis.data_sources.epias_ptf import (
    aggregate_ptf_annual,
    ingest_epias_ptf,
    load_ptf_hourly,
    parse_turkish_number,
)


def test_parse_turkish_number() -> None:
    assert parse_turkish_number("3.999,99") == pytest.approx(3999.99)
    assert parse_turkish_number("1.499,98") == pytest.approx(1499.98)


def test_load_ptf_hourly_2023_only() -> None:
    csv_path = Path("data/external/epias_ptf/Piyasa_Takas_Fiyati-01012023-01012024.csv")
    if not csv_path.exists():
        pytest.skip("PTF CSV not present in data/external/epias_ptf/")
    hourly = load_ptf_hourly(csv_path)
    assert (hourly["date"].dt.year == 2023).all()
    assert len(hourly) == 8760
    annual = aggregate_ptf_annual(hourly)
    assert float(annual.iloc[0]["ptf_tl_mwh_mean"]) == pytest.approx(2189.30, rel=0.01)


def test_ingest_epias_ptf_caches() -> None:
    csv_path = Path("data/external/epias_ptf/Piyasa_Takas_Fiyati-01012023-01012024.csv")
    if not csv_path.exists():
        pytest.skip("PTF CSV not present in data/external/epias_ptf/")
    stats = ingest_epias_ptf(force_refresh=True)
    assert stats["year"] == 2023
    assert stats["annual_mean_tl_mwh"] == pytest.approx(2189.30, rel=0.01)
