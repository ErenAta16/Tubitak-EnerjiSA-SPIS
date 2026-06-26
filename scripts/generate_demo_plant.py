#!/usr/bin/env python3
"""Generate and write the committed synthetic demo plant snapshot."""

from __future__ import annotations

import logging

from spis.demo_plant import DEMO_PLANT_DIR, generate_demo_plant_artifacts

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    generate_demo_plant_artifacts(output_dir=DEMO_PLANT_DIR)
    readme = DEMO_PLANT_DIR / "README.md"
    readme.write_text(
        """# Synthetic demo plant snapshot

This directory contains **synthetic** daily PV data generated for the public SPIS
Streamlit demo. It contains **no Enerjisa SCADA data** and no real plant identifiers.

Regenerate deterministically (seed=42, 600 days, ~-0.15 %/day clear-sky soiling target):

```bash
python scripts/generate_demo_plant.py
```
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
