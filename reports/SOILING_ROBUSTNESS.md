# P3.5 Soiling Robustness Verdict

## Clear-sky slope sharpening

Clearness index k = ALLSKY/CLRSKY from NASA POWER. High-clearness days use k >= 0.7.

## Daily pollution test (CAMS vs in-situ)

Clean-day input: 750; regression n after trend removal (CAMS PM10): 557.
Ground PM10 accumulated paired days: 422; ground PM10 daily: 422; ground PM2.5 accumulated: 496.

Side-by-side HAC regressions on trend-removed PI residuals:

| Source / variable | n | HAC coef | 95% CI | partial R2 | p |
|---|---:|---:|---|---:|---:|
| CAMS PM10 accumulated | 557 | 1.2480219758461097e-05 | [-5.760070906756325e-05, 8.256114858448544e-05] | 0.0006311298436969537 | 0.7270621311715896 |
| Ground PM10 accumulated | 422 | 1.4765394139659467e-06 | [-3.056890385159967e-05, 3.352198267953156e-05] | 5.8809549207450296e-05 | 0.9280423593302465 |
| Ground PM10 daily | 422 | -0.002272333062611932 | [-0.004305209162957378, -0.00023945696226648728] | 0.017822341127047947 | 0.028463918154038603 |
| Ground PM2.5 accumulated | 496 | 2.4660754331530698e-05 | [-5.102133428891431e-05, 0.0001003428429519757] | 0.0019208086357748178 | 0.5230521560312753 |
| Ground PM2.5 daily | 496 | -0.00110567347481522 | [-0.0051404877632903745, 0.002929140813659935] | 0.00073278941463506 | 0.5912017189333534 |

Verdict: **not supported at daily resolution (confirmed with in-situ PM10)**. CAMS attenuation concern resolved: ground PM10 accumulated also null. Sensitivity: daily raw ground PM10 HAC p=0.028 (not the P3.5 accumulated spec). Association only; not proven causation.

## Spatial proxy caveat (in-situ PM)

In-situ PM10/PM2.5 comes from Canakkale Merkez UHKIA (TR170141), an urban monitor ~40-60 km from the rural hybrid plant. Even ground readings are a spatial proxy for field soiling; on-site reference dust instrumentation (recommended future work for Enerjisa) would be the only direct measure.

## Rain natural washing

Mean PI recovery per rain event: -0.006734735294061635 (95% CI -0.05092077511237886 .. 0.03898457538037984).
Rain share of positive cleaning uplift: 74.0% vs washing 26.0%.

## Irradiance-sensor caveat

The SCADA irradiance column (ISINIM) is a plant-level daily integrated irradiation signal, likely from an in-plane reference sensor. If that sensor soiling tracks module soiling, true panel degradation is partially cancelled in PI = production/irradiation, so observed soiling rates are a lower bound on physical soiling. No sensor datasheet was found in the repository; this limitation is not corrected, only flagged.

## P4 recommendation

Robust enough to schedule: **True**.

Use rate **-0.1247 %/day** (clear_sky_pooled_weighted_by_n_fit) with uncertainty half-width ~0.0608.

## Report framing

Frame soiling as a robust seasonal loss rate corrected for clear days, with rain as a parallel natural-cleaning pathway. Do not claim pollution causality unless daily HAC coefficients are significant; emphasise irradiance-sensor co-soiling as an upward bias bound on true loss.
