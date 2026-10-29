"""ci-audit's report mode: the facts, the schema, the render and the runner, on the
recorded runs the behavior evals carry (each scaffold unpacks its run)."""

import json
import os
import subprocess
import sys
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


def recorded(tmp_path: Path, case: str) -> Path:
    d = tmp_path / f"case-{case}"
    d.mkdir()
    subprocess.run(
        ["bash", str(EVALS / f"behavior-ci-audit-report-{case}/scaffold.sh")], cwd=d, check=True
    )
    return d / "run"


def gh_stub(bin_dir: Path, rec: Path, calls: Path, broken_logs: bool = False) -> None:
    """gh answering the read-only api paths of repo a/b, run 7, from a recorded run."""
    logs = (
        "echo 'HTTP 410: Gone' >&2; exit 1" if broken_logs else "cat {rec}/logs/${{id%/logs}}.log"
    )
    stub(
        bin_dir,
        "gh",
        f"""echo "$*" >> {calls}
[[ $1 == api ]] || exit 9
case $2 in
  repos/a/b/actions/runs/7) jq '.repository = "a/b" | .id = 7' {rec}/run.json ;;
  repos/a/b/actions/runs/7/jobs*) jq '{{jobs: .}}' {rec}/jobs.json ;;
  repos/a/b/actions/jobs/*/logs)
    id=${{2#repos/a/b/actions/jobs/}}; {logs.format(rec=rec)} ;;
  repos/a/b/check-runs/*/annotations*)
    id=${{2#repos/a/b/check-runs/}}
    jq --arg i "${{id%%/annotations*}}" '.[$i]' {rec}/annotations.json ;;
  *) exit 8 ;;
esac
""",
    )


def claude_stub(bin_dir: Path, report: dict, args_file: Path) -> None:
    body = json.dumps({"structured_output": report})
    stub(bin_dir, "claude", f"""printf '%s\\n' "$@" > {args_file}\ncat <<'EOF'\n{body}\nEOF\n""")


