# Data Dictionary

Seeded from initial profiling. Cursor appends per-loader summaries during P1, and
external-source provenance during P2.

## Raw inputs (verified)

| file | sheet | rows | date span | notes |
|---|---|---|---|---|
| Canakkale_Uretim_isinim_verileri.xlsx | Canakkale Hibrit GES | 1026 | 2023-01-01..2025-10-22 | no missing dates; production & irradiation complete; feeders only last ~333 rows; DURUM empty |
| Canakkale_Hibrit_GES_Duruslar.xlsx | Gerceklesen Duruslar | 88 | 2023-02-20..2025-10-22 | reasons: Planli 34, Harici Mucbir 21, Yillik Bakim 12, Plansiz 10, Dahili Mucbir 5, Kisitlama 4, Ariza 2 |
| Canakkale-1_Hibrit_GES_gunluk_inverter_uretimi.xlsx | ÇANAKKALE 1 | 333 | 2024-11-26..2025-10-23 | INV1..INV11 + meteo; all-zero before 2025-01-23 (commissioning) |
| Panel_yikama_tarihleri.txt | - | 7 | 2023-09-18..2025-03-21 | 6 brush+solution, 1 robot no-solution; two events mislabeled "5." |

## Derived
- pi = GUNLUK TOTAL URETIM / ISINIM (daily irradiance-normalized yield)

## P1 interim frames (loaded 2026-06-24)

| artifact | rows | date span | null counts |
|---|---|---|---|
| irradiance_daily | 1026 | 2023-01-01..2025-10-22 | eflatun_production=693, hipokrat_production=693 |
| downtime_events | 88 | 2023-02-20..2025-10-22 | curtailment_mw=84 |
| downtime_days | 92 | 2023-02-20..2025-10-22 | curtailment_mw=88 |
| inverter_daily_long | 3025 | 2025-01-23..2025-10-23 | active_power=857, meteo_irradiance=55 |
| washing_events | 7 | 2023-09-18..2025-03-21 | none |

Each frame is written to `data/interim/<name>.parquet` by `spis.ingest.ingest_all()`.
Inverter loader logs 935 long-form rows with negative meteo_irradiance (night sensor
noise); values are retained, not imputed.

## External sources (vetted; pull in P2)
All cover the project window 2023-01-01..2025-10-22 and the plant point
lat 39.86857, lon 26.24152.

| source | variables | auth | url | units |
|---|---|---|---|---|
| Open-Meteo Air Quality (Copernicus CAMS) | pm10, pm2_5, dust, aerosol_optical_depth | none (free, non-commercial) | https://air-quality-api.open-meteo.com | ug/m3, AOD dimensionless |
| NASA POWER (daily) | T2M, WS2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN | none (free) | https://power.larc.nasa.gov/api/temporal/daily/point | degC, m/s, mm/day, kWh/m2/day |
| Open-Meteo Archive (ERA5) | temperature_2m, wind_speed, precipitation, shortwave_radiation | none (free) | https://archive-api.open-meteo.com | degC, m/s, mm, W/m2 |
| EPIAS Transparency (PTF/MCP) | day-ahead market clearing price | username+password (free registration); pkg eptr2 | https://seffaflik.epias.com.tr | TL/MWh |

Notes:
- CAMS pm10/dust/AOD is THE pollution layer the proposal needs; it is modelled
  (reanalysis), not in-situ. Cross-check magnitude against any nearby ground
  station if Enerjisa/MGM provides one.
- NASA POWER solar is satellite-derived; use it only to sanity-check the SCADA
  irradiation column, not to replace it.
- PTF needs free EPIAS registration -> per the data-access protocol, Cursor stops
  and requests EPTR_USERNAME / EPTR_PASSWORD when it reaches P4.
