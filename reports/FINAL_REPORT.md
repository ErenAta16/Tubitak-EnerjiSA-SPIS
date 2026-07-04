# SPIS Final Report (Canakkale Hybrid GES)

## Data and methods

Daily performance index PI = production / irradiation (kWh/day over Wh/m²/day).
Temperature-corrected PI used for soiling fits. Clean observations exclude downtime,
curtailment, fault, low-irradiation, and rain days (750 of 1026 days). Seven post-wash
segments from Enerjisa washing logs. External data: NASA POWER, CAMS air quality,
EPIAS PTF CSV (2023 hourly, annual mean 2189.30 TL/MWh).

## Soiling rate and robustness

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

Daily HAC regression on trend-removed PI residuals (accumulated since
last wash). CAMS accumulated n~557; ground PM10 accumulated paired days
422:
**not supported at daily resolution (confirmed with in-situ PM10)**.
CAMS PM10 accumulated HAC p = 0.727; ground PM10
accumulated HAC p = 0.928 (Canakkale Merkez
UHKIA, urban proxy ~40-60 km from plant). Daily raw ground PM10 is reported in
SOILING_ROBUSTNESS.md as a sensitivity check only. Segment-level correlations (n=7)
are **weak, non-confirmatory** signals only.

The 15-algorithm panel (all blocked CV R2 negative)
does not generalize beyond the days_since_wash trend; permutation importance was not
reported. Held-out RF soiling_ratio test R2 is **-0.5585** (legacy
absolute-PI R2 = -0.7842).

## Rain natural cleaning

Mean PI recovery per rain event: **-0.0067** (near zero).
Rain accounts for **74.0 %** of summed positive
cleaning uplift vs scheduled washing.

## Economic optimum

Real central PTF: **2189.30 TL/MWh** (2023 annual mean only;
2024-2025 not supplied). Wash cost **150,000 TL remains ASSUMED**.

Optimal interval T* = **99 days**
(CI 81-139 days). Previous assumed 2000 TL/MWh central
price gave T* = 104 days.

Actual mean inter-wash gap: **79 days**. At the
2023 nominal price the plant appears to wash more often than the model optimum
(over-washing), but if Enerjisa supplies a current-TL wash cost without rebasing the
2023 PTF, the nominal price biases T* **longer** — keep the cadence verdict cautious.

## Machine learning corroboration

The model panel compares **15** scikit-learn algorithms on
within-segment **soiling_ratio**. Best blocked CV R2 =
**-0.4396 +/- 0.5911** (best: svr_rbf). Any model
with CV R2 >= 0: **False**. Held-out RF
soiling_ratio test R2 = **-0.5585** (legacy absolute-PI
RF R2 = **-0.7842**). No algorithm in the 15-model panel achieves non-negative blocked CV R2 **and** beats the days_since_wash trend on held-out test. No model reaches CV R2 >= 0; Best CV R2: **svr_rbf** (-0.4396 +/- 0.5911). The negative ML finding now holds across linear, kernel, tree, boosting, and neural families — the simple physical trend suffices.

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
- **ml_panel_cv_r2_comparison**: algorithm-panel CV vs test R2 (soiling_ratio)
- **ml_predicted_vs_actual**: RF predicted vs actual soiling_ratio on held-out test
- **robustness_rain_recovery**: Rain-event PI recovery distribution
- **optimize_cost_vs_interval**: Total cost vs wash interval at real 2023 PTF central case
- **optimize_t_star_heatmap**: T* heatmap over wash cost and ASSUMED PTF sweep
- **optimize_actual_vs_optimal**: Actual vs model-optimal inter-wash cadence