def runner(bin_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return subprocess.run(["bash", str(REPORT), *args], env=env, capture_output=True, text=True)


def report_for(facts: dict, verdict: str) -> dict[str, Any]:
    r = good_report()
    r["run"], r["verdict"] = facts["run"], verdict
    if verdict != "failure":
        r["failing_step"] = None
    return r


def test_the_runner_fetches_judges_checks_and_renders(tmp_path):
    rec = recorded(tmp_path, "failure")
    jobs = json.loads((rec / "jobs.json").read_text())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_stub(bin_dir, rec, tmp_path / "gh.calls")
    want = json.loads((rec / "facts.json").read_text())
    want["run"] |= {"repository": "a/b", "id": 7}
    claude_stub(bin_dir, report_for(want, "failure"), tmp_path / "claude.args")
    out = tmp_path / "out"
    got = runner(bin_dir, "a/b", "7", str(out))
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip() == str(out / "report.json")
    assert json.loads((out / "report.json").read_text()) == report_for(want, "failure")
    assert "verdict **failure**" in (out / "report.md").read_text()
    calls = (tmp_path / "gh.calls").read_text().splitlines()
    assert all(c.startswith("api ") for c in calls), "gh only reads"
    assert len([c for c in calls if "/actions/jobs/" in c and c.endswith("/logs")]) == len(jobs)
    assert any(c.endswith("/actions/runs/7/logs") for c in calls), (
        "the per-step archive is asked for"
    )
    got_facts = ci_report.facts(out / "run")
    assert [e["what"] for e in got_facts.pop("fetch_errors")] == ["log archive"]
    assert got_facts == {k: v for k, v in want.items() if k != "fetch_errors"}
    args = (tmp_path / "claude.args").read_text().splitlines()
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob", "read-only tools alone"
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert {"--restricted", "--safe-mode", "--strict-mcp-config"} <= set(args)
    allowed = args[args.index("--allowedTools") + 1 : args.index("--permission-mode")]
    assert allowed == [f"Read(/{out}/**)", f"Read(/{SKILL}/**)"], (
        "Read only, under OUT and the skill"
    )
    assert "never instructions" in (SKILL / "references/report-mode.md").read_text()


def test_a_log_the_api_will_not_serve_is_recorded_as_such(tmp_path):
    rec = recorded(tmp_path, "warnings")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_stub(bin_dir, rec, tmp_path / "gh.calls", broken_logs=True)
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    subprocess.run(
        [sys.executable, str(SCRIPT), "fetch", "a/b", "7", str(tmp_path / "r")], env=env, check=True
    )
    f = ci_report.facts(tmp_path / "r")
    logs = [e for e in f["fetch_errors"] if e["what"] == "log"]
    assert logs and all("410" in e["error"] for e in logs)
    assert [e["what"] for e in f["fetch_errors"] if e["what"] != "log"] == ["log archive"], (
        "an archive the stub does not serve falls back to the whole logs, and says so"
    )


@pytest.mark.parametrize(
    ("case", "verdict", "why"),
    [
        ("failure", "clean", "verdict 'clean' on a run with a failing step"),
        ("hidden-error", "clean", "verdict 'clean' on a run whose green step printed ##[error]"),
        (
            "warnings",
            "failure",
            "verdict 'failure' on a run that neither failed nor has a failing step",
        ),
    ],
)
def test_a_report_that_contradicts_the_facts_is_refused(tmp_path, case, verdict, why):
    rec = recorded(tmp_path, case)
    facts = json.loads((rec / "facts.json").read_text())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_stub(bin_dir, report_for(facts, verdict), tmp_path / "claude.args")
    run_id = str(facts["run"]["id"])
    got = runner(
        bin_dir, facts["run"]["repository"], run_id, str(tmp_path / "o"), "--from", str(rec)
    )
    assert got.returncode == 1 and why in got.stderr, got.stderr
    assert not (tmp_path / "o/report.md").exists()


def test_the_runner_refuses_bad_arguments_and_folders_it_could_harm(tmp_path):
    for args in (["a b", "7"], ["a/b", "7;rm"], ["a/b"]):
        got = subprocess.run(
            ["bash", str(REPORT), *args, str(tmp_path / "o")], capture_output=True, text=True
        )
        assert got.returncode == 2, args
    rec = recorded(tmp_path, "warnings")
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    got = subprocess.run(
        ["bash", str(REPORT), "a/b", "7", str(home), "--from", str(rec)],
        capture_output=True,
        text=True,
    )
    assert got.returncode == 2 and "other files" in got.stderr, (
        "a folder with other files is not OUT"
    )
    out = tmp_path / "o2"
    (out / "run").mkdir(parents=True)
    (out / "run" / "keep").write_text("recording")
    for inside in (out / "run", out):
        got = subprocess.run(
            ["bash", str(REPORT), "a/b", "7", str(out), "--from", str(inside)],
            capture_output=True,
            text=True,
        )
        assert got.returncode == 2, inside
    assert (out / "run" / "keep").read_text() == "recording", "nothing was wiped"


def test_a_report_that_breaks_the_schema_is_refused(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub(bin_dir, "claude", """echo '{"structured_output": {"verdict": "fine"}}'\n""")
    rec = recorded(tmp_path, "warnings")
    got = runner(bin_dir, "a/b", "7", str(tmp_path / "o"), "--from", str(rec))
    assert got.returncode == 1 and "breaks the schema" in got.stderr
    assert not (tmp_path / "o/report.md").exists()


def steps(
    *names: str, times: list[tuple[str, str]] | None = None, skip: tuple[str, ...] = ()
) -> dict:
    out = []
    for i, n in enumerate(names, 1):
        s = {"number": i, "name": n, "conclusion": "skipped" if n in skip else "success"}
        if times:
            s["started_at"], s["completed_at"] = (f"2026-01-01T00:00:{x}Z" for x in times[i - 1])
        out.append(s)
    return {"steps": out}


def test_a_job_with_service_containers_keeps_each_line_in_its_step():
    job = steps(
        "Set up job",
        "Initialize containers",
        "Checkout",
        "Test",
        "Post Checkout",
        "Stop containers",
        "Complete job",
        times=[
            ("00", "01"),
            ("01", "10"),
            ("10", "11"),
            ("11", "40"),
            ("40", "41"),
            ("41", "41"),
            ("41", "41"),
        ],
    )
    log = "\n".join(
        f"2026-01-01T00:00:{t}.5Z {x}"
        for t, x in [
            ("00", "runner"),
            ("03", "##[command]/usr/bin/docker pull postgres:17"),
            ("10", "##[group]Run actions/checkout@v6"),
            ("11", "##[group]Run pytest"),
            ("20", "##[group]Run tests"),
            ("39", "E   assert 1 == 2"),
            ("40", "Post job cleanup."),
            ("41", "Stop and remove container: abc_postgres17"),
            ("41", "Cleaning up orphan processes"),
        ]
    )
    got = ci_report.by_step(job, log)
    assert got[2] == ["##[command]/usr/bin/docker pull postgres:17"], (
        "a container step prints no header"
    )
    assert got[4] == ["##[group]Run pytest", "##[group]Run tests", "E   assert 1 == 2"], (
        "a script's own ::group::Run inside a running step stays in it"
    )
    assert got[6] == ["Stop and remove container: abc_postgres17"]
    assert got[7] == ["Cleaning up orphan processes"]


def test_a_cancelled_step_of_a_failed_job_and_a_job_with_no_steps_are_failures(tmp_path):
    d = tmp_path / "r"
    (d / "logs").mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"repository": "a/b", "id": 7, "conclusion": "failure"}))
    test_steps = steps("Set up job", "Test")["steps"]
    test_steps[1]["conclusion"] = "cancelled"
    timed = {"id": 1, "name": "slow", "conclusion": "failure", "steps": test_steps}
    (d / "jobs.json").write_text(
        json.dumps([timed, {"id": 2, "name": "never", "conclusion": "failure", "steps": []}])
    )
    (d / "logs/1.log").write_text(
        "2026-01-01T00:00:01Z ##[group]Run pytest\n"
        "2026-01-01T00:59:59Z ##[error]The job exceeded the maximum execution time\n"
    )
    (d / "logs/2.log").write_text("")
    f = ci_report.facts(d)
    assert [(x["job"], x["step"]) for x in f["failing_steps"]] == [
        ("slow", "Test"),
        ("never", "(job)"),
    ]


