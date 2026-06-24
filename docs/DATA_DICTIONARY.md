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

## External sources (P2 pulls, 2026-06-24)

| source | variables | auth | url | units | coverage |
|---|---|---|---|---|---|
| NASA POWER daily point | T2M, T2M_MAX, WS2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN | none | https://power.larc.nasa.gov/api/temporal/daily/point | degC, degC, m/s, mm/day, kWh/m2/day | 2023-01-01..2025-10-22 (1026 days) |
| Open-Meteo Air Quality (CAMS) | pm10, pm2_5, dust, aerosol_optical_depth | none | https://air-quality-api.open-meteo.com/v1/air-quality | ug/m3, ug/m3, ug/m3, dimensionless | 2023-01-01..2025-10-22 (1026 days; hourly mean aggregated to daily) |

Cached under `data/external/nasa_power/` and `data/external/open_meteo_aq/` with JSON sidecars recording request params and pull timestamp.

### SCADA vs NASA irradiance units

SCADA `irradiation` median 5461.6 vs NASA `ALLSKY_SFC_SW_DWN` median 4.77 kWh/m²/day.
Median ratio `(SCADA / 1000) / NASA` = 1.057, so SCADA irradiation is consistent with
**Wh/m²/day** (divide by 1000 to compare with NASA kWh/m²/day). SCADA remains the
primary irradiance for PI; NASA solar is a units cross-check only.

### Low-irradiation cutoff (P2)

Rule: 5th percentile of SCADA daily `irradiation` (`LOW_IRRADIATION_PERCENTILE = 0.05`).
Computed cutoff: **1125.26 Wh/m²/day**. Rain-day threshold: `PRECTOTCORR >= 1.0 mm/day`.

## P2 master table (`data/processed/master_daily.parquet`)

1026 rows (complete daily spine 2023-01-01..2025-10-22). 750 `is_clean_observation`
days after exclusion filters (276 days fail at least one filter; filters overlap).

| column | dtype | description |
|---|---|---|
| date | datetime | Calendar date (spine) |
| eflatun_production | float | Feeder-1 net production (nullable early period) |
| hipokrat_production | float | Feeder-2 net production (nullable early period) |
| production | float | Daily total production (SCADA) |
| irradiation | float | Daily integrated irradiation (SCADA, Wh/m²/day) |
| pi | float | production / irradiation |
| is_downtime | bool | Any downtime event touches this day |
| is_curtailment | bool | Kisitlama reason present |
| is_fault | bool | Ariza reason present |
| is_planned | bool | Planli or Yillik Bakim reason present |
| downtime_hours | float | Sum of event hours on this day |
| downtime_reasons | str | Semicolon-separated reason set |
| nasa_t2m | float | NASA POWER ambient temperature (degC) |
| nasa_t2m_max | float | NASA POWER daily max temperature (degC) |
| nasa_ws2m | float | NASA POWER wind speed at 2 m (m/s) |
| nasa_precip_mm | float | NASA POWER corrected precipitation (mm/day) |
| nasa_allsky_kwh_m2 | float | NASA POWER all-sky surface shortwave (kWh/m²/day) |
| pm10 | float | CAMS PM10 daily mean (ug/m³) |
| pm2_5 | float | CAMS PM2.5 daily mean (ug/m³) |
| dust | float | CAMS dust daily mean (ug/m³) |
| aerosol_optical_depth | float | CAMS AOD daily mean (dimensionless) |
| pre_first_wash | bool | Before first washing event |
| is_open_segment | bool | After last washing event (open segment) |
| segment_id | Int64 | Inter-wash segment (0 pre-first-wash) |
| washing_method | str | Method of wash starting current segment |
| days_since_wash | Int64 | Days since last wash end (NA pre-first-wash) |
| cell_temp_c | float | NOCT-estimated cell temperature (degC) |
| pi_temp_corrected | float | PI corrected to 25 degC reference |
| rain_day | bool | PRECTOTCORR >= 1 mm/day |
| low_irradiation | bool | irradiation below 5th-percentile cutoff |
| is_clean_observation | bool | Passes all P3 soiling-fit exclusion flags |

Filter day counts (not mutually exclusive): downtime 70, curtailment 4, fault 2,
low irradiation 52, rain 205; 750 days pass all filters.

Figure: `reports/figures/pi_temp_correction_comparison.png` (+ CSV) compares 14-day
rolling means of raw vs temperature-corrected PI.

## External sources (vetted; reference list)

Notes:
- CAMS pm10/dust/AOD is THE pollution layer the proposal needs; it is modelled
  (reanalysis), not in-situ. Cross-check magnitude against any nearby ground
  station if Enerjisa/MGM provides one.
- NASA POWER solar is satellite-derived; use it only to sanity-check the SCADA
  irradiation column, not to replace it.
- PTF needs free EPIAS registration -> per the data-access protocol, Cursor stops
  and requests EPTR_USERNAME / EPTR_PASSWORD when it reaches P4.
