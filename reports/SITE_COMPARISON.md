# Site environmental comparison (Canakkale vs Balikesir)

## Status flags

- Canakkale: **CONFIRMED** (operational SCADA available).
- Balikesir: **PROVISIONAL** — PROVISIONAL placeholder for Balikesir RES area pending KMZ confirmation; no operational SCADA files present under data/raw/balikesir/.

## Verdict

Balikesir PROVISIONAL coordinates do NOT show consistently lower pollution than Canakkale; the proposal premise that Balikesir is cleaner is NOT supported at this placeholder location.

## Pollution test summary

| Variable | Median Canakkale | Median Balikesir | Med diff (Bal-Can) | 95% CI | Overlap | p (Bal<Can) | Bal lower? |
|---|---:|---:|---:|---|---:|---:|---|
| pm10 | 12.263 | 15.933 | 3.666 | [2.898, 4.519] | 0.769 | 1 | no |
| pm2_5 | 8.519 | 11.685 | 3.160 | [2.571, 3.629] | 0.712 | 1 | no |
| dust | 0.708 | 0.667 | -0.042 | [-0.208, 0.167] | 0.968 | 0.3922 | no |
| aerosol_optical_depth | 0.141 | 0.159 | 0.020 | [0.009, 0.028] | 0.877 | 1 | no |

## Limitations

- Balikesir coordinates are **PROVISIONAL** (no KMZ confirmed; no operational data).
- Comparison is **environmental only** — no performance or soiling metrics for Balikesir.
- CAMS/Open-Meteo are reanalysis/gridded products, not on-site measurements.

## Enerjisa data needed for full two-site performance comparison

1. Confirmed plant coordinates (KMZ or as-built layout).
2. Daily production + plane-of-array irradiance (same schema as Canakkale workbook).
3. Downtime/curtailment log and washing event dates for Balikesir.
4. Inverter-level daily production if feeder/inverter diagnostics are required.
5. Reference irradiance sensor maintenance/cleaning log (both sites).

- Analysis window: 2023-01-01 .. 2025-10-22
- Daily rows compared: Canakkale 1026, Balikesir 1026