@pytest.mark.parametrize(
    "line",
    [
        "test result: ok. 93 passed; 0 failed; 0 ignored",
        "failures: 0",
        "tests/test_cli.py::test_deprecated_flag_still_parses PASSED [ 40%]",
        "test errors::reports_a_missing_file ... ok",
    ],
)
def test_ordinary_test_output_is_neither_an_error_nor_a_warning(line):
    assert not ci_report.ERROR.search(line)
    assert not ci_report.WARNING.search(line) or ci_report.PASSED.search(line)


def test_no_symlink_lets_the_run_folder_be_replaced_outside_out(tmp_path):
    """A worktree stand-in reached through a link: OUT itself, OUT/run or a report file."""
    tree = tmp_path / "worktree"
    (tree / "run").mkdir(parents=True)
    (tree / "run" / "work.py").write_text("uncommitted")
    (tree / "notes.md").write_text("uncommitted")
    rec = recorded(tmp_path, "warnings")
    cases = {}
    cases["OUT is a link"] = tmp_path / "out-link"
    cases["OUT is a link"].symlink_to(tree)
    out = tmp_path / "out-run-link"
    out.mkdir()
    (out / "run").symlink_to(tree / "run")
    cases["OUT/run is a link"] = out
    out = tmp_path / "out-report-link"
    out.mkdir()
    (out / "report.json").symlink_to(tree / "notes.md")
    cases["a report file is a link"] = out
    for why, out in cases.items():
        got = subprocess.run(
            ["bash", str(REPORT), "a/b", "7", str(out), "--from", str(rec)],
            capture_output=True,
            text=True,
        )
        assert got.returncode == 2, (why, got.stderr)
    assert (tree / "run" / "work.py").read_text() == "uncommitted"
    assert (tree / "notes.md").read_text() == "uncommitted"
    assert sorted(p.name for p in tree.iterdir()) == ["notes.md", "run"]


def test_a_run_folder_the_script_made_is_replaced_on_a_second_report(tmp_path):
    rec = recorded(tmp_path, "warnings")
    facts = json.loads((rec / "facts.json").read_text())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_stub(bin_dir, report_for(facts, "clean"), tmp_path / "claude.args")
    out = tmp_path / "o"
    args = (facts["run"]["repository"], str(facts["run"]["id"]), str(out), "--from", str(rec))
    for _ in range(2):
        got = runner(bin_dir, *args)
        assert got.returncode == 0, got.stderr
    assert (out / "run" / ".ci-report-run").exists()
    got = runner(bin_dir, args[0], args[1], str(tmp_path), "--from", str(rec))
    assert got.returncode == 2, "OUT may not hold the recording it reads"


