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
| NASA POWER daily point | T2M, T2M_MAX, WS2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN, CLRSKY_SFC_SW_DWN | none | https://power.larc.nasa.gov/api/temporal/daily/point | degC, degC, m/s, mm/day, kWh/m2/day, kWh/m2/day | 2023-01-01..2025-10-22 (1026 days) |
| Open-Meteo Air Quality (CAMS) | pm10, pm2_5, dust, aerosol_optical_depth | none | https://air-quality-api.open-meteo.com/v1/air-quality | ug/m3, ug/m3, ug/m3, dimensionless | 2023-01-01..2025-10-22 (1026 days; hourly mean aggregated to daily) |
| EPIAS PTF CSV (user export) | hourly PTF TL/MWh | file | data/external/epias_ptf/Piyasa_Takas_Fiyati-*.csv | TL/MWh | 2023 only (8760 hours); 2024-2025 not supplied |

Cached under `data/external/nasa_power/`, `data/external/open_meteo_aq/`, and
`data/external/epias_ptf/` with JSON sidecars.

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

## P3 soiling segments (`data/processed/soiling_segments.parquet`)

Seven post-wash segments (segment 0 excluded). Primary fit signal:
`pi_temp_corrected` on rain-free `is_clean_observation` days. Baseline = median of
first 3 clean days after wash (`SOILING_BASELINE_CLEAN_DAYS`). Robust slope =
`scipy.stats.theilslopes` of soiling_ratio (%) vs `days_since_wash`.

| seg | season | method | n_clean | n_fit | rate %/day | CI | R2 | recovery % | flags |
|---|---|---|---:|---:|---:|---|---:|---:|---|
| 1 | autumn | brush | 47 | 40 | -0.297 | [-0.34,-0.25] | 0.79 | -1.2 | recovery<0 |
| 2 | winter | brush | 69 | 62 | +0.130 | [0.09,0.18] | 0.19 | -12.6 | positive slope |
| 3 | spring | brush | 41 | 29 | -0.001 | [-0.08,0.07] | -0.02 | +10.8 | |
| 4 | summer | brush | 55 | 47 | -0.022 | [-0.08,0.04] | -0.05 | +12.3 | |
| 5 | autumn | robot | 101 | 93 | -0.223 | [-0.25,-0.20] | 0.47 | +9.6 | n=1 robot (descriptive) |
| 6 | winter | brush | 73 | 70 | -0.081 | [-0.11,-0.05] | 0.38 | -2.4 | recovery<0 |
| 7 | summer | brush | 171 | 162 | -0.088 | [-0.11,-0.07] | 0.23 | +46.5 | open segment |

### Seasonal summary (segment means)

| season | mean rate %/day | n segments |
|---|---:|---:|
| autumn | -0.260 | 2 |
| winter | +0.025 | 2 |
| spring | -0.001 | 1 |
| summer | -0.055 | 2 |

### P4 recommended rate

| metric | value %/day |
|---|---:|
| Pooled (variance-weighted) | -0.090 |
| Pooled approx 95% CI | [-0.177, -0.004] |
| Summer mean (recommended for P4) | -0.055 |
| Winter mean | +0.025 |

Rationale: summer rate used for scheduling because peak soiling loss accumulates in
dry months; pooled rate is cross-season fallback. See `reports/SOILING_INTERPRETATION.md`.

### Pollution association (n=7 segments, not causal)

| pollutant | r | p | bootstrap 95% CI |
|---|---:|---:|---|
| accumulated pm10 | -0.16 | 0.73 | [-0.97, 0.33] |
| accumulated dust | -0.04 | 0.93 | [-0.89, 0.88] |
| accumulated AOD | -0.05 | 0.91 | [-0.90, 0.78] |

## P3.5 soiling robustness (`data/processed/soiling_robustness.parquet`)

Reads `master_daily.parquet` and `soiling_segments.parquet` only (no P1-P3 re-run).
At analysis time joins NASA `CLRSKY_SFC_SW_DWN` from cache and computes
`clearness_index = nasa_allsky_kwh_m2 / nasa_clrsky_kwh_m2`. High-clearness filter
k >= 0.7 (tercile cutoff ~0.977 logged). Re-fits per-segment Theil-Sen slopes on
rain-free clean days within that subset.

### Clear-sky vs original slopes

