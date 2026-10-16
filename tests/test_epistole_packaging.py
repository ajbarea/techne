import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from conftest import DOCTOR_LIB, EMAIL, MACHINE_PATH, _load

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "epistole"
DOC = ROOT / "docs" / "epistole.md"
PRIVACY_URL = "https://ajbarea.github.io/techne/epistole/"


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
    plugins = next(entry["Plugins"] for entry in nav if "Plugins" in entry)
    assert {"epistole": "epistole.md"} in plugins


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
    """A file listing three or more plugins' install lines is a list of plugins; a plugin's own
    page carries only its own line."""
    listed = [
        f
        for f in subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "--", "*.md", "*.html"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        if len(re.findall(r"/plugin install \w+@techne", (ROOT / f).read_text())) >= 3
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


RUNTIME = ("mcp", "google-api-python-client", "google-auth", "google-auth-oauthlib")


def _locked(path: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for pkg in tomllib.loads(path.read_text())["package"]:
        out.setdefault(pkg["name"], set()).add(pkg.get("version", ""))
    return out


def test_root_and_plugin_locks_pin_the_same_runtime_versions():
    root, plugin = _locked(ROOT / "uv.lock"), _locked(PLUGIN / "uv.lock")
    assert set(RUNTIME) <= set(plugin) and set(RUNTIME) <= set(root)
    shared = sorted((set(plugin) & set(root)) - {"epistole", "techne"})
    differ = {n: (plugin[n], root[n]) for n in shared if plugin[n] != root[n]}
    assert not differ, f"plugin lock vs root lock: {differ}; re-lock so they match"


def test_dependabot_updates_the_plugin_lock():
    import yaml

    updates = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())["updates"]
    uv = next(u for u in updates if u["package-ecosystem"] == "uv")
    assert {"/", "/plugins/epistole"} <= set(uv.get("directories", [uv.get("directory")]))


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start : nxt if nxt != -1 else None]


def test_send_claim_is_scoped_to_the_tool_with_its_controls_named():
    readme = _section((PLUGIN / "README.md").read_text(), "## Safety")
    privacy = _section(DOC.read_text(), "## Privacy")
    agents = (PLUGIN / "AGENTS.md").read_text()
    for text in (readme, privacy, agents):
        assert "send_draft" in text
        assert "token" in text and "sandbox" in text
        assert "Read(~/.config/epistole/**)" in text
        assert "draft body" in text


def test_attach_dirs_default_is_empty_and_documented():
    readme = (PLUGIN / "README.md").read_text()
    agents = (PLUGIN / "AGENTS.md").read_text()
    example = re.search(r"attach_dirs = \[(.*)\]", readme)
    assert example and "Downloads" not in example.group(1)
    assert "attach_dirs" in agents and "Downloads" in agents
    assert re.search(r"[Aa]sk the user which folder", agents)
    assert re.search(r"empty|none|no folder", _section(readme, "## Safety"))


@pytest.mark.parametrize("script", ["epistole-login", "epistole-since"])
def test_bin_without_uv_names_the_installer(tmp_path, script):
    bash = shutil.which("bash")
    assert bash
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    proc = subprocess.run(
        [bash, str(PLUGIN / "bin" / script), "--status"],
        env={"PATH": str(empty), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 127
    assert _load("epistole_doctor_lib", DOCTOR_LIB).FIXES["uv"].cmd in proc.stderr


@pytest.mark.parametrize("script", ["epistole-login", "epistole-since"])
def test_bin_wrapper_copy_of_the_uv_installer_is_the_fixes_entry(script):
    cmd = _load("epistole_doctor_lib_tie", DOCTOR_LIB).FIXES["uv"].cmd
    assert cmd in (PLUGIN / "bin" / script).read_text()


def test_readme_troubleshoots_a_missing_uv():
    text = _section((PLUGIN / "README.md").read_text(), "## Troubleshooting")
    assert "command -v uv" in text and "/mcp" in text
    assert _load("epistole_doctor_lib_doc", DOCTOR_LIB).FIXES["uv"].cmd in text


def test_agents_step_one_handles_a_missing_accounts_tool():
    step = _section((PLUGIN / "AGENTS.md").read_text(), "## 1. Check where things stand")
    assert "`accounts` tool is not available" in step and "command -v uv" in step


def test_setup_description_names_uv():
    head = (PLUGIN / "skills" / "setup" / "SKILL.md").read_text().split("---")[1]
    assert "uv is missing" in head
