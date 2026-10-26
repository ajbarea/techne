"""scripts/check_plugin_refs.sh: path resolution and where plugin variables may appear."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import ROOT

SCRIPT = ROOT / "scripts" / "check_plugin_refs.sh"


def run(root: Path) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "PLUGINS_ROOT": str(root)}
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.mark.parametrize("rel", ["plugins/p/agents/a.md", "plugins/p/commands/c.md"])
def test_variables_allowed_in_substituted_bodies(tmp_path: Path, rel: str):
    write(tmp_path, "plugins/p/x.py", "")
    write(tmp_path, rel, "run ${CLAUDE_SKILL_DIR}/x.py and ${CLAUDE_PLUGIN_ROOT}/x.py\n")
    assert run(tmp_path).returncode == 0


@pytest.mark.parametrize("var", ["CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "CLAUDE_SKILL_DIR"])
def test_variable_in_reference_file_fails(tmp_path: Path, var: str):
    write(tmp_path, "plugins/p/skills/s/references/r.md", f"python ${{{var}}}\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert f"FAIL: plugins/p/skills/s/references/r.md uses ${{{var}}}" in result.stderr
    assert "only in SKILL.md, agent and command bodies" in result.stderr


def test_eval_fixtures_are_excluded(tmp_path: Path):
    write(tmp_path, "plugins/p/skills/s/eval-fixtures/f.md", "${CLAUDE_SKILL_DIR}\n")
    assert run(tmp_path).returncode == 0


def test_repo_is_clean():
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr


SKILL = "plugins/p/skills/s/SKILL.md"
SKILL_DEF = "`<skill-dir>` is the directory holding this SKILL.md.\n"
ROOT_DEF = (
    "`<plugin-root>` is the plugin's root directory, two levels above the directory holding"
    " this SKILL.md.\n"
)


@pytest.mark.parametrize("var", ["CLAUDE_SKILL_DIR", "CLAUDE_PLUGIN_ROOT"])
def test_claude_variable_in_skill_body_fails(tmp_path: Path, var: str):
    write(tmp_path, "plugins/p/skills/s/x.py", "")
    write(tmp_path, "plugins/p/x.py", "")
    write(tmp_path, SKILL, f"run ${{{var}}}/x.py\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert f"FAIL: {SKILL} uses ${{{var}}}, which only Claude Code substitutes" in result.stderr


@pytest.mark.parametrize("marker", ["${user_config.repo}", "${CLAUDE_PLUGIN_DATA}/venv"])
def test_skill_reading_plugin_options_keeps_its_variables(tmp_path: Path, marker: str):
    write(tmp_path, "plugins/p/x.py", "")
    write(tmp_path, SKILL, f"run ${{CLAUDE_PLUGIN_ROOT}}/x.py {marker}\n")
    assert run(tmp_path).returncode == 0


def test_placeholders_resolve_against_skill_and_plugin(tmp_path: Path):
    write(tmp_path, "plugins/p/skills/s/scripts/run.py", "")
    write(tmp_path, "plugins/p/_shared/prose.md", "")
    body = (
        SKILL_DEF
        + ROOT_DEF
        + "python <skill-dir>/scripts/run.py; read <plugin-root>/_shared/prose.md.\n"
    )
    write(tmp_path, SKILL, body)
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("ref", "missing"),
    [
        ("<skill-dir>/scripts/gone.py", "<skill-dir>/scripts/gone.py"),
        ("<plugin-root>/_shared/gone.md", "<plugin-root>/_shared/gone.md"),
    ],
)
def test_placeholder_path_must_ship(tmp_path: Path, ref: str, missing: str):
    write(tmp_path, SKILL, SKILL_DEF + ROOT_DEF + f"run {ref}\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert f"FAIL: {SKILL} names {missing}, which plugins/p does not ship" in result.stderr


def test_skill_dir_resolves_from_its_own_skill(tmp_path: Path):
    """A script in a sibling skill does not satisfy <skill-dir>."""
    write(tmp_path, "plugins/p/skills/other/scripts/run.py", "")
    write(tmp_path, SKILL, SKILL_DEF + "python <skill-dir>/scripts/run.py\n")
    assert run(tmp_path).returncode == 1


@pytest.mark.parametrize(
    ("name", "definition"), [("skill-dir", ROOT_DEF), ("plugin-root", SKILL_DEF)]
)
def test_placeholder_needs_its_definition(tmp_path: Path, name: str, definition: str):
    write(tmp_path, SKILL, definition + f"look in <{name}>\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert f"FAIL: {SKILL} uses <{name}> without defining it" in result.stderr


def test_placeholder_outside_skill_md_fails(tmp_path: Path):
    write(tmp_path, "plugins/p/x.py", "")
    write(tmp_path, "plugins/p/skills/s/references/r.md", "run <plugin-root>/x.py\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert "references/r.md uses <skill-dir> or <plugin-root>, which only a SKILL.md defines" in (
        result.stderr
    )


def test_definition_must_come_before_first_use(tmp_path: Path):
    write(tmp_path, "plugins/p/x.py", "")
    write(tmp_path, SKILL, "# S\n\nrun <plugin-root>/x.py\n\n" + ROOT_DEF)
    result = run(tmp_path)
    assert result.returncode == 1
    assert "uses <plugin-root> on line 3, before its definition on line 5" in result.stderr


def test_portable_plugin_may_not_read_plugin_options(tmp_path: Path):
    skill = "plugins/graphe/skills/s/SKILL.md"
    write(tmp_path, skill, "key ${user_config.key}\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert f"FAIL: {skill} reads plugin options or plugin data, which graphe must not need" in (
        result.stderr
    )


def test_unbraced_claude_variable_fails(tmp_path: Path):
    write(tmp_path, "plugins/p/skills/s/x.py", "")
    write(tmp_path, SKILL, "run $CLAUDE_SKILL_DIR/x.py\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert "uses $CLAUDE_SKILL_DIR, which only Claude Code substitutes" in result.stderr


def test_placeholder_path_may_not_climb_out(tmp_path: Path):
    write(tmp_path, "plugins/other/x.py", "")
    write(tmp_path, SKILL, ROOT_DEF + "run <plugin-root>/../other/x.py\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert (
        "names <plugin-root>/../other/x.py, which climbs out of the path it names" in result.stderr
    )


def test_trailing_dots_after_a_path_are_prose(tmp_path: Path):
    write(tmp_path, "plugins/p/skills/s/x.py", "")
    write(tmp_path, SKILL, SKILL_DEF + "Run <skill-dir>/x.py... then stop.\n")
    assert run(tmp_path).returncode == 0


def test_definition_must_match_exactly(tmp_path: Path):
    write(tmp_path, "plugins/p/skills/s/x.py", "")
    wrong = "`<skill-dir>` is the directory holding this SKILL.md's parent plugin.\n"
    write(tmp_path, SKILL, wrong + "run <skill-dir>/x.py\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert f"FAIL: {SKILL} uses <skill-dir> without defining it" in result.stderr


@pytest.mark.parametrize("marker", ["$CLAUDE_PLUGIN_DATA/venv", "${CLAUDE_PLUGIN_DATA:-/tmp}"])
def test_portable_plugin_may_not_read_plugin_data_in_any_spelling(tmp_path: Path, marker: str):
    skill = "plugins/graphe/skills/s/SKILL.md"
    write(tmp_path, skill, f"venv {marker}\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert "reads plugin options or plugin data, which graphe must not need" in result.stderr
