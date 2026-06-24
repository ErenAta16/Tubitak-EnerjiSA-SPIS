"""Typed loaders for raw SPIS inputs."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from spis import config
from spis.io import write_interim
from spis.sites import DEFAULT_SITE, get_site, site_raw_paths

LOGGER = logging.getLogger(__name__)

WASHING_METHOD_MAP: dict[str, str] = {
    "fircali-solusyonlu": "brush_solution",
    "robot-solusyonsuz": "robot_no_solution",
}


def _resolve_sheet(path: Path, substring: str) -> str:
    """Return the first worksheet whose name contains ``substring``."""
    names = pd.ExcelFile(path).sheet_names
    for name in names:
        if substring.lower() in name.strip().lower():
            return name
    raise ValueError(f"No sheet matching {substring!r} in {path.name}; found {names}")


def _normalize_text(text: str) -> str:
    """Fold Turkish characters to ASCII for tolerant header matching."""
    folded = text.strip()
    for src, dst in {
        "ı": "i",
        "İ": "i",
        "I": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }.items():
        folded = folded.replace(src, dst)
    return folded.lower()


def _find_column(columns: pd.Index, *needles: str) -> str:
    """Match a column by case-insensitive substring needles."""
    for column in columns:
        normalized = _normalize_text(str(column))
        if all(_normalize_text(needle) in normalized for needle in needles):
            return column
    raise KeyError(f"No column matching {needles} in {list(columns)}")


def coerce_comma_decimal(series: pd.Series) -> pd.Series:
    """Parse numeric strings that may use comma decimal separators."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = series.astype(str).str.strip().str.replace(",", ".", regex=False)
    cleaned = cleaned.replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
    return pd.to_numeric(cleaned, errors="coerce")


def _assert_complete_daily_index(dates: pd.Series, start: str, end: str) -> None:
    """Assert a daily date index has zero gaps between start and end inclusive."""
    normalized = pd.to_datetime(dates).dt.normalize()
    expected = pd.date_range(start=start, end=end, freq="D")
    missing = expected.difference(normalized.unique())
    if len(missing) > 0:
        raise ValueError(
            f"Daily index incomplete: expected {len(expected)} days, "
            f"found {normalized.nunique()}, missing {len(missing)} "
            f"(first gap: {missing[0].date()})"
        )


