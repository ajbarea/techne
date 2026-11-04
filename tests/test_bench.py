"""Tests for bench/run.py (hyperfine over the hook cases) and bench/compare.py (the gate)."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import platform
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"bench_{name}", ROOT / "bench" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


compare = _load("compare")


def summary(python: str = "3.14.4", label: str = "ci", instructions: bool = False, **ratios):
    """A bench/run.py summary whose cases have these wall-clock ratios (and, with INSTRUCTIONS,
    the same instruction ratios)."""

    def row(v: float) -> dict:
        r = {"ratio": v, "floor_ms": 10.0, "hook_ms": 10.0 * v}
        return {**r, "instructions_ratio": v} if instructions else r

    return {"label": label, "python": python, "cases": {k: row(v) for k, v in ratios.items()}}


def test_no_case_grew_past_the_threshold():
    code, lines = compare.compare(summary(a=2.0, b=1.0), summary(a=2.2, b=0.9))
    assert code == 0 and not any("SLOWER" in line for line in lines)


@pytest.mark.parametrize(("now", "code"), [(2.5, 0), (2.52, 1)])
def test_wall_growth_at_its_threshold_passes_and_past_it_fails(now, code):
    got, lines = compare.compare(summary(a=2.0), summary(a=now))
    assert got == code
    assert any("wall" in line and ("SLOWER" in line) is bool(code) for line in lines)


@pytest.mark.parametrize(("now", "code"), [(2.1, 0), (2.12, 1)])
def test_instruction_counts_are_checked_when_both_sides_have_them(now, code):
    base = summary(instructions=True, a=2.0)
    new = summary(instructions=True, a=2.0)
    new["cases"]["a"]["instructions_ratio"] = now  # wall time unchanged
    got, lines = compare.compare(base, new)
    assert got == code and any("instructions" in line for line in lines)


def test_wall_time_decides_when_one_side_has_no_counts():
    base = summary(instructions=True, a=2.0)
    got, lines = compare.compare(base, summary(a=2.2))
    assert got == 0 and any(" wall" in line for line in lines)
    assert not any("instructions" in line for line in lines[1:-1])
    assert compare.compare(base, summary(a=2.6))[0] == 1


def test_wall_growth_fails_even_when_instructions_held_still():
    # A hook that now waits (a sleep, a lock, a network call) retires about the same
    # instructions but takes longer; the instruction counts must not hide that.
    base = summary(instructions=True, a=2.0)
    new = summary(instructions=True, a=2.0)
    new["cases"]["a"]["ratio"] = 6.0
    got, lines = compare.compare(base, new)
    assert got == 1
    assert any("wall SLOWER" in line and "+0.0% instructions" in line for line in lines)


def test_a_baseline_case_the_run_did_not_measure_fails():
    code, lines = compare.compare(summary(a=2.0, b=1.0), summary(a=2.0))
    assert code == 1 and any(line.startswith("b ") and "not measured" in line for line in lines)


def test_a_case_without_a_baseline_is_listed_and_passes():
    code, lines = compare.compare(summary(a=2.0), summary(a=2.0, c=9.0))
    assert code == 0 and any(line.startswith("c ") and "no baseline" in line for line in lines)


def test_different_python_minor_versions_cannot_be_compared():
    code, lines = compare.compare(summary("3.12.3", a=2.0), summary("3.14.4", a=2.0))
    assert code == 2 and "3.14" in lines[0]
    assert compare.compare(summary("3.14.0", a=2.0), summary("3.14.4", a=2.0))[0] == 0


def test_a_different_machine_label_is_noted():
    _, lines = compare.compare(summary(label="ci", a=2.0), summary(label="local", a=2.0))
    assert lines[0].startswith("note:")


def test_a_different_cpu_is_noted():
    base, new = summary(a=2.0), summary(a=2.0)
    base["cpu"], new["cpu"] = "AMD EPYC 7763", "AMD EPYC 9V74"
    code, lines = compare.compare(base, new)
    assert code == 0 and any(line.startswith("note:") and "9V74" in line for line in lines)
    assert not any("note:" in line for line in compare.compare(base, base)[1])


def test_cli_exit_code_and_thresholds(tmp_path, capsys):
    base, new = tmp_path / "base.json", tmp_path / "new.json"
    base.write_text(json.dumps(summary(a=2.0)))
    new.write_text(json.dumps(summary(a=3.0)))
    assert compare.main([str(base), str(new)]) == 1
    assert compare.main([str(base), str(new), "--wall-threshold", "1.6"]) == 0
    for flag in ("--threshold", "--wall-threshold"):
        with pytest.raises(SystemExit):
            compare.main([str(base), str(new), flag, "0.9"])
    capsys.readouterr()


FAKE_HYPERFINE = """#!{python}
import json, pathlib, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("hyperfine 2.0.0")
    sys.exit(0)
pathlib.Path({log!r}).open("a").write(json.dumps(args) + "\\n")
out = next(a.split("=", 1)[1] for a in args if a.startswith("--export-json="))
commands = [a for a in args if not a.startswith("--")]
def result(command, seconds, instructions):
    stats = lambda v: {{"median": v, "mean": v, "stddev": v / 100, "min": v, "max": v}}
    return {{"command": command, "measurements": [],
             "summary": {{"time_wall_clock": stats(seconds), "instructions": stats(instructions)}}}}
