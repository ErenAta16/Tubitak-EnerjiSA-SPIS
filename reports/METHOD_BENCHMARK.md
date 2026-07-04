# Method benchmark — SPIS vs RdTools SRR

## Verdict

RdTools SRR (Deceglie et al. 2018) targets a sawtooth of dry accumulation plus sharp cleaning events. Canakkale's frequent rain and logged washes may yield little SRR-detected soiling — consistent with our rain-as-cleaning finding. Canakkale: SPIS -0.1247 %/day vs RdTools median interval slope -0.1649 %/day (qualitative agreement on sign and order of magnitude). PVDAQ 2107: SPIS 0.0908 %/day vs RdTools -0.2609 %/day (methods disagree on sign — investigate rain/cleaning segmentation). SPIS clear-sky Theil-Sen pooled rate and RdTools SRR interval slopes are not identical estimands: SPIS uses logged/inferred wash segments with clearness filtering; SRR uses stochastic cleaning detection on daily PI. Compare sign and order of magnitude, not point equality.

## Representation conversion

- **SPIS:** segment Theil-Sen slopes on clear-sky days, pooled with `clear_sky_pooled_weighted_by_n_fit` CI half-width.
- **RdTools SRR:** insolation-weighted daily PI (`pi_temp_corrected`) with stochastic cleaning detection (`clean_criterion='shift'`); headline outputs are soiling ratio (energy lost fraction) plus per-interval `%/day` slopes in `soiling_interval_summary`.
- **Comparison rule:** qualitative sign agreement and order-of-magnitude check; no parameter tuning to force match.

## Side-by-side table

| Site | SPIS rate (%/day) | SPIS 95% CI | RdTools SRR ratio | RdTools ratio CI | RdTools median interval slope (%/day) | Intervals | Agreement |
|---|---:|---|---:|---|---:|---:|---|
| Canakkale Hybrid GES | -0.1247 | [-0.1855, -0.0640] | 0.9473 | [0.9352, 0.9563] | -0.1649 | 53 | qualitative agreement on sign and order of magnitude |
| PVDAQ 2107 Farm Solar Array (Arbuckle CA) | 0.0908 | [-0.5125, 0.6941] | 0.9189 | [0.8259, 0.9826] | -0.2609 | 161 | methods disagree on sign — investigate rain/cleaning segmentation |

## Caveats

- Canakkale uses horizontal SCADA irradiance; PVDAQ uses POA — RdTools expects POA insolation; Canakkale comparison is approximate.
- Neither method uses operator wash logs for PVDAQ or DKASC; cleaning inference differs between SPIS segments and SRR stochastic detection.
- RdTools installed from `requirements-bench.txt`; core SPIS pipeline does not import rdtools.
