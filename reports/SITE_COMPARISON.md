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

## Ground-station vs CAMS cross-check (national network)

In-situ PM from sim.csb.gov.tr daily exports (StationDataDownloadNewData). Canakkale: **TR170141** (Canakkale Merkez UHKIA). Balikesir proxy: **TR100241** (Bandirma-MTHM; nearest national station to PROVISIONAL Balikesir coordinates).

| Site | Pollutant | Station | n | Pearson r | Median bias (g-c) | Ground med. | CAMS med. | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---|
| canakkale | pm10 | TR170141 | 832 | 0.574 | 16.90 | 30.1 | 12.5 | Ground PM10 exceeds CAMS on median; CAMS captures direction but may underestimate absolute local PM10. |
| canakkale | pm2_5 | TR170141 | 930 | 0.609 | 4.94 | 13.7 | 8.6 | Ground and CAMS PM2.5 agree in magnitude and covary on daily scale; CAMS is a reasonable proxy for relative pollution context. |
| balikesir PROVISIONAL | pm10 | TR100241 | 931 | 0.737 | 22.11 | 37.5 | 15.7 | Ground PM10 exceeds CAMS on median; CAMS captures direction but may underestimate absolute local PM10. |

### Ground PM10 synthesis

- **canakkale**: Ground PM10 exceeds CAMS on median; CAMS captures direction but may underestimate absolute local PM10.
- **balikesir**: Ground PM10 exceeds CAMS on median; CAMS captures direction but may underestimate absolute local PM10.

Implication for SPIS: national ground PM10 at Canakkale exceeds CAMS by ~2.4x on median (30.1 vs 12.5 ug/m3). Weak daily pollution–performance links remain credible: CAMS supports relative context but not absolute local particulate load.