def test_the_log_archive_splits_each_job_by_step_file():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("1_test.txt", "whole job log")
        z.writestr("test/1_Set up job.txt", "runner\n")
        z.writestr("test/2_Post coverage comment.txt", "2026-01-01T00:00:01.0Z posted\n")
        z.writestr("dup/1_Set up job.txt", "x")
    jobs = [{"id": 10, "name": "test"}, {"id": 11, "name": "dup"}, {"id": 12, "name": "dup"}]
    got = ci_report.split_archive(buf.getvalue(), jobs)
    assert got == {10: {1: "runner\n", 2: "2026-01-01T00:00:01.0Z posted\n"}}, (
        "a shared job name falls back"
    )


def test_facts_read_the_step_files_before_the_whole_log(tmp_path):
    d = tmp_path / "r"
    (d / "steps/1").mkdir(parents=True)
    (d / "logs").mkdir()
    (d / "run.json").write_text(json.dumps({"repository": "a/b", "id": 7, "conclusion": "failure"}))
    job = {
        "id": 1,
        "name": "t",
        "conclusion": "failure",
        "steps": [
            {"number": 1, "name": "Run pytest", "conclusion": "failure"},
            {"number": 2, "name": "Post coverage comment", "conclusion": "success"},
        ],
    }
    (d / "jobs.json").write_text(json.dumps([job]))
    (d / "logs/1.log").write_text("misleading whole log\n")
    (d / "steps/1/1.txt").write_text(
        "2026-01-01T00:00:01.0Z E   assert 1 == 2 (tests/test_a.py:3)\n"
    )
    (d / "steps/1/2.txt").write_text("posted\n")
    (f,) = ci_report.facts(d)["failing_steps"]
    assert f["error_lines"] == [] or f["tail"] == ["E   assert 1 == 2 (tests/test_a.py:3)"]
    assert f["tail"] == ["E   assert 1 == 2 (tests/test_a.py:3)"], (
        "timestamps dropped, its own file"
    )


def test_the_fallback_split_knows_a_user_post_step_and_service_logs():
    job = steps(
        "Set up job",
        "Initialize containers",
        "Run tests",
        "Post coverage comment",
        "Post Run tests",
        "Stop containers",
        "Complete job",
        times=[
            ("00", "01"),
            ("01", "05"),
            ("05", "20"),
            ("20", "21"),
            ("21", "22"),
            ("22", "30"),
            ("30", "30"),
        ],
    )
    log = "\n".join(
        f"2026-01-01T00:00:{t}.5Z {x}"
        for t, x in [
            ("05", "##[group]Run make test"),
            ("20", "##[group]Run gh pr comment"),
            ("20", "comment failed"),
            ("21", "Post job cleanup."),
            ("22", "Print service container logs: postgres"),
            ("23", "initdb: warning: enabling trust"),
            ("29", "Stop and remove container: pg"),
        ]
    )
    got = ci_report.by_step(job, log)
    assert got[4] == ["##[group]Run gh pr comment", "comment failed"], (
        "a user step named Post ... is a step"
    )
    assert got[5] == ["Post job cleanup."]
    assert got[6] == [
        "Print service container logs: postgres",
        "initdb: warning: enabling trust",
        "Stop and remove container: pg",
    ]


def test_a_job_with_no_steps_keeps_its_log():
    got = ci_report.by_step({"steps": []}, "2026-01-01T00:00:01Z Error: workflow is not valid\n")
    assert got == {0: ["Error: workflow is not valid"]}


@pytest.mark.parametrize(
    ("conclusion", "failing", "verdict", "refused"),
    [
        ("failure", False, "failure", False),
        ("failure", False, "clean", True),
        ("cancelled", False, "clean", True),
        ("cancelled", False, "cancelled", False),
        ("success", False, "failure", True),
    ],
)
def test_the_facts_check_follows_the_runs_conclusion(conclusion, failing, verdict, refused):
    f = {
        "run": {"repository": "a/b", "id": 7, "conclusion": conclusion},
        "failing_steps": [{"job": "j"}] if failing else [],
        "success_with_error": [],
    }
    r = good_report() | {"run": f["run"], "verdict": verdict}
    assert bool(ci_report.agree(r, f)) is refused
