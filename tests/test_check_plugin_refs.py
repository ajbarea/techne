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


@pytest.mark.parametrize(
    "rel",
    ["plugins/p/skills/s/SKILL.md", "plugins/p/agents/a.md", "plugins/p/commands/c.md"],
)
def test_variables_allowed_in_substituted_bodies(tmp_path: Path, rel: str):
    write(tmp_path, "plugins/p/x.py", "")
    write(tmp_path, rel, "run ${CLAUDE_SKILL_DIR}/x.py and ${CLAUDE_PLUGIN_ROOT}/x.py\n")
    assert run(tmp_path).returncode == 0


@pytest.mark.parametrize("var", ["CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "CLAUDE_SKILL_DIR"])
def test_variable_in_reference_file_fails(tmp_path: Path, var: str):
    write(tmp_path, "plugins/p/skills/s/references/r.md", f"python ${{{var}}}\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert f"FAIL: plugins/p/skills/s/references/r.md uses ${{{var}}}" in result.stdout
    assert "only in SKILL.md, agent and command bodies" in result.stdout


def test_eval_fixtures_are_excluded(tmp_path: Path):
    write(tmp_path, "plugins/p/skills/s/eval-fixtures/f.md", "${CLAUDE_SKILL_DIR}\n")
    assert run(tmp_path).returncode == 0


def test_repo_is_clean():
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout
