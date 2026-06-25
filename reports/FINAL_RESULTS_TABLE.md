| metric | value | unit | source |
|---|---|---|---|
| soiling_rate_pct_per_day | -0.1247 | %/day | P3.5 clear-sky pooled |
| soiling_rate_ci_half_width | 0.0608 | %/day | P3.5 |
| median_wash_recovery_pct | 9.64 | % | P3 segment median |
| pollution_daily_hac_verdict | not supported at daily resolution (confirmed with in-situ PM10) | text | P3.5/P11 in-situ definitive test |
| pollution_pm10_hac_p_value | 0.727 |  | CAMS accumulated |
| pollution_ground_pm10_hac_p_value | 0.928 |  | Ground PM10 accumulated (Merkez UHKIA) |
| ground_pm10_accumulated_pairs | 422 | days | Clean days with observed ground PM10 |
| optimal_wash_interval_T_star | 99 | days | P4 real_2023 PTF |
| optimal_interval_ci | 81-139 | days | P4 rate CI |
| T_star_legacy_assumed_2000 | 104 | days | Previous assumed PTF |
| actual_mean_inter_wash_gap | 79 | days | Enerjisa washing_events |
| rain_mean_pi_recovery | -0.0067 | PI units | P3.5 rain |
| rain_share_positive_uplift | 74.0 | % | P3.5 positive recoveries only |
| ml_soiling_ratio_rf_test_r2 | -0.5585 |  | P12 reframed target |
| ml_absolute_pi_rf_test_r2 | -0.7842 |  | P5 legacy target (comparison) |
| ml_soiling_ratio_rf_cv_r2 | -1.3525 +/- 2.1188 |  | P12 blocked TimeSeriesSplit |
| ml_soiling_ratio_trend_test_r2 | -0.8942 |  | days_since_wash linear baseline |
| ml_verdict | Random Forest modestly beats the trend baseline on the held-out window, but blocked CV R2 remains negative — treat ML ga | text | P12 soiling_ratio framing |
| rf_test_mae | 10.7816 |  | P12 soiling_ratio RF held-out |
| rf_test_r2 | -0.5585 |  | P12 soiling_ratio RF held-out |
| baseline_days_since_wash_r2 | -0.8942 |  | P12 days_since_wash on soiling_ratio |
| central_ptf_tl_mwh | 2189.30 | TL/MWh | real_2023 |
