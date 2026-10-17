"""Every plugin is findable: a README, a docs page in the nav, a homepage, and for each setup
skill a runbook and routing evals. Published Markdown carries no personal data."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib

import pytest
from conftest import DOCTOR_LIB, EMAIL, MACHINE_PATH, ROOT, _load

ZENSICAL = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]
SITE = ZENSICAL["site_url"]
LOCAL = sorted(p.parent.parent.name for p in ROOT.glob("plugins/*/.claude-plugin/plugin.json"))
PAGES = {name: f"plugins/{name}.md" for name in LOCAL} | {
    "epistole": "epistole.md",
    "keryx": "plugins/keryx.md",
}
SETUP = sorted(p.parents[2].name for p in ROOT.glob("plugins/*/skills/setup/SKILL.md"))
# epistole's README holds its tools table and safety model, which its privacy page links.
FULL_README = {"epistole"}


def url(page: str) -> str:
    return SITE + page.removesuffix(".md") + "/"


def plugins_section() -> list[dict]:
    names = [next(iter(entry)) for entry in ZENSICAL["nav"]]
    assert names[names.index("Getting Started") + 1] == "Plugins"
    return ZENSICAL["nav"][names.index("Plugins")]["Plugins"]


def test_every_plugin_has_a_readme_and_a_docs_page():
    for name in LOCAL:
        assert (ROOT / "plugins" / name / "README.md").is_file(), name
        assert (ROOT / "docs" / PAGES[name]).is_file(), name
    assert (ROOT / "docs" / PAGES["keryx"]).is_file()


def test_the_plugins_section_lists_every_plugin():
    listed = {k: v for entry in plugins_section() for k, v in entry.items()}
    assert listed == {name: PAGES[name] for name in [*LOCAL, "keryx"]}


@pytest.mark.parametrize("name", LOCAL)
def test_homepage_is_the_docs_page(name):
    manifest = json.loads((ROOT / "plugins" / name / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["homepage"] == url(PAGES[name])


@pytest.mark.parametrize("name", [n for n in LOCAL if n not in FULL_README])
def test_readme_is_a_pointer(name):
    text = (ROOT / "plugins" / name / "README.md").read_text()
    assert f"/plugin install {name}@techne" in text
    assert url(PAGES[name]) in text
    assert len([line for line in text.splitlines() if line.strip()]) <= 20
    assert not re.search(
        r"^## (Set ?up|Troubleshooting|Install)", text, re.MULTILINE | re.IGNORECASE
    )


@pytest.mark.parametrize("name", SETUP)
def test_every_setup_skill_has_a_runbook_and_routing_evals(name):
    plugin = ROOT / "plugins" / name
    assert (plugin / "AGENTS.md").is_file()
    skill = (plugin / "skills" / "setup" / "SKILL.md").read_text()
    assert "${CLAUDE_PLUGIN_ROOT}/AGENTS.md" in skill
    fires = (plugin / "evals" / "fires-setup" / "graders").glob("*.md")
    assert any(f'"{name}:setup"' in g.read_text() for g in fires)
    never = list((plugin / "evals").glob("never-setup-*/graders/*.md"))
    assert any(f'"{name}:setup"' in g.read_text() and "max: 0" in g.read_text() for g in never)


def test_docs_pages_link_agents_md_rather_than_embed_it():
    assert SETUP
    for name in SETUP:
        text = (ROOT / "docs" / PAGES[name]).read_text()
        assert f"/blob/main/plugins/{name}/AGENTS.md" in text, name
        assert "--8<--" not in text, name


def test_install_commands_in_runbooks_and_pages_come_from_the_fixes_table():
    fixes = _load("packaging_doctor_lib", DOCTOR_LIB).FIXES
    known = [v for fix in fixes.values() for v in (fix.apt, fix.brew, fix.cmd) if v]
    files = [*ROOT.glob("plugins/*/AGENTS.md"), *ROOT.glob("docs/plugins/*.md")]
    assert files
    trigger = re.compile(r"apt install|brew install|playwright==|python install|astral\.sh")
    checked = 0
    for f in files:
        for span in re.findall(r"`([^`\n]+)`", f.read_text()):
            command = span.removeprefix("!")
            if trigger.search(command):
                checked += 1
                assert any(command in v for v in known), (f.name, command)
    assert checked


def test_readme_cite_section_matches_citation_cff():
    cff_title = re.search(r'^title:\s*"(.+)"$', (ROOT / "CITATION.cff").read_text(), re.MULTILINE)
    assert cff_title
    readme = (ROOT / "README.md").read_text()
    assert "## Cite" in readme
    assert f"title   = {{{cff_title.group(1)}}}" in readme
    assert "Cite this repository" in readme


def _published_markdown() -> list:
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "--", "plugins", "docs", "README.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [ROOT / f for f in out if f.endswith(".md") and (ROOT / f).is_file()]


def test_no_personal_addresses_or_machine_paths_in_published_markdown():
    files = _published_markdown()
    assert ROOT / "plugins" / "techne" / "AGENTS.md" in files
    for f in files:
        text = f.read_text()
        assert not EMAIL.search(text), f
        assert not MACHINE_PATH.search(text), f


def test_skills_and_agents_address_whoever_installed_them():
    """Shipped instructions and the CLI help they run say "the user", never the maintainer."""
    shipped = [
        *ROOT.glob("plugins/*/skills/*/SKILL.md"),
        *ROOT.glob("plugins/*/agents/*.md"),
        *ROOT.glob("plugins/*/**/*.py"),
        *ROOT.glob("plugins/*/bin/*"),
    ]
    assert shipped
    named = [f.relative_to(ROOT) for f in shipped if re.search(r"\bAJ\b", f.read_text())]
    assert named == []


@pytest.mark.parametrize(
    ("prefix", "form"),
    [
        ("- package_root:", "`{}`"),
        ("- cli_entrypoint:", "`{}@techne`"),
        ("- **Marketplace metadata:**", r"\b{}\b"),
    ],
)
def test_skill_context_plugin_lists_name_every_plugin(prefix, form):
    lines = (ROOT / ".claude" / "skill-context.md").read_text().splitlines()
    (line,) = [x for x in lines if x.startswith(prefix)]
    for name in LOCAL:
        assert re.search(form.format(re.escape(name)), line), (prefix, name)
