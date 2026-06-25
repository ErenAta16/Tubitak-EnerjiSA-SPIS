# P5/P12/P13 Machine Learning Results

## Target (P12 fair framing, unchanged in P13)

Predict `soiling_ratio = 100 * pi_temp_corrected / segment_baseline`, where
`segment_baseline` is the P3 median of the first 3 post-wash clean days. Baseline is operationally known after a wash (not leakage).

## Leakage control

Exogenous features only; **production, irradiation, and soiling_ratio are excluded**.
Non-tree models use `Pipeline(StandardScaler, model)` with scaling fit inside each CV fold. Fixed hyperparameters; no test-set tuning.

Modelling frame: train=301, test=75 (split 2024-11-01, latest 20% held out).

## P13 algorithm panel (soiling_ratio, sorted by blocked CV R2)

| rank | model | test MAE | test RMSE | test R2 | CV R2 (mean +/- std) | CV>=0 |
|---:|---|---:|---:|---:|---:|---|
| 1 | svr_rbf | 12.53294 | 14.78154 | -0.9234 | -0.4396 +/- 0.5911 | no |
| 2 | knn | 8.99290 | 11.94112 | -0.2552 | -0.5053 +/- 0.4682 | no |
| 3 | extra_trees | 9.16486 | 11.42199 | -0.1485 | -0.7979 +/- 0.7271 | no |
| 4 | mean_baseline | 13.06775 | 15.89502 | -1.2241 | -1.1085 +/- 0.9255 | no |
| 5 | ada_boost | 10.12094 | 12.10686 | -0.2903 | -1.2949 +/- 2.0340 | no |
| 6 | random_forest | 10.78156 | 13.30544 | -0.5585 | -1.3525 +/- 2.1188 | no |
| 7 | gradient_boosting | 9.68484 | 12.04983 | -0.2782 | -1.5656 +/- 1.6841 | no |
| 8 | hist_gradient_boosting | 11.72090 | 14.72970 | -0.9100 | -1.6530 +/- 1.9254 | no |
| 9 | days_since_wash_linear | 11.95686 | 14.66884 | -0.8942 | -1.6746 +/- 1.7206 | no |
| 10 | ridge | 10.51516 | 13.08386 | -0.5070 | -1.9361 +/- 1.3257 | no |
| 11 | elastic_net | 9.74405 | 12.42996 | -0.3601 | -2.3590 +/- 1.4721 | no |
| 12 | decision_tree | 13.49350 | 16.83620 | -1.4953 | -2.9083 +/- 2.9463 | no |
| 13 | lasso | 12.36710 | 14.80286 | -0.9290 | -4.5491 +/- 5.1078 | no |
| 14 | linear_regression | 13.05467 | 15.54701 | -1.1278 | -6.1539 +/- 6.9979 | no |
| 15 | mlp | 30.02775 | 40.41783 | -13.3808 | -30.7018 +/- 36.7152 | no |

## Legacy absolute-PI comparison (P12 context)

Absolute-PI RF held-out R2 = -0.7842; soiling_ratio RF test R2 = -0.5585. Reframing aligns ML with within-segment physics.

## Multi-family verdict (P13)

No algorithm in the 15-model panel achieves non-negative blocked CV R2 **and** beats the days_since_wash trend on held-out test. No model reaches CV R2 >= 0; Best CV R2: **svr_rbf** (-0.4396 +/- 0.5911). The negative ML finding now holds across linear, kernel, tree, boosting, and neural families — the simple physical trend suffices.

MLPRegressor uses a small network; n=301 train rows is marginal for neural models — interpret MLP scores cautiously.

Figure: `reports/figures/ml_panel_cv_r2_comparison.png` (blocked CV R2 with test R2 overlaid; zero reference line).

## Permutation importance

Skipped: no model has CV R2 >= 0 and beats the trend baseline. Best CV R2 = -0.4396 (svr_rbf).

