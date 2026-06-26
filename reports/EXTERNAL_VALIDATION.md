# External validation — DKASC Alice Springs vs Canakkale

## Verdict

Primary conclusion: the external generalization test is INCONCLUSIVE for recoverable soiling loss on DKASC fixed-tilt research arrays. These ~5 kW arrays appear actively maintained (rain and inferred PI recoveries), so dust-driven soiling does not accumulate between inferred cleanings the way it does at Canakkale Hybrid GES. Canakkale clear-sky pooled rate (canonical CI method): -0.1247 %/day (95% CI [-0.1855, -0.0640]). Per-array DKASC clear-sky rates: array 13: 0.1674 %/day [-9.2212, 9.5559], PM10 HAC p=0.029 (inconclusive (CI spans zero)); array 18: 0.0947 %/day [-4.7515, 4.9409], PM10 HAC p=0.007 (inconclusive (CI spans zero)); array 14: -0.1437 %/day [-4.1452, 3.8577], PM10 HAC p=0.712 (inconclusive (CI spans zero)); array 32: 0.5471 %/day [-5.0271, 6.1213], PM10 HAC p=0.011 (inconclusive (CI spans zero)). All four fixed-tilt arrays show near-zero point estimates with wide CIs spanning zero; no recoverable desert soiling signal is demonstrated on these maintained research arrays. Pollution association: Canakkale PM10 HAC p=0.727; DKASC arrays span p=0.007..0.712 (closest to significance at the desert site is p≈0.01). That is a hint, not a conclusion — neither site reaches HAC p<0.05 on the accumulated CAMS spec used here. No operator wash log exists at DKASC. Cleaning events were inferred from rainfall and PI step recoveries only. Under strict/default/sensitive threshold presets the largest per-array rate shift was 1.4090 %/day — see sensitivity table. Daily PI uses the selected energy channel logged per array (cumulative inverter counter when valid, else integrated Active_Power). Recommended next external test: a utility-scale soiling dataset such as NREL PVDAQ system 2107 (~893 kW, California agricultural area) via the public OEDI/AWS bucket. That was not ingested in this work package.

## Comparison table (canonical CI method)

CI method for all sites: `clear_sky_pooled_weighted_by_n_fit` — weighted mean of segment clear-sky Theil-Sen rates by `clear_n_fit`, with half-width = mean segment Theil-Sen CI width / 2 (same as Canakkale P4 `p4_verdict`).

| Site / array | Clear-sky rate (%/day) | 95% CI | PM10 HAC p | Dust HAC p | Pollution sig.? | Inferred cleanings |
|---|---:|---|---:|---:|---|---:|
| Canakkale Hybrid GES | -0.1247 | [-0.1855, -0.0640] | 0.7270621311715896 | 0.6596967140685642 | no |  |
| DKASC array 13 | 0.1674 | [-9.2212, 9.5559] | 0.029011772025135406 | 0.012842089587224917 | no | 56 |
| DKASC array 18 | 0.0947 | [-4.7515, 4.9409] | 0.007203363819428786 | 0.011510800784584593 | no | 57 |
| DKASC array 14 | -0.1437 | [-4.1452, 3.8577] | 0.7124716426818489 | 0.5459374485444851 | no | 57 |
| DKASC array 32 | 0.5471 | [-5.0271, 6.1213] | 0.010688818955303993 | 0.020021620072582506 | no | 57 |

## Daily energy channel selection (DKASC)

- Array 13: `cumulative_counter` (median power/counter ratio 0.8973). Inverter cumulative Active_Energy_Delivered_Received daily difference used (median power/counter ratio 0.8973; 99.4% days with positive counter).
- Array 18: `cumulative_counter` (median power/counter ratio 0.8843). Inverter cumulative Active_Energy_Delivered_Received daily difference used (median power/counter ratio 0.8843; 99.6% days with positive counter).
- Array 14: `cumulative_counter` (median power/counter ratio 0.8818). Inverter cumulative Active_Energy_Delivered_Received daily difference used (median power/counter ratio 0.8818; 99.5% days with positive counter).
- Array 32: `cumulative_counter` (median power/counter ratio 0.8942). Inverter cumulative Active_Energy_Delivered_Received daily difference used (median power/counter ratio 0.8942; 99.2% days with positive counter).

## Cleaning-inference sensitivity (no wash log)

No operator wash log exists at DKASC. Three threshold presets were applied:
- **strict**: rain >= 15 mm, PI step >= 7%, min gap 21 days.
- **default**: rain >= 10 mm, PI step >= 5%, min gap 14 days.
- **sensitive**: rain >= 5 mm, PI step >= 3%, min gap 7 days.

