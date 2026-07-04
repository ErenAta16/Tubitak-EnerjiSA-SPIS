"""P18 repository hardening verifier: confidentiality greps and artifact policy."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("verifier")

FORBIDDEN_STRINGS: tuple[str, ...] = (
    "11131",
    "2748",
    "11x250",
    "11 x 250",
    "39.86857",
    "26.24152",
)
CANONICAL_SOILING_RATE = -0.1247
CANONICAL_SOILING_CI = (-0.186, -0.064)
EXACT_PLANT_LAT = str(round(39 + 86857 / 100_000, 5))
EXACT_PLANT_LON = str(round(26 + 24152 / 100_000, 5))


def _tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files"], text=True, cwd=ROOT)
    return [ROOT / line for line in output.splitlines() if line.strip()]


def _grep_forbidden_in_tracked() -> list[str]:
    failures: list[str] = []
    skip_names = {"verify_repo_hardening.py", "verify_product_ui.py", "test_config.py"}
    for path in _tracked_files():
        if path.name in skip_names:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for needle in FORBIDDEN_STRINGS:
            if needle in text:
                failures.append(f"{path.relative_to(ROOT)} contains forbidden string {needle!r}")
    return failures


def _check_csv_tracking() -> list[str]:
    failures: list[str] = []
    tracked_csv = [
        line
        for line in subprocess.check_output(["git", "ls-files"], text=True, cwd=ROOT).splitlines()
        if line.endswith(".csv") and line.startswith("reports/")
    ]
    if tracked_csv:
        failures.append(f"Tracked report CSVs remain: {tracked_csv[:5]}")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("reports/figures/*.csv", "reports/*.csv", "!reports/figures/*.png"):
        if pattern not in gitignore:
            failures.append(f".gitignore missing pattern: {pattern}")
    tracked_png = [
        line
        for line in subprocess.check_output(["git", "ls-files"], text=True, cwd=ROOT).splitlines()
        if line.startswith("reports/figures/") and line.endswith(".png")
    ]
    if not tracked_png:
        failures.append("No PNG figures tracked under reports/figures/")
    return failures


def _check_env_hygiene() -> list[str]:
    failures: list[str] = []
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "*.key"):
        if pattern not in gitignore:
            failures.append(f".gitignore missing {pattern}")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("PLANT_LAT=", "PLANT_LON=", "EPTR_USERNAME=", "EPTR_PASSWORD="):
        if key not in example:
            failures.append(f".env.example missing {key}")
    if "39.86857" in example or "26.24152" in example:
        failures.append(".env.example must not contain precise plant coordinates")
    return failures


def _check_coordinate_resolution() -> list[str]:
    failures: list[str] = []
    import importlib

    import spis.config as config_module

    importlib.reload(config_module)
    if config_module.PLANT_COORD_SOURCE != "coarse_default":
        failures.append("Expected coarse_default coordinates without .env override")
    lat_ok = np.isclose(config_module.PLANT_LAT, 39.9)
    lon_ok = np.isclose(config_module.PLANT_LON, 26.2)
    if not lat_ok or not lon_ok:
        failures.append("Coarse default coordinates incorrect")

    env = os.environ.copy()
    env["PLANT_LAT"] = EXACT_PLANT_LAT
    env["PLANT_LON"] = EXACT_PLANT_LON
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib; import spis.config as c; importlib.reload(c); "
            "print(c.PLANT_COORD_SOURCE, c.PLANT_LAT, c.PLANT_LON)",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        failures.append(f"Exact-coordinate subprocess failed: {probe.stderr}")
    else:
        source, lat, lon = probe.stdout.strip().split()
        if source != "env":
            failures.append("PLANT_COORD_SOURCE not env when PLANT_LAT/LON set")
        if lat != EXACT_PLANT_LAT or lon != EXACT_PLANT_LON:
            failures.append("Exact coordinates not resolved from environment")
    return failures


def _check_canonical_soiling_rate() -> list[str]:
    """Soiling rate unchanged when read from existing processed outputs."""
    failures: list[str] = []
    robustness_path = ROOT / "data" / "processed" / "soiling_robustness.parquet"
    if not robustness_path.exists():
        LOGGER.warning("Skipping soiling-rate check: %s not present locally", robustness_path)
        return failures

    from spis.io import read_processed

    robustness = read_processed("soiling_robustness")
    verdict = robustness.loc[robustness["record_type"] == "p4_verdict"].iloc[0]
    rate = float(verdict["recommended_rate_pct_per_day"])
    half = float(verdict["recommended_uncertainty_half_width"])
    ci_lo = rate - half
    ci_hi = rate + half
    if not np.isclose(rate, CANONICAL_SOILING_RATE, rtol=1e-4, atol=1e-4):
        failures.append(f"Canonical soiling rate {rate} != {CANONICAL_SOILING_RATE}")
    if not np.isclose(ci_lo, CANONICAL_SOILING_CI[0], atol=0.002):
        failures.append(f"Canonical CI lower {ci_lo} != {CANONICAL_SOILING_CI[0]}")
    if not np.isclose(ci_hi, CANONICAL_SOILING_CI[1], atol=0.002):
        failures.append(f"Canonical CI upper {ci_hi} != {CANONICAL_SOILING_CI[1]}")
    return failures


def _check_license_files() -> list[str]:
    failures: list[str] = []
    for name in ("LICENSE", "DATA_USE.md"):
        if not (ROOT / name).exists():
            failures.append(f"Missing {name}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "DATA_USE.md" not in readme:
        failures.append("README.md missing DATA_USE.md link")
    return failures


def verify_repo_hardening() -> bool:
    failures: list[str] = []
    failures.extend(_grep_forbidden_in_tracked())
    failures.extend(_check_csv_tracking())
    failures.extend(_check_env_hygiene())
    failures.extend(_check_license_files())
    failures.extend(_check_coordinate_resolution())
    failures.extend(_check_canonical_soiling_rate())

    if failures:
        LOGGER.error("VERIFIER FAIL")
        for item in failures:
            LOGGER.error("- %s", item)
        return False

    LOGGER.info("VERIFIER PASS")
    LOGGER.info("- Forbidden strings absent from tracked files")
    LOGGER.info("- Report CSVs untracked; PNG figures remain tracked")
    LOGGER.info("- LICENSE + DATA_USE.md present; README updated")
    LOGGER.info("- Coordinates: coarse default public; set PLANT_LAT/PLANT_LON in .env locally")
    LOGGER.info(
        "- Canonical soiling rate unchanged at %.4f %%/day when processed data present",
        CANONICAL_SOILING_RATE,
    )
    return True


def main() -> int:
    return 0 if verify_repo_hardening() else 1


if __name__ == "__main__":
    sys.exit(main())
