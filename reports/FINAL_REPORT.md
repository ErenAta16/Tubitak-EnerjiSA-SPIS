# SPIS Final Report (Canakkale Hybrid GES)

## Data and methods

Daily performance index PI = production / irradiation (kWh/day over Wh/m²/day).
Temperature-corrected PI used for soiling fits. Clean observations exclude downtime,
curtailment, fault, low-irradiation, and rain days (750 of 1026 days). Seven post-wash
segments from Enerjisa washing logs. External data: NASA POWER, CAMS air quality,
EPIAS PTF CSV (2023 hourly, annual mean 2189.30 TL/MWh).

## Soiling rate (P3 / P3.5)

Clear-sky pooled Theil-Sen rate: **-0.1247 %/day**
(uncertainty half-width 0.0608 %/day).

Per-segment rates:

| seg | rate %/day | season |
|---:|---:|---|
| 1 | -0.297 | autumn |
| 2 | 0.130 | winter |
| 3 | -0.001 | spring |
| 4 | -0.022 | summer |
| 5 | -0.223 | autumn |
| 6 | -0.081 | winter |
| 7 | -0.088 | summer |

Observed rates are a **lower bound** when the reference irradiance sensor co-soils.

## Washing recovery

Median post-wash recovery: **9.64 %** across segments.

## Pollution test (honest verdict)

Daily HAC regression on trend-removed PI residuals (P3.5 spec: accumulated since
last wash). CAMS accumulated n~557; ground PM10 accumulated paired days
422:
**not supported at daily resolution (confirmed with in-situ PM10)**.
CAMS PM10 accumulated HAC p = 0.727; ground PM10
accumulated HAC p = 0.928 (Canakkale Merkez
UHKIA, urban proxy ~40-60 km from plant). Daily raw ground PM10 is reported in
SOILING_ROBUSTNESS.md as a sensitivity check only. Segment-level correlations (n=7)
and RF permutation ranks are **weak, non-confirmatory** signals only.

The reframed soiling_ratio RF test R2 is **-0.5585** (legacy
absolute-PI R2 = -0.7842). Permutation
importances are **not evidence** for a pollution driver; any mid-ranked dust feature
may reflect season/collinearity, not causation.

## Rain natural cleaning

Mean PI recovery per rain event: **-0.0067** (near zero).
Rain accounts for **74.0 %** of summed positive
cleaning uplift vs scheduled washing (P3.5).

## Economic optimum (P4)

Real central PTF: **2189.30 TL/MWh** (2023 annual mean only;
2024-2025 not supplied). Wash cost **150,000 TL remains ASSUMED**.

Optimal interval T* = **99 days**
(CI 81-139 days). Previous assumed 2000 TL/MWh central
price gave T* = 104 days.

Actual mean inter-wash gap: **79 days**. At the
2023 nominal price the plant appears to wash more often than the model optimum
(over-washing), but if Enerjisa supplies a current-TL wash cost without rebasing the
2023 PTF, the nominal price biases T* **longer** — keep the cadence verdict cautious.

## Machine learning corroboration (P5 / P12)

P12 reframes the target to within-segment **soiling_ratio** (fair task; PI no longer
resets between washes). Blocked CV R2 (RF) =
**-1.3525 +/- 2.1188**; held-out test R2 =
**-0.5585** vs legacy absolute-PI RF R2 =
**-0.7842**. Simple trend baseline R2 =
**-0.8942**. Random Forest modestly beats the trend baseline on the held-out window, but blocked CV R2 remains negative — treat ML ga

## Limitations

- Single site (Canakkale); no Balikesir comparison data.
- Irradiance-sensor co-soiling cancels part of true module loss in PI.
- PTF central price is 2023-only nominal TL; wash cost assumed.
- Pollution null result and weak ML generalization remain valid findings, not failures.

## Figure captions

- **soiling_timeline_slopes**: PI timeline with wash lines and segment slopes
- **soiling_rate_by_segment**: Per-segment soiling rate with CIs by season
- **soiling_recovery_by_wash**: Washing recovery per event
- **robustness_residual_vs_pm10**: Daily PI residual vs accumulated CAMS PM10
- **robustness_residual_vs_ground_pm10**: Daily PI residual vs accumulated ground PM10
- **robustness_residual_vs_dust**: Daily PI residual vs accumulated dust
- **robustness_rain_recovery**: Rain-event PI recovery distribution
- **optimize_cost_vs_interval**: Total cost vs wash interval at real 2023 PTF central case
- **optimize_t_star_heatmap**: T* heatmap over wash cost and ASSUMED PTF sweep
- **optimize_actual_vs_optimal**: Actual vs model-optimal inter-wash cadence
- **ml_permutation_importance**: RF permutation importance (model test R2 negative)