| Preset | Array | Rate (%/day) | 95% CI | Inferred cleanings |
|---|---|---:|---|---:|
| strict | 13 | -0.2251 | [-3.8111, 3.3610] | 39 |
| strict | 18 | -0.1987 | [-2.5187, 2.1214] | 40 |
| strict | 14 | -0.0534 | [-2.3418, 2.2350] | 41 |
| strict | 32 | 0.0620 | [-1.8882, 2.0122] | 42 |
| default | 13 | 0.1674 | [-9.2212, 9.5559] | 56 |
| default | 18 | 0.0947 | [-4.7515, 4.9409] | 57 |
| default | 14 | -0.1437 | [-4.1452, 3.8577] | 57 |
| default | 32 | 0.5471 | [-5.0271, 6.1213] | 57 |
| sensitive | 13 | -1.2416 | [-23.4393, 20.9562] | 104 |
| sensitive | 18 | -0.9624 | [-21.5452, 19.6204] | 100 |
| sensitive | 14 | -0.8416 | [-20.7451, 19.0619] | 107 |
| sensitive | 32 | -0.5935 | [-20.4659, 19.2788] | 111 |

## kW-scale research-array caveat

Data sources: four fixed-tilt DKASC silicon research arrays (~5 kW AC each, arrays 13/14/18/32 — Trina mono-Si, SunPower mono-Si, Kyocera poly-Si, Canadian Solar poly-Si). Array 10 (SunPower) export was corrupt at the DKASC source and was replaced by array 32. These are maintained research strings, not utility plants. Single-array noise, inverter clipping, and reference-sensor co-soiling differ from Canakkale Hybrid GES (~2750 kW AC). Results test method portability, not commercial fleet performance.

## Recommended future external test

Utility-scale soiling validation should use an independently maintained plant with documented washing or long soiling accumulation, e.g. NREL PVDAQ system 2107 (~893 kW, California agricultural area) from the public OEDI/AWS bucket. Ingest was not attempted in P16.

## Temperature coefficient assumptions

- Array 13: Assumed -0.41 %/degC from Trina mono-Si datasheet class; DKASC metadata does not publish a verified coefficient.
- Array 18: Assumed -0.38 %/degC from SunPower mono-Si datasheet class; DKASC metadata does not publish a verified coefficient.
- Array 14: Assumed -0.45 %/degC from Kyocera poly-Si datasheet class; DKASC metadata does not publish a verified coefficient.
- Array 32: Assumed -0.41 %/degC from Canadian Solar poly module datasheet class (CS6K-style); DKASC metadata does not publish a verified coefficient.

Analysis window: 2023-01-01 .. 2025-10-22 (aligned with Canakkale).
## PVDAQ 2107 utility-scale validation

PVDAQ 2107 (893 kWdc Farm Solar Array, Arbuckle CA, Csa dry-summer agricultural) analysis window 2018-01-08 .. 2024-11-01 (2361 days with adequate 15-min coverage). Canakkale clear-sky rate -0.1247 %/day (CI [-0.1855, -0.0640]); PVDAQ 0.0908 %/day (CI [-0.5125, 0.6941]). PVDAQ clear-sky soiling CI spans zero — the utility-scale signal is not fully recoverable under inferred-cleaning segmentation despite the dry Csa climate; interpret with cleaning-inference and POA sensor caveats. Pollution HAC: Canakkale PM10 p=0.727, PVDAQ PM10 p=0.017 (accumulated CAMS spec after segment detrending). No operator wash log at PVDAQ; cleanings inferred from NASA precipitation and PI step recoveries only.

CI method: `clear_sky_pooled_weighted_by_n_fit` (same as Canakkale P4).

### Canakkale vs PVDAQ 2107

| Site | Clear-sky rate (%/day) | 95% CI | CI width | Recoverable signal? | PM10 p | Dust p | Inferred cleanings |
|---|---:|---|---:|---|---:|---:|---:|
| Canakkale Hybrid GES | -0.1247 | [-0.1855, -0.0640] | 0.1215 | yes | 0.7270621311715896 | 0.6596967140685642 |  |
| PVDAQ 2107 Farm Solar Array (Arbuckle CA) | 0.0908 | [-0.5125, 0.6941] | 1.2066 | no | 0.016810539637580727 | 0.08800801890841928 | 71 |

### PVDAQ data access and channels

- OEDI bucket: `oedi-data-lake`, prefix `pvdaq/2023-solar-data-prize/2107_OEDI/`
- System: Farm Solar Array (893.0 kWdc), Arbuckle, CA, climate Csa.
- Energy: Revenue-grade AC meter channel meter_revenue_grade_ac_output_meter_149578 is interval-mean kW (metadata units=kW, aggregation=avg); no cumulative energy counter is exposed in the prize export slices.
- Precipitation: NASA POWER PRECTOTCORR (no onsite rain gauge in prize export)
- Module temp coeff: Assumed -0.41 %/degC from Hyundai HiS-M310TI mono-Si datasheet class; PVDAQ metadata does not publish a verified coefficient.
- Inferred cleaning (no wash log): rain >= 25 mm, PI step >= 7%, min gap 30 days.
