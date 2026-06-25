# External validation — DKASC Alice Springs vs Canakkale

## Verdict

Clear-sky pooled soiling rate: Canakkale -0.1247 %/day (CI -0.2254 .. -0.0241) vs Alice Springs -0.0384 %/day (CI -0.5439 .. 0.4671). Alice Springs does not show materially faster soiling than Canakkale once clear-sky filtering is applied; the desert site is not dramatically dustier in this ~5 kW research array. Neither site shows a significant daily CAMS pollution–PI decay link after trend removal. The generalization test does not validate a dust-driver hypothesis at grid scale even in central Australia; both sites appear dominated by other soiling/recovery dynamics at this temporal resolution. Alice Springs used 57 inferred cleaning events (rain >= 10 mm and/or PI step >= 5% vs rolling median); rates are approximate.

## Comparison table

| Site | Clear-sky rate (%/day) | 95% CI | PM10 HAC coef | PM10 p | Dust HAC coef | Dust p | Pollution sig.? |
|---|---:|---|---:|---:|---:|---:|---|
| Canakkale Hybrid GES | -0.1247 | [-0.2254, -0.0241] | 1.2480219758461097e-05 | 0.7270621311715896 | 5.4809231205801e-05 | 0.6596967140685642 | no |
| DKASC Alice Springs | -0.0384 | [-0.5439, 0.4671] | 5.5303244106025436e-09 | 0.08132798984573436 | 2.3548417389714836e-09 | 0.10370582074555736 | no |

## Cleaning-inference caveat (Alice Springs)

No operator wash log exists at DKASC. Cleaning events were inferred from:
- Rainfall >= 10 mm/day (onsite Weather_Daily_Rainfall), and
- Abrupt PI recoveries >= 5% above a 7-day rolling median.
Events within 3 days were merged. Segment soiling rates are therefore approximate and not directly comparable to Canakkale's logged brush/robot washes.

## kW-scale research-array caveat

Data source: Canadian Solar 5.3 kW poly-Si fixed tilt (DKASC array 32, M18 B Phase II) (~5.3 kW AC research array, not a utility plant). Single-array noise, inverter clipping, and reference-sensor co-soiling can differ from Canakkale Hybrid GES (~2750 kW AC). Results test method generalization, not commercial fleet performance.

## DKASC column mapping (verified from header)

- `timestamp` -> `timestamp`
- `active_power_kw` -> `Active_Power`
- `active_energy_cumulative` -> `Active_Energy_Delivered_Received`
- `ghi_wm2` -> `Global_Horizontal_Radiation`
- `weather_temperature_c` -> `Weather_Temperature_Celsius`
- `weather_humidity_pct` -> `Weather_Relative_Humidity`
- `weather_wind_speed` -> `Wind_Speed`
- `weather_rainfall_mm` -> `Weather_Daily_Rainfall`

## Temperature coefficient assumption

Assumed -0.41 %/degC from Canadian Solar poly module datasheet class (CS6K-style); DKASC metadata does not publish a verified coefficient.

Analysis window: 2023-01-01 .. 2025-10-22 (aligned with Canakkale).
