from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_action_pins.sh"
SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def make_repo(
    tmp_path: Path,
    workflows: dict[str, str],
    templates: dict[str, str] | None = None,
) -> Path:
    repo = tmp_path / "repo"
    wf_dir = repo / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    for name, content in workflows.items():
        (wf_dir / name).write_text(content, encoding="utf-8")
    if templates:
        tpl_dir = repo / ".github-template" / "workflows"
        tpl_dir.mkdir(parents=True, exist_ok=True)
        for name, content in templates.items():
            (tpl_dir / name).write_text(content, encoding="utf-8")
    return repo


def run_check(
    repo: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run(
        ["bash", str(SCRIPT), str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_check_action_pins_success_when_pinned(tmp_path: Path) -> None:
    wf = f"""name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
"""
    repo = make_repo(tmp_path, {"ci.yml": wf})
    res = run_check(repo)
    assert res.returncode == 0
    assert "OK: all GitHub Actions are SHA-pinned" in res.stdout


def test_check_action_pins_fails_on_tag(tmp_path: Path) -> None:
    wf = """name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
    repo = make_repo(tmp_path, {"ci.yml": wf})
    res = run_check(repo)
    assert res.returncode == 1
    assert "actions/checkout@v4 is not pinned to a full commit SHA" in res.stderr


def test_check_action_pins_exemptions(tmp_path: Path) -> None:
    wf = f"""name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
      - uses: ./.github/actions/local-action
      - uses: docker://alpine:latest
      - uses: $/.github/actions/root-action
"""
    repo = make_repo(tmp_path, {"ci.yml": wf})
    res = run_check(repo)
    assert res.returncode == 0
    assert "OK: all GitHub Actions are SHA-pinned" in res.stdout


def test_check_action_pins_no_workflows(tmp_path: Path) -> None:
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    res = run_check(repo)
    assert res.returncode == 0
    assert "OK: no .github/workflows/ to check" in res.stdout


def test_check_action_pins_template_drift(tmp_path: Path) -> None:
    live_wf = f"""name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
"""
    tpl_wf = """name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@0000000000000000000000000000000000000000 # v7.0.0
"""
    repo = make_repo(tmp_path, {"ci.yml": live_wf}, templates={"ci.yml": tpl_wf})
    res = run_check(repo)
    assert res.returncode == 1
    assert "pins differ from" in res.stderr


def test_check_action_pins_github_actions_annotation(tmp_path: Path) -> None:
    wf = """name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
    repo = make_repo(tmp_path, {"ci.yml": wf})
    res = run_check(repo, extra_env={"GITHUB_ACTIONS": "true"})
    assert res.returncode == 1
    expected = (
        "::error file=.github/workflows/ci.yml,line=7::"
        "actions/checkout@v4 is not pinned to a full commit SHA"
    )
    assert expected in res.stderr
