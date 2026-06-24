"""Unit tests for ingestion loaders."""

from __future__ import annotations

import pandas as pd
import pytest

from spis import config
from spis.ingest import (
    coerce_comma_decimal,
    transform_downtime,
    transform_inverter,
    transform_irradiance,
    transform_washing,
)


def _build_irradiance_raw() -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", "2023-01-03", freq="D")
    return pd.DataFrame(
        {
            "TARIH": dates,
            " EFLATUN OG NET URETIM": [pd.NA, pd.NA, "100,5"],
            " HIPOKRAT OG NET URETIM": [pd.NA, pd.NA, "200,25"],
            "GUNLUK TOTAL URETIM": ["10,5", "20", "30,75"],
            "ISINIM": ["2,1", "4", "5,5"],
            "DURUM": [pd.NA, pd.NA, pd.NA],
        }
    )


def test_coerce_comma_decimal_parses_locale_strings() -> None:
    series = pd.Series(["7,65", "10", "3,5"])
    parsed = coerce_comma_decimal(series)
    assert parsed.tolist() == pytest.approx([7.65, 10.0, 3.5])


def test_transform_irradiance_shape_dtypes_and_complete_index(monkeypatch) -> None:
    monkeypatch.setattr(config, "IRRADIANCE_START_DATE", "2023-01-01")
    monkeypatch.setattr(config, "IRRADIANCE_END_DATE", "2023-01-03")

    frame = transform_irradiance(_build_irradiance_raw())

    assert frame.shape == (3, 6)
    assert list(frame.columns) == [
        "date",
        "eflatun_production",
        "hipokrat_production",
        "production",
        "irradiation",
        "pi",
    ]
    assert pd.api.types.is_datetime64_any_dtype(frame["date"])
    assert frame["production"].dtype == "float64"
    assert frame.loc[0, "production"] == pytest.approx(10.5)
    assert frame.loc[2, "pi"] == pytest.approx(30.75 / 5.5)


def test_transform_irradiance_rejects_gaps(monkeypatch) -> None:
    monkeypatch.setattr(config, "IRRADIANCE_START_DATE", "2023-01-01")
    monkeypatch.setattr(config, "IRRADIANCE_END_DATE", "2023-01-03")

    raw = _build_irradiance_raw().iloc[:2]
    with pytest.raises(ValueError, match="Daily index incomplete"):
        transform_irradiance(raw)


def test_transform_downtime_expands_days_and_parses_duration() -> None:
    raw = pd.DataFrame(
        {
            "Baslangic Tarihi": [pd.Timestamp("2023-02-20")],
            "Basl. Saati": [pd.Timestamp("2023-02-20 10:00:00")],
            "Bitis Tarihi": [pd.Timestamp("2023-02-21")],
            "Bitis Saati": [pd.Timestamp("2023-02-21 12:00:00")],
            "Durus S.(sa)": ["7,65"],
            "Durus Nedeni": ["Kisitlama"],
            "Durusa Neden Olan Sistemler": ["Santral"],
            "Curtailment Degeri (Maksimum Uretim)": [pd.NA],
        }
    )

    events, days = transform_downtime(raw)

    assert events.shape == (1, 7)
    assert events.loc[0, "duration_hours"] == pytest.approx(7.65)
    assert days.shape == (2, 8)
    assert days["date"].tolist() == [
        pd.Timestamp("2023-02-20"),
        pd.Timestamp("2023-02-21"),
    ]


def test_transform_inverter_melts_and_drops_commissioning(monkeypatch) -> None:
    monkeypatch.setattr(config, "INVERTER_COMMISSIONING_END_DATE", "2025-01-22")
    monkeypatch.setattr(config, "INVERTER_COUNT", 2)

    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-20", "2025-01-23"]),
            "BAND.CNK GES.2.CNK1_INV.INV1.Total Active Power": [0, 100],
            "BAND.CNK GES.2.CNK1_INV.INV2.Total Active Power": [0, 200],
            "BAND.CNK GES.2.CNK1_Meteo.Main_Meteo.Anlik_Isinim": [0, 3.5],
        }
    )

    frame = transform_inverter(raw)

    assert frame.shape == (2, 4)
    assert set(frame["inverter"]) == {"INV1", "INV2"}
    assert frame.loc[frame["inverter"] == "INV1", "active_power"].iloc[0] == pytest.approx(100)


def test_transform_washing_orders_by_date_and_maps_methods() -> None:
    text = """\
5. yikama 19.11.2024-25.11.2024 Fircali-Solusyonlu
5. yikama 21.07.2024-30.07.2024 Robot-Solusyonsuz
1. yikama 18.09.2023-25.09.2023 Fircali-Solusyonlu
2. yikama 13.11.2023-06.12.2023 Fircali-Solusyonlu
3. yikama 26.03.2024-07.04.2024 Fircali-Solusyonlu
4. yikama 20.05.2024-29.05.2024 Fircali-Solusyonlu
6. yikama 10.03.2025-21.03.2025 Fircali-Solusyonlu
"""
    frame = transform_washing(text)

    assert len(frame) == 7
    assert frame["event_index_by_date"].tolist() == list(range(1, 8))
    assert frame.iloc[0]["start"] == pd.Timestamp("2023-09-18")
    assert frame.iloc[4]["method"] == "robot_no_solution"
    assert frame.iloc[4]["event_index_by_date"] == 5
    assert frame.iloc[5]["start"] == pd.Timestamp("2024-11-19")
