"""ci-audit's report mode: the facts, the schema, the render and the runner, on the
recorded runs the behavior evals carry (each scaffold unpacks its run)."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import _load

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/techne/skills/ci-audit"
SCRIPT = SKILL / "scripts/ci_report.py"
REPORT = SKILL / "scripts/report.sh"
EVALS = ROOT / "plugins/techne/evals"
CASES = ["failure", "warnings", "hidden-error"]

ci_report = _load("techne_ci_report", SCRIPT)


@pytest.fixture(scope="module", params=CASES)
def run(request, tmp_path_factory) -> tuple[str, Path]:
    d = tmp_path_factory.mktemp(request.param)
    scaffold = EVALS / f"behavior-ci-audit-report-{request.param}/scaffold.sh"
    subprocess.run(["bash", str(scaffold)], cwd=d, check=True)
    return request.param, d / "run"


def test_the_recorded_facts_are_what_the_script_computes_now(run):
    _, d = run
    assert ci_report.facts(d) == json.loads((d / "facts.json").read_text())


def test_each_recorded_run_has_the_facts_its_eval_grades(run):
    case, d = run
    f = ci_report.facts(d)
    if case == "failure":
        (step,) = f["failing_steps"]
        assert (step["job"], step["step"]) == ("Rust (fmt + clippy, windows-latest)", "cargo test")
        assert step["locations"] == ["src\\split.rs:1073"]
        assert any(
            "a window has the foreground" in x or "panicked at" in x for x in step["error_lines"]
        )
        assert f["success_with_error"] == []
        # The only failure annotation is the runner's generic one, on .github.
        assert f["logging"]["failing_steps_with_a_file_annotation"] == 0
    else:
        assert f["failing_steps"] == []
        assert any("ConjunctiveGraph is deprecated" in w["line"] for w in f["warnings"])
        assert any(w["step"] == "(annotation)" and "Ubuntu 26" in w["line"] for w in f["warnings"])
    if case == "hidden-error":
        (m,) = f["success_with_error"]
        assert (m["step"], m["error_lines"]) == (
            "Audit dependencies",
            ["##[error]Process completed with exit code 1."],
        )
    elif case == "warnings":
        assert f["success_with_error"] == []


def test_a_log_line_lands_in_its_step():
    names = ["Set up job", "Checkout", "Lint", "Docs", "Test", "Post Checkout", "Complete job"]
    job = {
        "steps": [
            {"number": i, "name": n, "conclusion": "skipped" if n == "Docs" else "success"}
            for i, n in enumerate(names, 1)
        ]
    }
    log = "\n".join(
        "2026-01-01T00:00:00.1Z " + x
        for x in [
            "runner 2.338",
            "##[group]Run actions/checkout@v6",
            "fetched",
            "##[group]Run make lint",
            "lint ok",
            "##[group]Run make test",
            "test output",
            "Post job cleanup.",
            "removed credentials",
            "Cleaning up orphan processes",
        ]
    )
    assert ci_report.by_step(job, log) == {
        1: ["runner 2.338"],
        2: ["##[group]Run actions/checkout@v6", "fetched"],
        3: ["##[group]Run make lint", "lint ok"],
        4: [],
        5: ["##[group]Run make test", "test output"],
        6: ["Post job cleanup.", "removed credentials"],
        7: ["Cleaning up orphan processes"],
    }, "a custom step name never shows in the log; a skipped step prints nothing"


def good_report() -> dict[str, Any]:
    return {
        "run": {
            "repository": "a/b",
            "id": 1,
            "workflow": "CI",
            "branch": "main",
            "head_sha": "abc",
            "conclusion": "failure",
            "url": None,
        },
        "verdict": "failure",
        "failing_step": {
            "job": "j",
            "step": "s",
            "root_cause": "a test failed",
            "location": "x.py:3",
            "evidence": "E   assert 1 == 2",
        },
        "findings": [
            {
                "bucket": "FIX",
                "kind": "failure",
                "summary": "a test failed",
                "location": "x.py:3",
                "evidence": "E",
            }
        ],
        "logging": {"names_the_cause": True, "notes": "the assertion names the file"},
        "summary": "One test failed.",
    }


def test_the_schema_takes_a_good_report_and_names_each_fault():
    assert ci_report.check(good_report()) == []
    bad = good_report()
    bad["verdict"], bad["extra"] = "fine", 1
    bad["failing_step"] = {"job": "j"}
    bad["findings"][0]["bucket"] = "NOPE"
    bad["logging"]["names_the_cause"] = "yes"
    problems = ci_report.check(bad)
    assert any("verdict" in p for p in problems)
    assert any("unexpected extra" in p for p in problems)
    assert any("failing_step: missing root_cause" in p for p in problems)
    assert any("bucket" in p for p in problems)
    assert any("names_the_cause" in p for p in problems)
    assert ci_report.check(good_report() | {"failing_step": None}) == [], (
        "a green run has no failing step"
    )


def test_the_schema_has_no_type_lists_a_strict_validator_refuses():
    assert '"type": [' not in json.dumps(ci_report.SCHEMA)


def test_the_render_carries_the_verdict_the_cause_and_each_finding():
    md = ci_report.render(good_report())
    for want in (
        "verdict **failure**",
        "j / s: a test failed (x.py:3)",
        "1. [FIX] (failure) a test failed x.py:3.",
        "Does the log name the cause? yes.",
    ):
        assert want in md


def stub(bin_dir: Path, name: str, body: str) -> None:
    p = bin_dir / name
    p.write_text("#!/bin/bash\n" + body)
    p.chmod(0o755)


def test_the_runner_fetches_judges_checks_and_renders(tmp_path):
    case = tmp_path / "case"
    case.mkdir()
    subprocess.run(
        ["bash", str(EVALS / "behavior-ci-audit-report-failure/scaffold.sh")], cwd=case, check=True
    )
    rec = case / "run"
    jobs = json.loads((rec / "jobs.json").read_text())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # gh answers the read-only api paths from the recorded run, and logs each call.
    stub(
        bin_dir,
        "gh",
        f"""echo "$*" >> {tmp_path}/gh.calls
