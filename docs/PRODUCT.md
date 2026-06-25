# SPIS product description (v1.0)

## Purpose

SPIS quantifies soiling-driven PV performance loss at Enerjisa plants, optimizes panel-
washing economics, and supports field verification. It is the software deliverable
for the TUBITAK 2209-B project (Canakkale Hybrid GES primary site; Balikesir
environmental comparison when operational data is unavailable).

## Inputs

### Required (Canakkale)

- Daily production + irradiance workbook
- Downtime / curtailment log
- Panel washing event dates
- Inverter daily production (for P6 screening)

Stored under `data/raw/` (gitignored). Schema in `docs/DATA_DICTIONARY.md`.

### External (auto-fetched)

- NASA POWER daily weather at plant coordinates
- Open-Meteo / CAMS daily pollution
- Turkish national AQ ground stations via `sim.csb.gov.tr` (Canakkale TR170141,
  Bandirma TR100241 for Balikesir proxy)

### Optional

- EPIAS PTF CSV files in `data/external/epias_ptf/` (2023 supplied; 2024–2025 from
  seffaflik.epias.com.tr extends P4)

## Outputs

| Artifact | Location | Description |
|---|---|---|
| Master daily table | `data/processed/master_daily.parquet` | P2 analysis spine |
| Soiling segments | `data/processed/soiling_segments.parquet` | P3 inter-wash slopes |
| Robustness | `data/processed/soiling_robustness.parquet` | P3.5 clear-sky pooled rate |
| Washing optimization | `data/processed/washing_optimization.parquet` | P4 T* and sweeps |
| Site comparison | `data/processed/site_comparison.parquet` | P9 environmental + ground check |
| Inverter anomaly | `data/processed/inverter_anomaly.parquet` | P6 peer ranking |
| Reports | `reports/*.md` | Human-readable findings |
| Figures | `reports/figures/*.{png,csv}` | Publication plots (300 dpi) |

## How to run end to end

```bash
python -m spis.run --stage all
```

Stages execute in order: ingest → clean → soiling → robustness → optimize → ml →
report → site_comparison → inverter_anomaly → field_visit.

Requires local Canakkale raw data and network access for first-time external pulls
(cached under `data/external/` thereafter).

## Multi-site capability

`src/spis/sites.py` registry:

- **canakkale** — confirmed coordinates, full SCADA pipeline
- **balikesir** — PROVISIONAL coordinates, environmental comparison only until Enerjisa
  supplies raw files

Site-key parameterization applies to NASA POWER, CAMS, ingest, and master build.
Canakkale keeps legacy flat processed paths for regression compatibility.

## Limitations

- Soiling rates are a **lower bound** when the reference irradiance sensor co-soils
  with modules (see `reports/FIELD_VISIT_PACK.md`).
- CAMS gridded pollution does not match absolute ground PM10; national-station cross-
  check documented in `reports/SITE_COMPARISON.md`.
- P4 wash cost is **ASSUMED**; PTF central uses real 2023 only unless extended CSVs
  are supplied.
- P5 ML test performance is poor; not used for scheduling decisions.
- P6 inverter ranking is **descriptive**, not diagnostic.
- Balikesir site coordinates and Bandirma ground-station proxy are **PROVISIONAL**.

## Verification

Each phase has a script under `scripts/verify_*.py`. Run the full suite:

```bash
python scripts/run_all_verifiers.py
```

Independent cross-checks include master-table hash regression, closed-form T*
agreement, and reproducible parquet hashes on repeated runs.
