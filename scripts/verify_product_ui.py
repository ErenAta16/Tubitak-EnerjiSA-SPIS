"""P19 product UI verifier: demo data, upload analysis, confidentiality."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")


def _tracked_under_data() -> list[str]:
    return [
        line
        for line in subprocess.check_output(
            ["git", "ls-files", "data/"], text=True, cwd=ROOT
        ).splitlines()
        if line.strip()
    ]


def verify_product_ui() -> bool:
    failures: list[str] = []

    tracked = _tracked_under_data()
    allowed_example_prefixes = (
        "data/examples/demo_plant/",
        "data/examples/pvdaq_2107/",
        "data/examples/dkasc/",
    )
    if not tracked:
        failures.append("No tracked files under data/; demo snapshot missing")
    elif not all(
        line.startswith(allowed_example_prefixes) or line.endswith(".gitkeep") for line in tracked
    ):
        failures.append(f"Unexpected tracked data paths: {tracked}")
    for prefix in allowed_example_prefixes:
        if not any(line.startswith(prefix) for line in tracked):
            failures.append(f"Expected tracked public example missing: {prefix}")

    forbidden_prefixes = ("data/raw/", "data/processed/", "data/interim/", "data/external/")
    for line in tracked:
        if line.endswith(".gitkeep"):
            continue
        if any(line.startswith(prefix) for prefix in forbidden_prefixes):
            failures.append(f"Proprietary data path tracked: {line}")

    req = (ROOT / "requirements-streamlit.txt").read_text(encoding="utf-8")
    for package in ("streamlit", "statsmodels", "matplotlib", "plotly", "pyarrow"):
        if package not in req:
            failures.append(f"requirements-streamlit.txt missing {package}")

    if not (ROOT / ".streamlit" / "config.toml").exists():
        failures.append(".streamlit/config.toml missing")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "Streamlit Community Cloud" not in readme:
        failures.append("README missing Streamlit deployment section")

    try:
        from spis.demo_plant import demo_data_available, load_demo_headline_metrics
        from spis.public_examples import (
            PUBLIC_EXAMPLE_KEYS,
            load_public_headline_metrics,
            public_example_available,
        )

        if not demo_data_available():
            failures.append("Synthetic demo snapshot not present")
        else:
            metrics = load_demo_headline_metrics()
            if metrics["clear_sky_rate_pct_per_day"] is None:
                failures.append("Demo headline soiling rate missing")
        for site_key in PUBLIC_EXAMPLE_KEYS:
            if not public_example_available(site_key):
                failures.append(f"Public example snapshot not present: {site_key}")
                continue
            public = load_public_headline_metrics(site_key)
            master = public["master"]
            forbidden = {"enerjisa", "canakkale", "çanakkale", "latitude", "longitude"}
            columns = {str(column).lower() for column in master.columns}
            if columns & forbidden:
                failures.append(f"Forbidden public-example fields in {site_key}: {columns}")
            text = " ".join(
                master.select_dtypes(include=["object", "string"])
                .fillna("")
                .astype(str)
                .to_numpy()
                .ravel()
            ).lower()
            if any(token in text for token in forbidden):
                failures.append(f"Forbidden public-example values in {site_key}")
    except Exception as exc:
        failures.append(f"Example snapshot load failed: {exc}")

    streamlit_src = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    if "list_downloadable_figures" in streamlit_src:
        failures.append("streamlit_app still references list_downloadable_figures")
    if "reports/figures" in streamlit_src:
        failures.append("streamlit_app references reports/figures downloads")
    if 'UI_BUILD = "2026-07-05-p24-real-site-demo"' not in streamlit_src:
        failures.append("UI_BUILD tag not bumped to p24-real-site-demo")

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Only approved synthetic/public example data tracked under data/")
    LOGGER.info("- requirements-streamlit.txt and Streamlit config present")
    LOGGER.info("- Public app exposes no reports/figures PNG downloads")
    return True


def main() -> int:
    return 0 if verify_product_ui() else 1


if __name__ == "__main__":
    sys.exit(main())