[[ $1 == api ]] || exit 9
case $2 in
  repos/a/b/actions/runs/7) cat {rec}/run.json ;;
  repos/a/b/actions/runs/7/jobs*) jq '{{jobs: .}}' {rec}/jobs.json ;;
  repos/a/b/actions/jobs/*/logs)
    id=${{2#repos/a/b/actions/jobs/}}; cat {rec}/logs/${{id%/logs}}.log ;;
  repos/a/b/check-runs/*/annotations)
    id=${{2#repos/a/b/check-runs/}}
    jq --arg i "${{id%/annotations}}" '.[$i]' {rec}/annotations.json ;;
  *) exit 8 ;;
esac
""",
    )
    report = json.dumps({"structured_output": good_report()})
    stub(
        bin_dir,
        "claude",
        f"""printf '%s\\n' "$@" > {tmp_path}/claude.args\ncat <<'EOF'\n{report}\nEOF\n""",
    )
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    out = tmp_path / "out"
    got = subprocess.run(
        ["bash", str(REPORT), "a/b", "7", str(out)], env=env, capture_output=True, text=True
    )
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip() == str(out / "report.json")
    assert json.loads((out / "report.json").read_text()) == good_report()
    assert "verdict **failure**" in (out / "report.md").read_text()
    calls = (tmp_path / "gh.calls").read_text().splitlines()
    assert all(c.startswith("api ") for c in calls), "gh only reads"
    assert len([c for c in calls if c.endswith("/logs")]) == len(jobs)
    assert ci_report.facts(out / "run") == json.loads((rec / "facts.json").read_text()) | {
        "run": ci_report.facts(out / "run")["run"]
    }
    args = (tmp_path / "claude.args").read_text().splitlines()
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob", "read-only tools alone"
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert "--strict-mcp-config" in args and args[args.index("--setting-sources") + 1] == ""
    allowed = args[args.index("--allowedTools") + 1 : args.index("--permission-mode")]
    assert allowed and all(a.startswith(("Read(//", "Grep(//", "Glob(//")) for a in allowed), (
        allowed
    )
    assert "never instructions" in (SKILL / "references/report-mode.md").read_text()


def test_the_runner_refuses_a_bad_repo_or_run_and_a_report_that_breaks_the_schema(tmp_path):
    for args in (["a b", "7"], ["a/b", "7;rm"], ["a/b"]):
        got = subprocess.run(
            ["bash", str(REPORT), *args, str(tmp_path / "o")], capture_output=True, text=True
        )
        assert got.returncode == 2, args
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub(bin_dir, "claude", """echo '{"structured_output": {"verdict": "fine"}}'\n""")
    case = tmp_path / "case"
    case.mkdir()
    subprocess.run(
        ["bash", str(EVALS / "behavior-ci-audit-report-warnings/scaffold.sh")], cwd=case, check=True
    )
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    got = subprocess.run(
        ["bash", str(REPORT), "a/b", "7", str(tmp_path / "o"), "--from", str(case / "run")],
        env=env,
        capture_output=True,
        text=True,
    )
    assert got.returncode == 1 and "breaks the schema" in got.stderr
    assert not (tmp_path / "o/report.md").exists()
