# P5/P12 Machine Learning Results

## Target reframing (P12)

**Old (P5):** predict absolute `pi_temp_corrected`. PI resets at each wash, so
segment baseline shifts make this an unfair target (negative held-out R2).

**New (P12):** predict `soiling_ratio = 100 * pi_temp_corrected / segment_baseline`,
where `segment_baseline` is the P3 median of the first post-wash clean days
(`SOILING_BASELINE_CLEAN_DAYS=3`). That
baseline is operationally known right after a wash; it uses only each segment's
own early post-wash days — not future PI — so this is realistic, not leakage.

## Leakage control

Features are exogenous only; **production and irradiation are excluded**
because PI = production/irradiation would leak the target ratio.

Modelling frame: train=301, test=75 (time split at 2024-11-01, latest 20% held out). Pre-first-wash days excluded.

## Blocked TimeSeriesSplit CV (train span only, mean +/- std)

| framing | model | MAE | RMSE | R2 |
|---|---|---:|---:|---:|
| absolute PI | mean_baseline | 0.29656 +/- 0.18004 | 0.33980 +/- 0.17663 | -2.0462 +/- 2.0802 |
| absolute PI | days_since_wash_linear | 0.24255 +/- 0.14365 | 0.30481 +/- 0.16679 | -1.4340 +/- 1.7016 |
| absolute PI | random_forest | 0.22652 +/- 0.15134 | 0.27119 +/- 0.15844 | -0.6702 +/- 0.9709 |
| absolute PI | hist_gradient_boosting | 0.23030 +/- 0.14515 | 0.27709 +/- 0.16092 | -0.6925 +/- 0.9229 |
| soiling_ratio | mean_baseline | 8.38345 +/- 4.33090 | 10.36491 +/- 5.03451 | -1.1085 +/- 0.9255 |
| soiling_ratio | days_since_wash_linear | 10.46052 +/- 8.13303 | 12.72752 +/- 9.88826 | -1.6746 +/- 1.7206 |
| soiling_ratio | random_forest | 8.81022 +/- 7.55284 | 11.35934 +/- 8.29520 | -1.3525 +/- 2.1188 |
| soiling_ratio | hist_gradient_boosting | 9.62942 +/- 7.17378 | 12.18222 +/- 7.91938 | -1.6530 +/- 1.9254 |

## Held-out test metrics (same chronological test window)

| framing | model | MAE | RMSE | R2 |
|---|---|---:|---:|---:|
| absolute PI | mean_baseline | 0.42401 | 0.49415 | -2.0998 |
| absolute PI | days_since_wash_linear | 0.33922 | 0.41583 | -1.1951 |
| absolute PI | random_forest | 0.28525 | 0.37490 | -0.7842 |
| absolute PI | hist_gradient_boosting | 0.31068 | 0.39346 | -0.9653 |
| soiling_ratio | mean_baseline | 13.06775 | 15.89502 | -1.2241 |
| soiling_ratio | days_since_wash_linear | 11.95686 | 14.66884 | -0.8942 |
| soiling_ratio | random_forest | 10.78156 | 13.30544 | -0.5585 |
| soiling_ratio | hist_gradient_boosting | 11.72090 | 14.72970 | -0.9100 |

## Why scores changed

Absolute-PI RF test R2 = -0.7842; soiling_ratio RF test R2 = -0.5585. Reframing removes segment-level level shifts so the ML task aligns with within-segment soiling physics.

## ML vs simple trend (soiling_ratio framing)

Random Forest modestly beats the trend baseline on the held-out window, but blocked CV R2 remains negative — treat ML gains as fragile.

## Permutation importance

Skipped: blocked CV R2 mean = -1.3525 (negative or NaN). Permutation importances are only trustworthy when the model generalizes.

