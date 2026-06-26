# Cursor Prompt Playbook

How to use: paste one prompt per Cursor session/turn, in order. Each prompt is
self-contained and assumes the `.cursor/` rules and skills are installed. After
Cursor finishes a phase and the verifier passes, it commits and opens the PR, then
you move to the next prompt. If anything blocks (missing API key, failed download),
Cursor must stop and tell you exactly what it needs.

Prompts are in English on purpose: the repo, code and commits are English, and the
agent performs more reliably with a single working language. Your conversation with
the project manager stays in Turkish.

--------------------------------------------------------------------------------
## P0 — Bootstrap (run once)
--------------------------------------------------------------------------------

Read .cursor/rules/00-core.mdc and .cursor/skills/input-data-contract.md first.

Set up the project skeleton without touching analysis yet:
1. Create and activate a venv, install requirements.txt, freeze exact versions
   into requirements.lock.
2. Create src/spis/config.py holding: data paths, plant constants from the data
   contract (module temp coeff -0.0035/degC, NOCT 45, ref 25; 11x SG250HX 250kVA;
   feeders EFLATUN, HIPOKRAT; plant coordinates via PLANT_LAT/PLANT_LON in local .env),
   and tunables
   (low-irradiance cutoff, random_state=42). Use pathlib, no hardcoded strings
   elsewhere.
3. Create src/spis/run.py with an argparse CLI exposing --stage
   {ingest,clean,soiling,optimize,ml,report} that dispatches to stage functions
   (stubs for now that raise NotImplementedError with a clear message).
4. Add ruff config (pyproject.toml) and a trivial smoke test in tests/.
5. Confirm the four raw files are present in data/raw/ (list them); if any are
   missing, stop and tell me which.

Then run ruff and pytest, show me the output, and commit on branch `p0-bootstrap`
following .cursor/rules/30-git.mdc. Do not implement stages beyond stubs.

--------------------------------------------------------------------------------
## P1 — Ingestion (WP1)
--------------------------------------------------------------------------------

Read .cursor/rules/10-python.mdc, .cursor/rules/20-methodology.mdc and
.cursor/skills/input-data-contract.md before coding. Branch `p1-ingestion`.

Implement typed loaders in src/spis/ingest.py, one function per raw file, each
returning a validated pandas DataFrame:

- load_irradiance(): read the irradiance/production workbook. Normalize Turkish
  headers to snake_case English (tarih->date, gunluk_total_uretim->production,
  isinim->irradiation, plus the two feeders). Parse date to datetime, coerce
  comma-decimals, assert a complete daily index 2023-01-01..2025-10-22 with zero
  gaps, assert production and irradiation are non-null and >= 0. Compute
  pi = production / irradiation and keep it.
- load_downtime(): read the downtime workbook. Parse start/end datetimes and
  duration hours (comma decimals), keep reason and affected-system categories.
  Expand each event into the set of calendar days it touches (a tidy
  day-per-row table) for later day-level joins.
- load_inverter(): read the inverter sheet. Parse the date, melt INV1..INV11 to
  long form (date, inverter, active_power) plus the meteo irradiance column.
  Drop the all-zero commissioning rows before 2025-01-23 but log how many.
- load_washing(): parse Panel_yikama_tarihleri.txt into rows of
  (event_index_by_date, start, end, method in {brush_solution, robot_no_solution}).
  Order strictly by start date; ignore the printed indices. Add a derived
  segment_id between consecutive washes.

Validation: each loader logs rows in/out and asserts schema (columns, dtypes,
ranges). Write a thin io layer that saves each frame to data/interim/ as Parquet.

Tests: tests/test_ingest.py with tiny synthetic frames per loader asserting shape,
dtypes, the complete-index check, comma-decimal parsing, and the washing date
ordering (including the duplicate "5." label case).

Then invoke the verifier subagent (.cursor/skills/verifier-subagent.md) against
these loaders. Only if it returns PASS, run ruff + pytest, show output, and commit
in small logical commits, then open a PR into main. If verifier FAILS, fix and
re-run before committing.

Produce a one-paragraph summary table of each loaded frame (rows, date span,
null counts) and append it to docs/DATA_DICTIONARY.md.

--------------------------------------------------------------------------------
## P2..P8 — expand on request
--------------------------------------------------------------------------------

These are filled in by the project manager as each prior phase lands, so the
prompts reflect what P1 actually produced. Short spec of each so you know what is
coming:

P2 Cleaning + enrichment: day-level master table; flag downtime/curtailment days;
   pull NASA POWER daily temp/wind/precip for the location (self-serve, no key);
   estimate cell temp (NOCT) and build temperature-corrected PI; mark rain days.
P3 Soiling: segment by wash; robust-fit PI vs days-since-wash per segment; extract
   soiling rate (%/day) and recovery; compare seasons and washing methods.
P4 Optimize: soiling-loss vs washing-cost model; optimal interval; sensitivity
   sweep over wash cost and PTF electricity price (request real values, else sweep).
P5 ML: feature matrix (weather + days-since-wash + season); time-split Random
   Forest + GridSearchCV; MAE/RMSE/R2; feature importance; compare to P3.
P6 Inverter anomaly detection on 2025 data; rank persistent underperformers.
P7 Reporting: publication-grade figures + tables, reproducible report build.
P8 Field-visit support pack (what to inspect, expected vs observed per inverter).
