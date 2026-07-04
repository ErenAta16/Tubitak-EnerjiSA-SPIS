# SPIS — Project Plan

Solar Performance Improvement System. TUBITAK 2209-B. Owner: Eren Ata.
The repository contains the reproducible analysis pipeline, validation checks, reports,
and public Streamlit product.

## What the data actually supports (read first)
- Backbone series: daily production + irradiation, 2023-01-01..2025-10-22, complete.
- Downtime log (88 events) for cleaning. Per-inverter data only from 2025-01-23.
- 7 panel washes (2023-09..2025-03), two methods.
- No Balikesir data yet -> primary track is a within-Canakkale soiling study;
  Balikesir comparison is an optional track if its data is provided.
- Headline scientific result = soiling rate between washes -> economic optimum
  washing interval. Random Forest is the secondary, proposal-required layer.

## Engineering work packages

| Work package | Scope | Proposal alignment |
|---|---|---|
| Platform foundation | Repository structure, configuration, data contract, linting and tests | Enabler |
| Data ingestion | Typed loaders for the four plant inputs and schema validation | WP1 |
| Cleaning and enrichment | Downtime/curtailment filtering, NASA POWER weather, temperature-corrected PI | WP1/WP2 |
| Soiling analysis | Inter-wash segmentation, robust soiling-rate fits, washing recovery and seasonal comparison | WP3/WP4 |
| Washing economics | Cost model, optimal interval and wash-cost/electricity-price sensitivity | WP4 |
| Machine learning | Leakage-controlled features, blocked time-series validation and physical-baseline comparison | WP3/WP4 |
| Inverter screening | Descriptive peer-relative performance ranking on the available inverter window | Supporting |
| Reporting and product | Reproducible figures, written reports and the Streamlit dashboard | WP5/WP7 |
| Field validation | Site-visit checklist and reference-sensor inspection guidance | WP6 |

## Definition of done

Code, unit tests and verifier checks pass; generated artifacts are reproducible;
methodology and data documentation are updated; and public outputs contain no
proprietary plant data.
