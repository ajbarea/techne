"""Tests for the periegesis guided product tour skill: each guard its instructions promise."""

from __future__ import annotations

import functools
import http.server
import json
import re
import shlex
import subprocess
import sys
import threading
import tomllib
from pathlib import Path

from test_slides_web import needs_browser

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "techne"
SKILL_MD = PLUGIN_ROOT / "skills" / "periegesis" / "SKILL.md"
DOCS_MD = REPO_ROOT / "docs" / "skills" / "periegesis.md"
TEMPLATE_MD = PLUGIN_ROOT / "skills" / "periegesis" / "templates" / "friction-log.md"


def skill() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def bullet(prefix: str) -> str:
    """The SKILL.md line that starts with PREFIX (after list markers)."""
    for line in skill().splitlines():
        if line.lstrip(" -0123456789.").startswith(prefix):
            return line
    raise AssertionError(f"no line starting {prefix!r}")


def test_log_paths_sit_outside_the_published_docs_folder() -> None:
    """Every place the skill writes is outside the folder the docs site publishes."""
    docs_dir = tomllib.loads((REPO_ROOT / "zensical.toml").read_text()).get("project", {})
    published = str(docs_dir.get("docs_dir", "docs")).rstrip("/") + "/"
    paths = re.findall(r"`([^`\s]*periegesis/[^`\s]*)`", skill())
    assert any(p.startswith(".periegesis/") for p in paths)
    assert any(p.startswith("~/.local/state/periegesis/") for p in paths)
    for p in paths:
        assert p.startswith((".periegesis/", "~/.local/state/periegesis/")), p
        assert not p.lstrip("./").startswith(published), p
    assert "docs/friction" not in TEMPLATE_MD.read_text(encoding="utf-8")


def test_the_log_stays_out_of_git_until_reviewed() -> None:
    """Signed-in screenshots never reach a commit by default."""
    line = bullet("Keep `.periegesis/` out of git")
    assert "`.periegesis/` and `.playwright-mcp/` to `.git/info/exclude`" in line
    assert "then delete `.playwright-mcp/`" in bullet("Close the shared Playwright browser window")
    assert "commit only the reviewed `.md` log" in line
    assert "solo private repo" in line
    assert "Commit `.periegesis/` to git" not in skill()


def test_issues_follow_the_repo_kind_check() -> None:
    """repo_kind.py runs first; solo files unassigned, team files nothing until confirmed."""
    check = bullet("Check repository ownership before filing issues")
    assert '`python3 "<plugin-root>/_shared/repo_kind.py" <target-repo-path>`' in check
    assert (PLUGIN_ROOT / "_shared" / "repo_kind.py").is_file()
    assert "optional" not in check.lower()
    solo = bullet("On a **solo repo**")
    assert "leaving each issue unassigned" in solo
    assert not re.search(r"\bassign(ing|s)? (it|them|the|an?) ", solo)
    assert re.findall(r"--type (\w+)", solo) == ["Bug", "Task", "Feature"]
    team = bullet("On a **team repo**")
    assert "file none until they confirm" in team


def test_machine_findings_name_a_source_for_each_row() -> None:
    """Console errors and load time come from the MCP; visual_qa.py measures neither."""
    text = skill()
    assert "`browser_console_messages`" in text
    assert "performance.getEntriesByType('navigation')" in text
    assert "`report.json`" in text
    script = visual_qa_args("http://x/", "", Path("/t"))[1]
    assert Path(script).is_file(), script


def test_a_missing_playwright_mcp_stops_the_tour() -> None:
    """No unrunnable fallback: without the MCP the skill stops and names the install."""
    line = bullet("Open a shared Playwright browser window")
    assert "stop before the tour" in line
    assert "`playwright` plugin" in line
    assert "python -c" not in skill() and "--with playwright==1.63.0 python -" not in skill()


def test_description_excludes_the_tooling_friction_log() -> None:
    """The trigger must not catch the agents' friction.md."""
    assert "Not for the agents' tooling friction log (friction.md)" in skill()
    assert "Not for the agents' tooling friction log" in DOCS_MD.read_text(encoding="utf-8")


def visual_qa_args(base: str, route: str, tour_dir: Path) -> list[str]:
    """The skill's own visual_qa.py command, placeholders filled, run with this Python."""
    block = re.search(r"```bash\n(.*?visual_qa\.py.*?)\n```", skill(), re.S)
    assert block, "no visual_qa.py command in SKILL.md"
    words = shlex.split(block.group(1).replace("\\\n", " "))
    words = words[words.index("python") + 1 :]
    filled = {
        "<plugin-root>/skills/docs-site/scripts/visual_qa.py": str(
            PLUGIN_ROOT / "skills/docs-site/scripts/visual_qa.py"
        ),
        "<base-url>/": base,
        "<route>": route,
        "<tour-dir>/qa/": str(tour_dir / "qa"),
    }
    return [sys.executable, *(filled.get(w, w) for w in words)]


@needs_browser
def test_the_documented_visual_qa_command_runs_on_an_app_with_no_sitemap(tmp_path) -> None:
    """A plain app (no sitemap.xml, a console.error) gets a report, not a traceback."""
    root = tmp_path / "app"
    root.mkdir()
    (root / "index.html").write_text(
        "<!doctype html><html lang=en><head><title>app</title></head>"
        "<body><main><p>App</p></main><script>console.error('boom')</script></body></html>"
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}/"
        run = subprocess.run(
            visual_qa_args(base, "", tmp_path / "tour"),
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert "Traceback" not in run.stderr, run.stderr
    assert run.returncode in (0, 1), run.stdout + run.stderr
    report = json.loads((tmp_path / "tour" / "qa" / "report.json").read_text())
    assert report, "empty report"
