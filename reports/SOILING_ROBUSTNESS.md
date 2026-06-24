# P3.5 Soiling Robustness Verdict

## Clear-sky slope sharpening

Clearness index k = ALLSKY/CLRSKY from NASA POWER. High-clearness days use k >= 0.7.

## Daily pollution test

Clean-day input: 750; regression n after trend removal: 557.

PM10 HAC coefficient: 1.2480219758461097e-05, 95% CI [-5.760070906756325e-05, 8.256114858448544e-05], p=0.7270621311715896.

Verdict: **not supported at daily resolution (n~750)**. Association only; not proven causation.

## Rain natural washing

Mean PI recovery per rain event: -0.006734735294061635 (95% CI -0.05092077511237886 .. 0.03898457538037984).
Rain share of positive cleaning uplift: 74.0% vs washing 26.0%.

## Irradiance-sensor caveat

The SCADA irradiance column (ISINIM) is a plant-level daily integrated irradiation signal, likely from an in-plane reference sensor. If that sensor soiling tracks module soiling, true panel degradation is partially cancelled in PI = production/irradiation, so observed soiling rates are a lower bound on physical soiling. No sensor datasheet was found in the repository; this limitation is not corrected, only flagged.

## P4 recommendation

Robust enough to schedule: **True**.

Use rate **-0.1247 %/day** (clear_sky_pooled_weighted_by_n_fit) with uncertainty half-width ~0.0608.

## Report framing

Frame soiling as a robust seasonal loss rate corrected for clear days, with rain as a parallel natural-cleaning pathway. Do not claim CAMS causality unless daily HAC coefficients are significant; emphasise irradiance-sensor co-soiling as an upward bias bound on true loss.
