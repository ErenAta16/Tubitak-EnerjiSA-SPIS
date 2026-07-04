"""Capture public dashboard screenshots from the synthetic Demo Plant."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "screenshots"
PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"
VIEWPORT = {"width": 1440, "height": 900}
STARTUP_TIMEOUT_SECONDS = 120

TAB_NAMES = {
    "overview.png": re.compile(r"^(Overview|Özet)$"),
    "charts.png": re.compile(r"^(Charts|Grafikler)$"),
    "segments.png": re.compile(r"^(Segments|Segmentler)$"),
    "economy.png": re.compile(r"^(Economy|Ekonomi)$"),
}

TAB_READY_SELECTORS = {
    "overview.png": ".js-plotly-plot:visible",
    "charts.png": ".js-plotly-plot:visible",
    "segments.png": "[data-testid='stDataFrame']:visible",
    "economy.png": "[data-testid='stSlider']:visible",
}


def _wait_for_server(process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout is not None else ""
            raise RuntimeError(f"Streamlit exited before startup:\n{output[-4000:]}")
        try:
            with urllib.request.urlopen(f"{BASE_URL}/_stcore/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    raise TimeoutError(f"Streamlit did not become ready at {BASE_URL}")


def _wait_for_demo(page: Page) -> None:
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=STARTUP_TIMEOUT_SECONDS * 1000)
    page.locator("[data-testid='stAppViewContainer']").wait_for(
        state="visible", timeout=STARTUP_TIMEOUT_SECONDS * 1000
    )
    demo_label = page.get_by_text(
        re.compile(r"Demo (Plant|Santral).*(synthetic|sentetik)", re.I)
    ).first
    demo_label.wait_for(state="visible", timeout=STARTUP_TIMEOUT_SECONDS * 1000)
    page.get_by_role("tab", name=TAB_NAMES["overview.png"]).wait_for(
        state="visible", timeout=STARTUP_TIMEOUT_SECONDS * 1000
    )
    page.wait_for_timeout(2500)


def _capture_tabs(page: Page) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, tab_name in TAB_NAMES.items():
        tab = page.get_by_role("tab", name=tab_name)
        tab.click()
        page.locator(TAB_READY_SELECTORS[filename]).first.wait_for(
            state="visible", timeout=STARTUP_TIMEOUT_SECONDS * 1000
        )
        page.evaluate(
            """
            async () => {
                const viewport = document.querySelector('section[data-testid="stMain"]')
                    || document.scrollingElement;
                const height = viewport.scrollHeight;
                for (let y = 0; y <= height; y += 700) {
                    viewport.scrollTo(0, y);
                    await new Promise((resolve) => setTimeout(resolve, 200));
                }
                viewport.scrollTo(0, 0);
            }
            """
        )
        page.wait_for_timeout(1500)
        dynamic_errors = page.get_by_text(
            re.compile(r"Failed to fetch dynamically imported module", re.I)
        )
        if dynamic_errors.count() > 0:
            raise RuntimeError(f"Lazy component loading failed while capturing {filename}")
        if filename != "overview.png":
            page.evaluate(
                """
                () => {
                    const sidebar = document.querySelector('[data-testid="stSidebar"]');
                    if (sidebar) sidebar.style.display = 'none';
                    document.querySelector('[role="tab"][aria-selected="true"]')
                        ?.scrollIntoView({block: 'start'});
                }
                """
            )
            page.wait_for_timeout(500)
        page.screenshot(path=str(OUTPUT_DIR / filename), full_page=False)
        print(f"Captured {OUTPUT_DIR / filename}")


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    env = os.environ.copy()
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(ROOT / "src"), str(ROOT), env.get("PYTHONPATH", "")))
    )
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app/streamlit_app.py",
        "--server.headless=true",
        f"--server.port={PORT}",
        "--server.address=127.0.0.1",
        "--browser.gatherUsageStats=false",
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server(process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
                _wait_for_demo(page)
                _capture_tabs(page)
            finally:
                browser.close()
    finally:
        _stop_process(process)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
