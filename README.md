# SPIS — Solar Performance Improvement System

Data-driven soiling analysis, washing-schedule optimization, and multi-site
environmental comparison for Enerjisa hybrid PV plants. TUBITAK 2209-B research
project.

## Question

How fast does environmental soiling degrade irradiance-normalized PV performance
between washes, and what washing interval minimizes total cost?

## Headline findings (honest)

- **Soiling rate (Canakkale):** clear-sky pooled loss ~0.05%/day (P3.5); modest and
  not driven by daily CAMS pollution at grid scale.
- **Optimal wash interval T*:** ~99 days at real 2023 EPIAS PTF (assumed wash cost);
  true interval may be shorter if the reference irradiance sensor co-soils.
- **Pollution vs performance:** daily HAC tests do not support pollution as a primary
  driver; ground-station PM10 at Canakkale is much higher than CAMS grid values.
- **Balikesir vs Canakkale (CAMS):** PROVISIONAL Balikesir coordinates are **not**
  consistently cleaner than Canakkale in gridded CAMS — proposal premise not supported
  at the placeholder point.
- **Inverters (descriptive):** INV2 ranks lowest vs daily peer median on meaningful-
  irradiance days; not fault diagnosis.
- **ML (P5):** test R² negative; documented as exploratory only.

## Data sources

| Source | Role | Auth |
|---|---|---|
| Enerjisa SCADA workbooks (`data/raw/`) | Production, irradiance, downtime, washing | Proprietary (gitignored) |
| NASA POWER | Weather, clear-sky baselines | None |
| Open-Meteo / CAMS | Gridded pollution | None |
| Turkish national AQ (`sim.csb.gov.tr`) | Ground PM10/PM2.5 cross-check | Session form POST |
| EPIAS PTF CSV (`data/external/epias_ptf/`) | Real 2023 price; 2024–2025 self-download | None |

## Layout

```
src/spis/           library code (loaders, models, reports)
data/raw/           plant inputs (not committed)
data/external/      cached API pulls (not committed)
data/processed/     analysis tables (not committed)
reports/            markdown reports + figures (committed)
tests/              unit tests
docs/               plan, dictionary, product docs
scripts/            verifier gates
```

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
pip install scipy matplotlib pandas pyarrow openpyxl requests pytest ruff scikit-learn statsmodels joblib
```

Place Canakkale raw files under `data/raw/` (see `docs/DATA_DICTIONARY.md`).

Optional: drop EPIAS PTF CSV exports for 2024–2025 into `data/external/epias_ptf/` from
[seffaflik.epias.com.tr](https://seffaflik.epias.com.tr) to extend P4 beyond 2023 nominal
price.

## Run instructions

**Full v1.0 pipeline (one command):**

```bash
python -m spis.run --stage all
# or
make all
```

**Individual stages:**

```bash
python -m spis.run --stage ingest
python -m spis.run --stage clean
python -m spis.run --stage soiling
python -m spis.run --stage robustness
python -m spis.run --stage optimize
python -m spis.run --stage ml
python -m spis.run --stage report
python -m spis.run --stage site_comparison
python -m spis.run --stage inverter_anomaly
python -m spis.run --stage field_visit
```

**Quality gates:**

```bash
make test
make verify
# or: python scripts/run_all_verifiers.py
```

## Reports index

See [docs/INDEX.md](docs/INDEX.md) for all written outputs.

## Release

Tagged releases: `v1.0` — first packaged SPIS deliverable with multi-site support,
ground AQ cross-check, and one-command reproducibility.
