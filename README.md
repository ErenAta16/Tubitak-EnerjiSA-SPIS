# SPIS — Solar Performance Improvement System

Data-driven soiling analysis, washing-schedule optimization, and multi-site
environmental comparison for Enerjisa hybrid PV plants. TUBITAK 2209-B research
project.

## Data and confidentiality

Raw Enerjisa SCADA and washing logs are **proprietary** and are **not** included in
this public repository. Only methodology, code, and aggregated written reports are
shared for academic purposes. See [DATA_USE.md](DATA_USE.md) for licensing, reuse
rules, and partner-permission notes. Place plant inputs under `data/raw/` locally;
set precise Canakkale coordinates in `.env` (`PLANT_LAT`, `PLANT_LON`).

## Question

How fast does environmental soiling degrade irradiance-normalized PV performance
between washes, and what washing interval minimizes total cost?

## Headline findings (honest)

- **Soiling rate (Canakkale):** clear-sky pooled **-0.125 %/day** (P3.5); modest seasonal
  loss, not driven by daily pollution at grid or ground-station scale.
- **Optimal wash interval T*:** **99 days** at real 2023 EPIAS PTF (assumed wash cost);
  true interval may differ if the reference irradiance sensor co-soils.
- **Pollution vs performance:** daily HAC null with **both CAMS and in-situ ground PM10**
  (P11); CAMS attenuation concern resolved.
- **Balikesir vs Canakkale (CAMS):** PROVISIONAL Balikesir coordinates are **not**
  consistently cleaner than Canakkale in gridded CAMS — proposal premise not supported
  at the placeholder point.
- **Inverters (descriptive):** INV2 ranks lowest vs daily peer median on meaningful-
  irradiance days; not fault diagnosis.
- **ML (P5/P12/P13):** 15-algorithm panel on fair soiling_ratio target; **all blocked
  CV R² negative** — simple physical trend suffices; not used for scheduling.

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
data/examples/      synthetic demo snapshot for public UI (committed)
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

**Full pipeline (one command):**

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
python -m spis.run --stage external_validation
```

**Web UI (Streamlit demo — works without proprietary data):**

```bash
pip install -r requirements-streamlit.txt
streamlit run app/streamlit_app.py
```

The default **Demo Plant (synthetic)** loads from `data/examples/demo_plant/` and drives
soiling, pollution text, PI timeline, and the economic optimizer. Canakkale and DKASC
examples appear only when you have built local `data/processed/` outputs.

## Live demo / Deployment

**Streamlit Community Cloud (recommended, free tier):**

1. Push this repo to GitHub (`main` branch).
2. Open [share.streamlit.io](https://share.streamlit.io), connect the repo.
3. Set **Main file path** to `app/streamlit_app.py`.
4. Set **Python version** to **3.12**.
5. Use **`requirements-streamlit.txt`** as the dependencies file (repo root).
6. Deploy. No secrets required for the synthetic demo.

Live URL placeholder: _add your `.streamlit.app` link after deploy._

Screenshots: add PNGs under `docs/screenshots/` after deployment.

**Hugging Face Spaces:** alternative — create a Streamlit Space, point entry to
`app/streamlit_app.py`, and use the same `requirements-streamlit.txt`.

Keep proprietary Enerjisa files in `data/raw/` locally only; never commit them.

**Quality gates:**

```bash
make test
make verify
# or: python scripts/run_all_verifiers.py
```

## Reports index

See [docs/INDEX.md](docs/INDEX.md) for all written outputs.

## Release

Tagged releases:

- **v1.1** — P11–P13 report alignment: in-situ pollution null, fair ML reframing, and
  15-model algorithm panel (matches current `main` reports).
- **v1.0** — first packaged SPIS deliverable with multi-site support, ground AQ
  cross-check, and one-command reproducibility.