pathlib.Path(out).write_text(json.dumps({{"schema_version": 2, "results": [
    result(commands[0], 0.010, 1000), result(commands[1], 0.025, 3000)]}}))
"""


def test_run_times_each_case_beside_the_floor_and_writes_the_summary(tmp_path, monkeypatch):
    log = tmp_path / "argv.jsonl"
    fake = tmp_path / "hyperfine"
    fake.write_text(FAKE_HYPERFINE.format(python=sys.executable, log=str(log)))
    fake.chmod(0o755)
    monkeypatch.setenv("HYPERFINE", str(fake))
    run = _load("run")
    out = tmp_path / "summary.json"
    assert run.main(["--out", str(out), "--only", "git_guards-no-git", "--label", "test"]) == 0
    data = json.loads(out.read_text())
    assert data["label"] == "test" and data["hyperfine"] == "2.0.0" and data["runs"] == 30
    row = data["cases"]["git_guards-no-git"]
    assert row == {
        "floor_ms": 10.0,
        "hook_ms": 25.0,
        "ratio": 2.5,
        "hook_stddev_ms": 0.25,
        "instructions_ratio": 3.0,
    }
    (argv,) = map(json.loads, log.read_text().splitlines())
    commands = [a for a in argv if not a.startswith("--")]
    assert (
        len(commands) == 2 and commands[0].endswith("-c pass'") and "git_guards.py" in commands[1]
    )
    assert "--shell=none" in argv and any(a.startswith("--input=") for a in argv)


def test_run_refuses_a_temporary_folder_whose_path_names_git(tmp_path, monkeypatch, capsys):
    # The no-git case's input carries the sandbox path, so under a folder named github the
    # guard would parse it and the bench would time the other path.
    log = tmp_path / "argv.jsonl"
    fake = tmp_path / "hyperfine"
    fake.write_text(FAKE_HYPERFINE.format(python=sys.executable, log=str(log)))
    fake.chmod(0o755)
    monkeypatch.setenv("HYPERFINE", str(fake))
    (tmp_path / "github").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "github"))
    run = _load("run")
    out = tmp_path / "summary.json"
    assert run.main(["--out", str(out), "--only", "git_guards-no-git"]) == 1
    assert "could name git" in capsys.readouterr().err
    assert not log.exists() and not out.exists()


def test_run_refuses_an_unknown_case(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HYPERFINE", "/bin/false")
    run = _load("run")
    with pytest.raises(SystemExit):
        run.main(["--out", str(tmp_path / "x.json"), "--only", "no-such-case"])
    assert "no case named no-such-case" in capsys.readouterr().err


def _fake_hyperfine(tmp_path, monkeypatch, version: str = "2.0.0") -> pathlib.Path:
    log = tmp_path / "argv.jsonl"
    fake = tmp_path / "hyperfine"
    script = FAKE_HYPERFINE.format(python=sys.executable, log=str(log))
    fake.write_text(script.replace('"hyperfine 2.0.0"', repr(f"hyperfine {version}")))
    fake.chmod(0o755)
    monkeypatch.setenv("HYPERFINE", str(fake))
    return log


def test_run_refuses_a_hook_that_does_not_run_as_its_case_expects(tmp_path, monkeypatch, capsys):
    # hyperfine throws away what a command prints, so a hook that fails fast would read as a
    # speed-up; the bench runs the latency test's check first and records nothing.
    log = _fake_hyperfine(tmp_path, monkeypatch)
    run = _load("run")
    monkeypatch.setattr(run.cases, "command", lambda case: "echo broken >&2")
    out = tmp_path / "summary.json"
    assert run.main(["--out", str(out), "--only", "git_guards-no-git"]) == 1
    assert "did not run as its latency case expects" in capsys.readouterr().err
    assert not log.exists() and not out.exists()


def test_run_refuses_a_hyperfine_other_than_2(tmp_path, monkeypatch, capsys):
    log = _fake_hyperfine(tmp_path, monkeypatch, version="1.18.0")
    run = _load("run")
    out = tmp_path / "summary.json"
    assert run.main(["--out", str(out), "--only", "git_guards-no-git"]) == 1
    assert "hyperfine 1.18.0" in capsys.readouterr().err
    assert not log.exists() and not out.exists()


@pytest.mark.parametrize("flags", [["--runs", "1"], ["--runs", "0"], ["--warmup", "-1"]])
def test_run_refuses_too_few_runs(tmp_path, monkeypatch, flags):
    _fake_hyperfine(tmp_path, monkeypatch)
    run = _load("run")
    with pytest.raises(SystemExit):
        run.main(["--out", str(tmp_path / "x.json"), *flags])


@pytest.mark.skipif(
    sys.platform != "linux" or platform.machine() not in ("x86_64", "aarch64"),
    reason="the installer pins Linux x86_64 and aarch64 builds only",
)
def test_installer_refuses_a_download_whose_sha256_differs(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    curl = bindir / "curl"
    # Writes junk where curl's --output points, as a tampered or truncated download would.
    curl.write_text('#!/bin/sh\nwhile [ "$1" != --output ]; do shift; done\necho junk >"$2"\n')
    curl.chmod(0o755)
    cache = tmp_path / "cache"
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts" / "install_hyperfine.sh")],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "XDG_CACHE_HOME": str(cache)},
    )
    assert proc.returncode != 0 and "FAILED" in proc.stderr and not proc.stdout
    assert not list(cache.rglob("hyperfine"))