| seg | original %/day | clear %/day | orig R2 | clear R2 | clear n | CI tightened |
|---:|---:|---:|---:|---:|---:|---|
| 1 | -0.281 | -0.293 | 0.79 | 0.79 | 39 | yes |
| 2 | +0.130 | +0.114 | 0.20 | 0.14 | 44 | yes |
| 3 | -0.039 | +0.007 | -0.06 | -0.08 | 21 | yes |
| 4 | -0.032 | -0.022 | -0.04 | -0.05 | 47 | yes |
| 5 | -0.218 | -0.224 | 0.47 | 0.46 | 92 | yes |
| 6 | -0.084 | -0.147 | 0.33 | -0.68 | 20 | no |
| 7 | -0.083 | -0.179 | 0.21 | 0.17 | 35 | no |

### Daily pollution test (HAC, Newey-West maxlags=7)

Regression n = 557 after dropna (750 clean input days). Verdict: **not supported at
daily resolution (n~750)**.

### P4 rate update (post P3.5)

Clear-sky pooled rate **-0.125 %/day** (uncertainty half-width 0.061). See
`reports/SOILING_ROBUSTNESS.md`.

### Irradiance-sensor caveat

SCADA `irradiation` (ISINIM) is likely in-plane reference irradiation. Co-soiling of
the reference sensor partially cancels module soiling in PI; observed rates are a
lower bound on physical soiling. No sensor datasheet in repo; not corrected.

## P4 washing optimization (`data/processed/washing_optimization.parquet`)

Reads `master_daily`, `soiling_segments`, `soiling_robustness`, and `washing_events`.
Economic inputs are **ASSUMED sweeps** until Enerjisa wash costs and EPIAS PTF are
supplied; every assumed value is logged (`record_type=assumption`).

### Production units

SCADA `production` (GUNLUK TOTAL URETIM) is **kWh/day**. Peak-day
production/irradiation implied ~2748 kW, matching 11 x SG250HX (2750 kW AC).

### Clean-baseline energy

Pooled post-wash clean-baseline: **11,131 kWh/day** (median of segment baselines from
first 3 clean days after each wash).

### Soiling-loss model

Linear L(t)=r*t with P3.5 clear-sky pooled r=**0.00125/day** (CI 0.00064..0.00185).
Observed r is a lower bound (irradiance-sensor co-soiling); true T* may be shorter.

### Central optimum (real 2023 PTF annual mean 2189.30 TL/MWh; wash cost ASSUMED 150k TL)

| metric | value |
|---|---:|
| T* (point rate, real_2023 price) | 99 days |
| T* rate CI | 81..139 days |
| T* at previous assumed 2000 TL/MWh | 104 days |
| Mean actual inter-wash gap | 79 days |
| Verdict at central assumptions | over-washing (cautious: 2023 nominal price) |

Closed-form T*=sqrt(2*C/(r*E*p)) verified against 1-day grid search (max delta 0.5 d).

Figures: `optimize_cost_vs_interval`, `optimize_t_star_heatmap`,
`optimize_actual_vs_optimal` under `reports/figures/`. Report:
`reports/WASHING_SCHEDULE.md`.

## P5 machine learning (`data/processed/ml_model_metrics.parquet`)

Random Forest corroboration layer on exogenous features only (production and
irradiation excluded to prevent PI leakage). Target: `pi_temp_corrected` on clean
post-first-wash days. Modelling frame: 376 rows (181 dropped for null clearness/features).

Time split at 2024-11-01: train=301, test=75 (latest 20% held out).

| model | MAE | RMSE | R2 |
|---|---:|---:|---:|
| Random Forest | 0.285 | 0.375 | -0.784 |
| days_since_wash baseline | 0.339 | 0.416 | -1.195 |

Top permutation importances (test): nasa_t2m, month_cos, dust_accumulated,
days_since_wash. Pollution verdict: dust_accumulated ranks #3 with positive importance
(possible nonlinear signal; not proven causation). Negative held-out R2 reflects a
difficult test window; RF still modestly beats the linear trend baseline.

Persisted artifacts: `ml_model.joblib`, `ml_feature_list.json`. Report:
`reports/ML_RESULTS.md`.

## External sources (vetted; reference list)

Notes:
- CAMS pm10/dust/AOD is THE pollution layer the proposal needs; it is modelled
  (reanalysis), not in-situ. Cross-check magnitude against any nearby ground
  station if Enerjisa/MGM provides one.
- NASA POWER solar is satellite-derived; use it only to sanity-check the SCADA
  irradiation column, not to replace it.
- PTF needs free EPIAS registration -> per the data-access protocol, Cursor stops
  and requests EPTR_USERNAME / EPTR_PASSWORD when it reaches P4.
