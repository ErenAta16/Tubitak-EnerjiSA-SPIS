| metric | value | unit | source |
|---|---|---|---|
| soiling_rate_pct_per_day | -0.1247 | %/day | clear-sky pooled |
| soiling_rate_ci_half_width | 0.0608 | %/day | clear-sky pooled uncertainty |
| median_wash_recovery_pct | 9.64 | % | segment median |
| pollution_daily_hac_verdict | not supported at daily resolution (confirmed with in-situ PM10) | text | in-situ definitive test |
| pollution_pm10_hac_p_value | 0.727 |  | CAMS accumulated |
| pollution_ground_pm10_hac_p_value | 0.928 |  | Ground PM10 accumulated (Merkez UHKIA) |
| ground_pm10_accumulated_pairs | 422 | days | Clean days with observed ground PM10 |
| optimal_wash_interval_T_star | 99 | days | real_2023 PTF |
| optimal_interval_ci | 81-139 | days | soiling-rate CI |
| T_star_legacy_assumed_2000 | 104 | days | Previous assumed PTF |
| actual_mean_inter_wash_gap | 79 | days | Enerjisa washing_events |
| rain_mean_pi_recovery | -0.0067 | PI units | rain events |
| rain_share_positive_uplift | 74.0 | % | positive recoveries only |
| ml_soiling_ratio_rf_test_r2 | -0.5585 |  | within-segment target |
| ml_absolute_pi_rf_test_r2 | -0.7842 |  | legacy absolute target (comparison) |
| ml_soiling_ratio_rf_cv_r2 | -1.3525 +/- 2.1188 |  | blocked TimeSeriesSplit |
| ml_soiling_ratio_trend_test_r2 | -0.8942 |  | days_since_wash linear baseline |
| ml_panel_best_cv_r2 | -0.4396 +/- 0.5911 |  | best: svr_rbf |
| ml_panel_model_count | 15 | count | algorithm panel |
| ml_panel_any_cv_r2_non_negative | False | bool | blocked TimeSeriesSplit |
| ml_verdict | No algorithm in the 15-model panel achieves non-negative blocked CV R2 **and** beats the days_since_wash trend on held-out test. No model reaches CV R2 >= 0; Best CV R2: **svr_rbf** (-0.4396 +/- 0.5911). The negative ML finding now holds across linear, kernel, tree, boosting, and neural families — the simple physical trend suffices. | text | multi-family panel |
| rf_test_mae | 10.7816 |  | soiling_ratio RF held-out |
| rf_test_r2 | -0.5585 |  | soiling_ratio RF held-out |
| baseline_days_since_wash_r2 | -0.8942 |  | days_since_wash on soiling_ratio |
| central_ptf_tl_mwh | 2189.30 | TL/MWh | real_2023 |
