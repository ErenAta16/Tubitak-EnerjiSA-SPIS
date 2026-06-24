# SPIS — Project Plan

Solar Performance Improvement System. TUBITAK 2209-B. Owner: Eren Ata.
Engine: this repo, driven locally by Cursor; planning/prompts by the project manager.

## What the data actually supports (read first)
- Backbone series: daily production + irradiation, 2023-01-01..2025-10-22, complete.
- Downtime log (88 events) for cleaning. Per-inverter data only from 2025-01-23.
- 7 panel washes (2023-09..2025-03), two methods.
- No Balikesir data yet -> primary track is a within-Canakkale soiling study;
  Balikesir comparison is an optional track if its data is provided.
- Headline scientific result = soiling rate between washes -> economic optimum
  washing interval. Random Forest is the secondary, proposal-required layer.

## Phases (mapped to proposal work packages WP1..WP7)

P0  Repo scaffold, env, config, data contract, CI lint/test.            (enabler)
P1  Ingestion: typed loaders for all four inputs, schema validation.    (WP1)
P2  Cleaning + external enrichment: downtime/curtailment filtering,
    NASA POWER weather pull, temperature-corrected PI series.           (WP1/WP2)
P3  Soiling analysis: inter-wash segmentation, soiling-rate fits,
    washing recovery, season & method comparison.                       (WP3/WP4)
P4  Economic optimization: cost model, optimal washing interval,
    sensitivity sweep on wash cost and electricity price.               (WP4)
P5  ML layer: feature build, time-split Random Forest, GridSearchCV,
    MAE/RMSE/R2, feature importance, comparison to soiling model.       (WP3/WP4)
P6  Inverter-level anomaly detection on 2025 data (underperformers).    (supporting)
P7  Visualization + reporting: figures, tables, reproducible report.    (WP5/WP7)
P8  Field-validation support pack for the site visit.                   (WP6)

Each phase = one branch + one PR into main. Verifier subagent runs before commit.

## Definition of done per phase
Code + unit tests pass, verifier PASS, figures+CSVs in reports/, plan/dictionary
updated, PR merged with professional English commits.