def transform_irradiance(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize, validate, and enrich an irradiance/production frame."""
    rows_in = len(raw)
    frame = raw.copy()
    frame.columns = [str(column).strip() for column in frame.columns]

    rename_map = {
        _find_column(frame.columns, "tarih"): "date",
        _find_column(frame.columns, "eflatun"): "eflatun_production",
        _find_column(frame.columns, "hipokrat"): "hipokrat_production",
        _find_column(frame.columns, "gunluk", "total"): "production",
        _find_column(frame.columns, "isinim"): "irradiation",
    }
    frame = frame.rename(columns=rename_map)
    keep = list(rename_map.values())
    frame = frame[keep].copy()

    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    for column in ("eflatun_production", "hipokrat_production", "production", "irradiation"):
        frame[column] = coerce_comma_decimal(frame[column])

    _assert_complete_daily_index(
        frame["date"],
        config.IRRADIANCE_START_DATE,
        config.IRRADIANCE_END_DATE,
    )

    if frame["production"].isna().any() or frame["irradiation"].isna().any():
        raise ValueError("production and irradiation must be non-null for all days")
    if (frame["production"] < 0).any() or (frame["irradiation"] < 0).any():
        raise ValueError("production and irradiation must be >= 0")

    frame["pi"] = frame["production"] / frame["irradiation"]
    frame = frame.sort_values("date").reset_index(drop=True)

    expected_dtypes = {
        "eflatun_production": "float64",
        "hipokrat_production": "float64",
        "production": "float64",
        "irradiation": "float64",
        "pi": "float64",
    }
    if not pd.api.types.is_datetime64_any_dtype(frame["date"]):
        raise TypeError(f"date expected datetime dtype, got {frame['date'].dtype}")
    for column, dtype in expected_dtypes.items():
        if str(frame[column].dtype) != dtype:
            raise TypeError(f"{column} expected {dtype}, got {frame[column].dtype}")

    LOGGER.info(
        "load_irradiance: rows_in=%s rows_out=%s rows_dropped=0",
        rows_in,
        len(frame),
    )
    return frame


def load_irradiance(path: Path | None = None) -> pd.DataFrame:
    """Load the daily production and irradiance workbook."""
    source = path or config.RAW_IRRADIANCE_PRODUCTION
    sheet = _resolve_sheet(source, config.SHEET_IRRADIANCE_SUBSTRING)
    raw = pd.read_excel(source, sheet_name=sheet)
    return transform_irradiance(raw)


def _combine_datetime(date_value: object, time_value: object) -> pd.Timestamp:
    """Combine separate date and time cells into one timestamp."""
    date_part = pd.to_datetime(date_value).normalize()
    if pd.isna(time_value):
        return date_part
    time_part = pd.to_datetime(time_value)
    return date_part + (time_part - time_part.normalize())


def transform_downtime(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse downtime events and expand them to one row per calendar day touched."""
    rows_in = len(raw)
    frame = raw.copy()
    frame.columns = [str(column).strip() for column in frame.columns]

    start_date_col = _find_column(frame.columns, "baslang", "tarih")
    end_date_col = _find_column(frame.columns, "bitis", "tarih")
    start_time_col = _find_column(frame.columns, "basl", "saat")
    end_time_col = _find_column(frame.columns, "bitis", "saat")
    duration_col = _find_column(frame.columns, "s.(sa)")
    reason_col = _find_column(frame.columns, "durus", "nedeni")
    systems_col = _find_column(frame.columns, "neden", "olan", "sistem")
    curtailment_col = _find_column(frame.columns, "curtailment")

    events = pd.DataFrame(
        {
            "event_id": range(1, len(frame) + 1),
            "start_datetime": [
                _combine_datetime(row[start_date_col], row[start_time_col])
                for _, row in frame.iterrows()
            ],
            "end_datetime": [
                _combine_datetime(row[end_date_col], row[end_time_col])
                for _, row in frame.iterrows()
            ],
            "duration_hours": coerce_comma_decimal(frame[duration_col]),
            "reason": frame[reason_col].astype(str).str.strip(),
            "affected_systems": frame[systems_col].astype(str).str.strip(),
            "curtailment_mw": coerce_comma_decimal(frame[curtailment_col]),
        }
    )

    if events["duration_hours"].isna().any():
        raise ValueError("duration_hours must be non-null for all downtime events")

    day_rows: list[dict[str, object]] = []
    for _, event in events.iterrows():
        day_range = pd.date_range(
            event["start_datetime"].normalize(),
            event["end_datetime"].normalize(),
            freq="D",
        )
        for day in day_range:
            day_rows.append(
                {
                    "date": day.normalize(),
                    "event_id": int(event["event_id"]),
                    "start_datetime": event["start_datetime"],
                    "end_datetime": event["end_datetime"],
                    "duration_hours": float(event["duration_hours"]),
                    "reason": event["reason"],
                    "affected_systems": event["affected_systems"],
                    "curtailment_mw": event["curtailment_mw"],
                }
            )

    days = pd.DataFrame(day_rows)
    if days.empty:
        raise ValueError("downtime day expansion produced zero rows")

    for column, dtype in {
        "duration_hours": "float64",
        "event_id": "int64",
    }.items():
        days[column] = days[column].astype(dtype)
    for column in ("date", "start_datetime", "end_datetime"):
        days[column] = pd.to_datetime(days[column])

    LOGGER.info(
        "load_downtime: events_in=%s events_out=%s day_rows_out=%s rows_dropped=0",
        rows_in,
        len(events),
        len(days),
    )
    return events, days


def load_downtime(path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load downtime events and return event-level and day-expanded tables."""
    source = path or config.RAW_DOWNTIME_EVENTS
    sheet = _resolve_sheet(source, config.SHEET_DOWNTIME_SUBSTRING)
    raw = pd.read_excel(source, sheet_name=sheet)
    return transform_downtime(raw)


def transform_inverter(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse inverter daily production into long form and drop commissioning zeros."""
    rows_in = len(raw)
    frame = raw.copy()
    date_col = frame.columns[0]
    frame = frame.rename(columns={date_col: "date"})
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()

    inverter_columns = [
        column
        for column in frame.columns
        if column != "date" and "INV" in str(column) and "Active Power" in str(column)
    ]
    meteo_column = _find_column(frame.columns, "meteo")
    inverter_columns = sorted(
        inverter_columns,
        key=lambda column: int(re.search(r"INV(\d+)", str(column)).group(1)),
    )

    if len(inverter_columns) != config.INVERTER_COUNT:
        raise ValueError(
            f"Expected {config.INVERTER_COUNT} inverter columns, found {len(inverter_columns)}"
        )

    commissioning_mask = frame["date"] <= pd.Timestamp(config.INVERTER_COMMISSIONING_END_DATE)
    commissioning_rows = frame.loc[commissioning_mask]
    zero_mask = commissioning_rows[inverter_columns].fillna(0).sum(axis=1) == 0
    rows_to_drop = int(zero_mask.sum())
    if rows_to_drop > 0:
        LOGGER.info(
            "load_inverter: dropping %s all-zero commissioning rows on or before %s",
            rows_to_drop,
            config.INVERTER_COMMISSIONING_END_DATE,
        )
    frame = frame.loc[~commissioning_mask | ~zero_mask].copy()

    inv_pattern = re.compile(r"INV(\d+)")
    inverter_map = {
        column: f"INV{inv_pattern.search(str(column)).group(1)}" for column in inverter_columns
    }
    long_frame = frame.melt(
        id_vars=["date", meteo_column],
        value_vars=inverter_columns,
        var_name="inverter_source",
        value_name="active_power",
    )
    long_frame["inverter"] = long_frame["inverter_source"].map(inverter_map)
    long_frame = long_frame.rename(columns={meteo_column: "meteo_irradiance"})
    long_frame["active_power"] = coerce_comma_decimal(long_frame["active_power"])
    long_frame["meteo_irradiance"] = coerce_comma_decimal(long_frame["meteo_irradiance"])
    long_frame = long_frame.drop(columns=["inverter_source"])
    long_frame = long_frame[["date", "inverter", "active_power", "meteo_irradiance"]].sort_values(
        ["date", "inverter"]
    )
    long_frame = long_frame.reset_index(drop=True)

    if (long_frame["active_power"] < 0).any():
        raise ValueError("active_power must be >= 0")
    negative_meteo = int((long_frame["meteo_irradiance"] < 0).sum())
    if negative_meteo:
        LOGGER.info(
            "load_inverter: %s rows have negative meteo_irradiance (night sensor noise)",
            negative_meteo,
        )

    wide_rows_out = len(frame)
    LOGGER.info(
        "load_inverter: rows_in=%s rows_out=%s rows_dropped=%s",
        rows_in,
        len(long_frame),
        rows_in - wide_rows_out,
    )
    return long_frame


def load_inverter(path: Path | None = None) -> pd.DataFrame:
    """Load inverter daily production in long form."""
    source = path or config.RAW_INVERTER_DAILY
    sheet = _resolve_sheet(source, config.SHEET_INVERTER_SUBSTRING)
    raw = pd.read_excel(source, sheet_name=sheet)
    return transform_inverter(raw)


def _normalize_method_token(raw_method: str) -> str:
    """Map a washing method label to a canonical enum string."""
    normalized = (
        raw_method.strip()
        .lower()
        .replace("ı", "i")
        .replace("ş", "s")
        .replace("ü", "u")
        .replace("ç", "c")
        .replace("ğ", "g")
        .replace("ö", "o")
    )
    normalized = re.sub(r"\s+", "-", normalized)
    if normalized not in WASHING_METHOD_MAP:
        raise ValueError(f"Unknown washing method: {raw_method!r}")
    return WASHING_METHOD_MAP[normalized]


def transform_washing(text: str) -> pd.DataFrame:
    """Parse washing event lines into an ordered, validated table."""
    pattern = re.compile(
        r"^\s*\d+\.\s*y[\w\u0131\u015f]*ama\s+"
        r"(\d{2}\.\d{2}\.\d{4})-(\d{2}\.\d{2}\.\d{4})\s+(.+?)\s*$",
        flags=re.IGNORECASE,
    )
    parsed_rows: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        match = pattern.match(stripped)
        if not match:
            raise ValueError(f"Unparseable washing line {line_number}: {stripped!r}")
        start_raw, end_raw, method_raw = match.groups()
        parsed_rows.append(
            {
                "start": pd.to_datetime(start_raw, format="%d.%m.%Y").normalize(),
                "end": pd.to_datetime(end_raw, format="%d.%m.%Y").normalize(),
                "method": _normalize_method_token(method_raw),
            }
        )

    if len(parsed_rows) != 7:
        raise ValueError(f"Expected 7 washing events, found {len(parsed_rows)}")

    frame = pd.DataFrame(parsed_rows).sort_values(["start", "end"]).reset_index(drop=True)
    frame["event_index_by_date"] = range(1, len(frame) + 1)
    frame["segment_id"] = frame["event_index_by_date"]

    for column in ("start", "end"):
        if not pd.api.types.is_datetime64_any_dtype(frame[column]):
            raise TypeError(f"{column} expected datetime dtype, got {frame[column].dtype}")
    if frame["event_index_by_date"].dtype != "int64" or frame["segment_id"].dtype != "int64":
        raise TypeError("event_index_by_date and segment_id must be int64")
    if not pd.api.types.is_string_dtype(frame["method"]):
        raise TypeError(f"method expected string dtype, got {frame['method'].dtype}")

    LOGGER.info(
        "load_washing: lines_in=%s rows_out=%s rows_dropped=0",
        len(parsed_rows),
        len(frame),
    )
    return frame


def load_washing(path: Path | None = None) -> pd.DataFrame:
    """Load panel washing events from the text log."""
    source = path or config.RAW_WASHING_DATES
    text = source.read_text(encoding="utf-8")
    return transform_washing(text)


def ingest_all(site_key: str = DEFAULT_SITE) -> dict[str, pd.DataFrame]:
    """Run all loaders and persist validated interim Parquet artifacts for a site."""
    site = get_site(site_key)
    if not site.operational_data_available:
        raise ValueError(
            f"Site {site_key!r} has operational_data_available=False; cannot ingest SCADA files"
        )

    paths = site_raw_paths(site_key)
    irradiance = load_irradiance(paths["irradiance"])
    events, downtime_days = load_downtime(paths["downtime"])
    inverter = load_inverter(paths["inverter"])
    washing = load_washing(paths["washing"])

    artifacts = {
        "irradiance_daily": irradiance,
        "downtime_events": events,
        "downtime_days": downtime_days,
        "inverter_daily_long": inverter,
        "washing_events": washing,
    }
    for name, frame in artifacts.items():
        write_interim(name, frame, site_key=site_key)
    return artifacts
