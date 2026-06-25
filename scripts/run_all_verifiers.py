"""Run all SPIS verifier gates sequentially."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verify_all")

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / "scripts").glob("verify_*.py"))


def _load_main(script_path: Path):
    spec = importlib.util.spec_from_file_location(script_path.stem, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def main() -> int:
    failures: list[str] = []
    for script in SCRIPTS:
        if script.name == "verify_all.py":
            continue
        LOGGER.info("Running %s", script.name)
        exit_code = _load_main(script)()
        if exit_code != 0:
            failures.append(script.name)
    if failures:
        LOGGER.error("VERIFIER SUITE FAIL: %s", ", ".join(failures))
        return 1
    LOGGER.info("VERIFIER SUITE PASS (%s scripts)", len(SCRIPTS) - 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
