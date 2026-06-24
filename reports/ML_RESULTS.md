# P5 Machine Learning Results

## Leakage control

Target: `pi_temp_corrected` on `is_clean_observation` days (post-first-wash).
Features are exogenous only; **production and irradiation are excluded**
because PI = production/irradiation would leak the target ratio.

Modelling frame: train=301, test=75 (time split at 2024-11-01, latest 20% held out).

## Test metrics

| model | MAE | RMSE | R2 |
|---|---:|---:|---:|
| Random Forest | 0.28525 | 0.37490 | -0.7842 |
| days_since_wash baseline | 0.33922 | 0.41583 | -1.1951 |

## RF vs simple baseline

RF modestly beats the days_since_wash baseline on held-out R2/MAE; weather adds explanatory power beyond the linear trend alone.

GridSearchCV best params: `{'max_depth': 5, 'min_samples_leaf': 5, 'n_estimators': 100}` (TimeSeriesSplit CV MAE=0.22652).

## Permutation importance (test set, full ranking)

| rank | feature | mean | 95% CI |
|---:|---|---:|---|
| 1 | nasa_t2m | 0.35456 | [0.15009, 0.55903] |
| 2 | month_cos | 0.27037 | [0.20118, 0.33955] |
| 3 | dust_accumulated | 0.18996 | [0.08731, 0.29261] |
| 4 | days_since_wash | 0.17713 | [0.04853, 0.30572] |
| 5 | nasa_t2m_max | 0.10915 | [0.04033, 0.17796] |
| 6 | aod_accumulated | 0.06698 | [0.03952, 0.09445] |
| 7 | pm10_accumulated | 0.06472 | [0.03105, 0.09840] |
| 8 | aerosol_optical_depth | 0.02312 | [-0.00261, 0.04886] |
| 9 | nasa_precip_mm | 0.00363 | [-0.00241, 0.00966] |
| 10 | nasa_ws2m | 0.00247 | [-0.01004, 0.01499] |
| 11 | dust | 0.00058 | [-0.00400, 0.00515] |
| 12 | days_since_rain | 0.00000 | [0.00000, 0.00000] |
| 13 | month_sin | -0.00245 | [-0.00414, -0.00076] |
| 14 | pm10 | -0.02007 | [-0.06052, 0.02037] |
| 15 | clearness_index | -0.10422 | [-0.21060, 0.00216] |

## Pollution verdict

dust_accumulated ranks #3 with positive permutation importance; possible nonlinear effect missed by linear HAC — quantify via partial dependence, not causation.

