# Synthetic demo plant snapshot

This directory contains **synthetic** daily PV data generated for the public SPIS
Streamlit demo. It contains **no Enerjisa SCADA data** and no real plant identifiers.

Regenerate deterministically (seed=42, 600 days, ~-0.15 %/day clear-sky soiling target):

```bash
python scripts/generate_demo_plant.py
```
