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


def test_the_composite_action_keeps_expressions_out_of_its_shell() -> None:
    # An input interpolated into `run:` is shell text a caller controls (zizmor's
    # template-injection); the step reads it from env instead.
    action = (ROOT / ".github/actions/check-action-pins/action.yml").read_text()
    run_lines = [line for line in action.splitlines() if line.strip().startswith("run:")]
    assert run_lines and all("${{" not in line for line in run_lines)


def test_actionlint_runs_from_the_lockfile() -> None:
    # `make actionlint` runs the version uv.lock pins, never whatever uvx fetches that day.
    makefile = (ROOT / "Makefile").read_text()
    recipe = makefile.split("\nactionlint:", 1)[1].split("\n\n", 1)[0]
    assert "uv run actionlint" in recipe and "uvx" not in recipe
    assert 'name = "actionlint-py"' in (ROOT / "uv.lock").read_text()


def test_a_short_sha_is_not_a_pin(tmp_path: Path) -> None:
    wf = "jobs:\n  t:\n    steps:\n      - uses: actions/checkout@3d3c42e\n"
    res = run_check(make_repo(tmp_path, {"ci.yml": wf}))
    assert res.returncode == 1 and "actions/checkout@3d3c42e" in res.stderr


def test_an_empty_directory_argument_is_refused(tmp_path: Path) -> None:
    # Empty must not fall back to the script's own checkout (techne's copy, in the action).
    res = subprocess.run(["bash", str(SCRIPT), ""], capture_output=True, text=True, check=False)
    assert res.returncode == 1 and "empty directory" in res.stderr


def test_the_action_fails_on_a_workspace_with_no_workflows(tmp_path: Path) -> None:
    # No checkout before the step leaves an empty workspace: the action must not pass.
    assert run_check(tmp_path).returncode == 0
    res = run_check(tmp_path, {"PIN_REQUIRE_WORKFLOWS": "1"})
    assert res.returncode == 1 and "actions/checkout" in res.stderr
    action = (ROOT / ".github/actions/check-action-pins/action.yml").read_text()
    assert 'PIN_REQUIRE_WORKFLOWS: "1"' in action
    # techne's own CI runs the action, so a wrong script path fails a real runner.
    validate = (ROOT / ".github/workflows/validate.yml").read_text()
    assert "uses: $/.github/actions/check-action-pins" in validate
    script = action.split("run: bash ")[1].split()[0].strip('"').replace("$GITHUB_ACTION_PATH", "")
    assert (ROOT / ".github/actions/check-action-pins" / script.lstrip("/")).resolve().is_file()
