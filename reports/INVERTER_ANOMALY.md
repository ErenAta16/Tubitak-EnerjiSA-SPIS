# Inverter relative-performance screening (Canakkale)

## Method (descriptive, not diagnostic)

- Days with meteo irradiance >= 500 Wh/m2/day only.
- Each inverter daily output divided by the cross-inverter median that day.
- Candidate underperformer if median relative < 0.95 and >= 25% of days below threshold.
- **This ranks peers; it does not diagnose root cause (soiling, fault, curtailment).**

## Ranking (best to worst median relative performance)

| Rank | Inverter | Median rel. | Mean rel. | Days | Frac below thresh | Flag |
|---:|---|---:|---:|---:|---:|---|
| 1 | INV1 | 1.008 | 1.412 | 6 | 33.33% | - |
| 2 | INV3 | 0.997 | 1.048 | 5 | 0.00% | - |
| 3 | INV4 | 0.996 | 0.996 | 6 | 16.67% | - |
| 4 | INV2 | 0.941 | 0.866 | 6 | 50.00% | candidate |

## Candidate underperformers

- **INV2**: median relative 0.941

- Window: 2025-04-29 .. 2025-10-23
- Meaningful-irradiance day-rows: 23
