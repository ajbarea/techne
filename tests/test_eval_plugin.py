"""scripts/eval-plugin.sh: the eval-only plugin each plugin's routing cases load."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "eval-plugin.sh"


def make_plugin(root: pathlib.Path, name: str, body: str, evals=True, rival=False):
    plugin = root / "plugins" / name
    (plugin / "skills" / "setup").mkdir(parents=True)
    (plugin / "skills" / "setup" / "SKILL.md").write_text(body)
    if evals:
        (plugin / "evals" / "case").mkdir(parents=True)
    if rival:
        skill = plugin / "eval-fixtures" / "rival-skills" / "skills" / "rival"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("rival")
    return plugin


def run_harness(root: pathlib.Path) -> None:
    (root / "scripts").mkdir()
    shutil.copy(SCRIPT, root / "scripts" / "eval-plugin.sh")
    subprocess.run(
        ["bash", str(root / "scripts" / "eval-plugin.sh")], check=True, capture_output=True
    )


def built(root: pathlib.Path, name: str) -> pathlib.Path:
    return root / "plugins" / name / "eval-fixtures" / "with-rivals"


def test_host_plugin_skill_wins_a_name_clash(tmp_path):
    for name in ("alpha", "beta", "gamma"):
        make_plugin(tmp_path, name, f"{name} setup", rival=True)
    run_harness(tmp_path)
    for name in ("alpha", "beta", "gamma"):
        skill = built(tmp_path, name) / "skills" / "setup" / "SKILL.md"
        assert skill.read_text() == f"{name} setup"


def test_a_plugin_with_evals_and_no_rivals_gets_an_eval_plugin(tmp_path):
    make_plugin(tmp_path, "solo", "solo setup")
    make_plugin(tmp_path, "other", "other setup", evals=False, rival=True)
    run_harness(tmp_path)
    out = built(tmp_path, "solo")
    assert json.loads((out / ".claude-plugin" / "plugin.json").read_text())["name"] == "solo"
    assert (out / "skills" / "rival" / "SKILL.md").exists()
    assert (out / "skills" / "setup" / "SKILL.md").read_text() == "solo setup"
    assert not built(tmp_path, "other").exists()
