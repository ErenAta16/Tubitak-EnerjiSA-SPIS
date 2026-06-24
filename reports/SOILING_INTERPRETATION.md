# P3 Soiling Analysis Interpretation

Generated from `python -m spis.run --stage soiling` on the Canakkale master table.

## Headline finding

Temperature-corrected PI declines between most washes at a typical rate of about
**-0.09 %/day** (pooled across seven post-wash segments, rain-free clean days only).
Summer segments show slower apparent loss (~**-0.05 %/day** mean) than autumn peaks
(segments 1 and 5 near **-0.22 to -0.30 %/day**). Segment 2 (winter) shows a
**positive** robust slope and is flagged `unexpected_positive_slope`; treat it as
noisy winter behaviour, not a physical soiling gain.

## Rain handling

Soiling slopes use **rain-free clean days only** (method a). Rain days remain in
the timeline figure as cyan crosses but are excluded from Theil-Sen fits so natural
washing does not bias a single straight line.

## Recovery

Five of seven washes show positive temp-corrected PI recovery in the 3-day windows.
Segments 1, 2, and 6 show non-positive recovery (likely overlap with exclusions or
short clean windows); see `recovery_note` in `soiling_segments.parquet`.

## Method comparison (descriptive only)

Six brush+solution inter-wash segments vs one robot (no-solution) segment (segment 5).
With **n=1** robot wash, no statistical test is applied. Segment 5 rate
(**-0.22 %/day**) is in line with autumn brush segments; no overclaim is made.

## Pollution association

Segment-level correlation of soiling rate vs accumulated CAMS PM10 is weak and not
significant at n=7 (r ≈ -0.16, p ≈ 0.73). This is reported as **association only**,
not causation; more segments or daily residuals would be needed for stronger inference.

## P4 input

Recommended schedule input: **summer mean rate -0.055 %/day** (segments 4 and 7).
Pooled rate **-0.090 %/day** (95% approx CI -0.18 to -0.004) is the cross-season fallback.

## Figures

| file | content |
|---|---|
| `reports/figures/soiling_timeline_slopes.png` | PI timeline, wash lines, rain markers, rain-free fits |
| `reports/figures/soiling_rate_by_segment.png` | Segment rates with Theil-Sen CIs, coloured by season |
| `reports/figures/soiling_recovery_by_wash.png` | Recovery % per wash event |
| `reports/figures/soiling_rate_vs_pm10.png` | Segment rate vs accumulated PM10 |

Each PNG has a matching CSV alongside it for reproducibility.
