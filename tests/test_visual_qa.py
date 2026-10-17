"""docs-site's visual_qa.py against two static pages in a real Chromium: one clean, one with
low-contrast text and a block wider than a phone. Shares the browser guard with
test_slides_web.py: a machine without Playwright's Chromium sets TECHNE_NO_BROWSER=1."""

from __future__ import annotations

import functools
import http.server
import json
import pathlib
import subprocess
import sys
import threading

import pytest
from test_slides_web import needs_browser

SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "plugins/techne/skills/docs-site/scripts/visual_qa.py"
)
PAGE = (
    "<!doctype html><html lang=en><head>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>{0}<title>t</title>"
    "</head><body><main>{1}</main></body></html>"
)
CLEAN = PAGE.format("", "<p style='color:#000;background:#fff'>Readable</p>")
BROKEN = PAGE.format(
    "<meta property='og:title' content='a'><meta name='og:title' content='b'>",
    "<p style='color:#ccc;background:#fff'>Faint</p><div style='width:1000px;height:30px'></div>",
)

PATHS = ["--path", "clean.html", "--path", "broken.html"]


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "clean.html").write_text(CLEAN)
    (root / "broken.html").write_text(BROKEN)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@needs_browser
def test_visual_qa_flags_the_broken_page_only(site, tmp_path):
    out = tmp_path / "qa"
    run = subprocess.run(
        [sys.executable, str(SCRIPT), site, "--out", str(out), *PATHS],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 1, run.stdout + run.stderr
    report = json.loads((out / "report.json").read_text())
    for device in ("wide", "desktop", "phone"):
        clean, broken = report[f"clean.html light {device}"], report[f"broken.html light {device}"]
        assert clean["contrastCount"] == 0 and clean["overflow"] <= 1
        assert broken["contrastCount"] >= 1, "the bundled axe-core did not run"
        assert clean["duplicateMeta"] == [] and broken["duplicateMeta"] == ["og:title"]
    assert report["broken.html light phone"]["overflow"] > 1
    assert (out / "broken.html-sheet.png").exists()
