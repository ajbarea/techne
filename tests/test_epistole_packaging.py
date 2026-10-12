import json
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "epistole"
DOC = ROOT / "docs" / "epistole.md"
PRIVACY_URL = "https://ajbarea.github.io/techne/epistole/"

EMAIL = re.compile(
    r"[\w.+-]+@(?!(?:[\w-]+\.)*example\.(?:com|edu|org)(?![\w-]*\.\w))[\w-]+\.[\w.]+"
)
MACHINE_PATH = re.compile(r"/(?:home|mnt|Users)/|[A-Za-z]:\\Users")


def _published_files() -> list[Path]:
    """Tracked and not-yet-tracked (not ignored) files of the plugin, plus its docs page."""
    out = subprocess.run(
        [
            "git",
            "ls-files",
            "-co",
            "--exclude-standard",
            "--",
            "plugins/epistole",
            "docs/epistole.md",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [ROOT / name for name in out if (ROOT / name).is_file()]


def _scanned_files() -> list[Path]:
    """The plugin, plus the shared files and docs pages that mention it."""
    extra = [ROOT / n for n in ("README.md", "ROADMAP.md", "CITATION.cff", "IMPL.md")]
    return _published_files() + extra + sorted((ROOT / "docs").rglob("*.md"))


def test_root_group_matches_plugin_deps():
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())
    plugin = tomllib.loads((PLUGIN / "pyproject.toml").read_text())
    assert root["dependency-groups"]["epistole"] == plugin["project"]["dependencies"]


def test_mcp_json_runs_the_server_from_plugin_data():
    spec = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]["epistole"]
    assert spec["command"] == "uv"
    assert "${CLAUDE_PLUGIN_ROOT}" in spec["args"] and "epistole.server" in spec["args"]
    assert spec["env"]["UV_PROJECT_ENVIRONMENT"].startswith("${CLAUDE_PLUGIN_DATA}")


def test_marketplace_lists_epistole_matching_its_manifest():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    entry = next(p for p in market["plugins"] if p["name"] == "epistole")
    assert entry["source"] == "./plugins/epistole"
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "epistole"
    assert entry["description"] == manifest["description"]


def test_docs_page_exists_with_privacy_heading():
    text = DOC.read_text()
    assert re.search(r"^#{2,3} Privacy\s*$", text, re.MULTILINE)
    assert "~/.config/epistole" in text


def test_docs_page_is_in_the_nav():
    nav = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["nav"]
    assert {"epistole": "epistole.md"} in nav


def test_privacy_url_matches_the_site_layout():
    site = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["site_url"]
    assert site + "epistole/" == PRIVACY_URL


def test_every_plugin_list_mentions_epistole():
    for name in (
        "README.md",
        "IMPL.md",
        "docs/index.md",
        "docs/getting-started.md",
        "docs/skills/index.md",
        "docs/architecture.md",
        "docs/configuration.md",
        ".claude/skill-context.md",
    ):
        assert "epistole" in (ROOT / name).read_text(), name


def test_every_install_list_has_the_epistole_line():
    listed = [
        f
        for f in subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "--", "*.md", "*.html"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        if "/plugin install dokimasia@techne" in (ROOT / f).read_text()
    ]
    assert {"README.md", "docs/index.md", "docs/getting-started.md"} <= set(listed)
    for name in listed:
        assert "/plugin install epistole@techne" in (ROOT / name).read_text(), name


def test_guard_patterns_catch_what_they_should():
    for bad in (
        "me@gmail.com",
        "a@example.com.evil.io",
        "a@example.edu.evil.io",
        "a@notexample.com",
        "/home/x",
        "/mnt/c/x",
        "/Users/x",
        "C:\\Users\\x",
    ):
        assert EMAIL.search(bad) or MACHINE_PATH.search(bad), bad
    for ok in ("user@example.com", "user@g.example.edu", "x@mail.example.org."):
        assert not EMAIL.search(ok), ok


def test_no_personal_addresses_or_machine_paths_in_published_files():
    files = _published_files()
    assert DOC in files and (PLUGIN / "README.md") in files
    for f in _scanned_files():
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        assert not EMAIL.search(text), f
        assert not MACHINE_PATH.search(text), f
