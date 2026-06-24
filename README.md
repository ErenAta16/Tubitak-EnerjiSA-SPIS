# SPIS — Solar Performance Improvement System

Data-driven soiling analysis and dynamic panel-washing schedule for the Canakkale
Hybrid PV power plant. TUBITAK 2209-B research project, in cooperation with
Enerjisa Uretim.

## Question
How fast does environmental soiling degrade irradiance-normalized PV performance
between washes, and what washing interval minimizes total cost?

## Layout
    .cursor/        agent rules and skills
    src/spis/       library code (loaders, cleaning, models)
    data/raw/       read-only inputs (not committed)
    data/external/  cached API pulls (not committed)
    data/processed/ final tables, Parquet (not committed)
    reports/        figures and the written report
    tests/          unit tests
    docs/           project plan, data dictionary, prompt playbook

## Setup
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

## Pipeline
    python -m spis.run --stage ingest
    python -m spis.run --stage clean
    python -m spis.run --stage soiling
    python -m spis.run --stage optimize
    python -m spis.run --stage ml
    python -m spis.run --stage report
