"""The gold runner, driven with a fake claude on PATH."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import GOLD_RUNNER, ROOT, _load

FAKE = ROOT / "tests" / "fixtures" / "heuresis" / "fake_claude.py"
CASES = ROOT / "tests" / "fixtures" / "heuresis" / "gold_cases.yaml"
r = _load("heuresis_gold", GOLD_RUNNER)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "claude"
    shim.write_text(f'#!/bin/sh\nexec {sys.executable} {FAKE} "$@"\n')
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HEURESIS_SRC", str(ROOT / "plugins" / "heuresis"))
    return tmp_path


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def guard_repo(tmp: Path) -> Path:
    repo = tmp / "real-ideas"
    (repo / "ideas").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def dirty_guard_repo(tmp: Path) -> Path:
    """A guard with a commit, an already-modified tracked file and an existing untracked file."""
    repo = guard_repo(tmp)
    (repo / "tracked.md").write_text("A" * 20)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    (repo / "tracked.md").write_text("C" * 20)
    (repo / "untracked.md").write_text("A" * 20)
    return repo


def go(out: Path, *flags: str, case: tuple[str, ...] = ("bib-checker",), runs: int = 1) -> int:
    """Run the gold runner against the fixture cases; flags go last."""
    picks = [x for c in case for x in ("--case", c)]
    return r.main(
        ["run", "--cases", str(CASES), *picks, "--runs", str(runs), "--out", str(out), *flags]
    )


def grades_of(out: Path) -> list[dict]:
    return [json.loads(x) for x in (results(out) / "grades.jsonl").read_text().splitlines()]


def results(out: Path) -> Path:
    (only,) = [p for p in out.iterdir() if p.is_dir()]
    return only


def test_parse_stream_finds_init_and_result():
    text = (
        '{"type":"system","subtype":"init","plugins":[]}\n'
        "not json\n"
        '{"type":"result","num_turns":2}\n'
    )
    init, result = r.parse_stream(text)
    assert init["subtype"] == "init" and result["num_turns"] == 2
    assert r.parse_stream("") == (None, None)


def test_run_grades_each_case_and_writes_the_report(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "trash")
    out = fake / "out"
    assert go(out, "--guard-repo", str(guard_repo(fake)), runs=2) == 0
    res = results(out)
    grades = grades_of(out)
    assert [
        (g["case"], g["run"], g["state"], g["accepted"], g["prior_art_hit"]) for g in grades
    ] == [("bib-checker", 1, "trash", True, True), ("bib-checker", 2, "trash", True, True)]
    assert grades[0]["cost_usd"] == 0.25
    assert grades[0]["plugin_path"] == "/plugins/heuresis"
    assert "| bib-checker |" in (res / "summary.md").read_text()
    assert json.loads((res / "summary.json").read_text())["runs"] == 2


def test_the_session_is_isolated_from_memory_mcp_and_repo_settings(fake, monkeypatch):
    record = fake / "record.json"
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "trash")
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    out = fake / "out"
    assert go(out, "--no-guard") == 0
    seen = json.loads(record.read_text())
    assert "--strict-mcp-config" in seen["argv"]
    assert seen["auto_memory"] == "1"
    assert Path(seen["cwd"]).resolve().is_relative_to(out.resolve())


def test_default_out_is_outside_any_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert r.default_out() == tmp_path / "heuresis-gold"
    monkeypatch.delenv("XDG_STATE_HOME")
    assert r.default_out() == Path.home() / ".local" / "state" / "heuresis-gold"


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("crash", "claude exited 3"),
        ("no-plugin", "heuresis plugin did not load"),
    ],
)
def test_failed_runs_are_recorded_and_the_next_case_still_runs(fake, monkeypatch, mode, error):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    out = fake / "out"
    assert go(out, "--no-guard", case=("bib-checker", "teleport")) == 0
    grades = grades_of(out)
    assert [g["case"] for g in grades] == ["bib-checker", "teleport"]
    assert all(error in g["error"] and not g["accepted"] for g in grades)


def test_setup_failure_is_recorded_and_the_set_continues(fake, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("heuresis init failed: boom")

    monkeypatch.setattr(r, "heuresis", broken)
    out = fake / "out"
    assert go(out, "--no-guard", case=("bib-checker", "teleport")) == 0
    grades = grades_of(out)
    assert [g["case"] for g in grades] == ["bib-checker", "teleport"]
    assert all(g["error"] == "setup failed: heuresis init failed: boom" for g in grades)


def alive(pid: int) -> bool:
    stat = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    ).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def test_timeout_is_an_error_and_kills_the_session_children(fake, monkeypatch):
    pidfile = fake / "child.pid"
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    monkeypatch.setenv("FAKE_CLAUDE_PIDFILE", str(pidfile))
    out = fake / "out"
    started = time.monotonic()
    assert go(out, "--no-guard", "--timeout", "2") == 0
    assert time.monotonic() - started < 20
    (g,) = grades_of(out)
    assert g["error"] == "timed out after 2s"
    child = int(pidfile.read_text())
    for _ in range(50):
        if not alive(child):
            break
        time.sleep(0.1)
    assert not alive(child)


def test_a_write_to_the_guard_repo_stops_everything(fake, monkeypatch, capsys):
    guard = guard_repo(fake)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "guard")
    monkeypatch.setenv("FAKE_CLAUDE_GUARD", str(guard))
    out = fake / "out"
    rc = go(out, "--guard-repo", str(guard), case=("bib-checker", "teleport"))
    assert rc == 1
    assert "guard repository" in capsys.readouterr().err
    lines = (results(out) / "grades.jsonl").read_text().splitlines()
    assert len(lines) == 0


@pytest.mark.parametrize("mode", ["guard-modified", "guard-untracked"])
def test_rewriting_an_already_dirty_guard_file_trips_the_guard(fake, monkeypatch, capsys, mode):
    guard = dirty_guard_repo(fake)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    monkeypatch.setenv("FAKE_CLAUDE_GUARD", str(guard))
    out = fake / "out"
    assert go(out, "--guard-repo", str(guard), case=("bib-checker", "teleport")) == 1
    assert "guard repository" in capsys.readouterr().err
    assert (results(out) / "grades.jsonl").read_text() == ""


def test_snapshot_sees_content_ref_and_ignored_changes_but_leaves_the_index_alone(tmp_path):
    repo = dirty_guard_repo(tmp_path)
    (repo / ".gitignore").write_text("ignored.md\n")
    (repo / "ignored.md").write_text("A")
    index = (repo / ".git" / "index").read_bytes()
    base = r.snapshot(repo)
    assert r.snapshot(repo) == base
    assert (repo / ".git" / "index").read_bytes() == index
    for edit in (
        lambda: (repo / "tracked.md").write_text("D" * 20),
        lambda: (repo / "untracked.md").write_text("D" * 20),
        lambda: (repo / "ignored.md").write_text("B"),
    ):
        edit()
        assert r.snapshot(repo) != base
        base = r.snapshot(repo)
    git(repo, "branch", "other")
    assert r.snapshot(repo) != base


def test_guard_is_required_unless_declined(fake, capsys):
    with pytest.raises(SystemExit) as exc:
        go(fake / "out")
    assert exc.value.code == 2
    assert "--guard-repo" in capsys.readouterr().err
    assert not (fake / "out").exists()


def test_guard_must_be_the_top_level_of_a_git_repository(fake, capsys):
    plain = fake / "plain"
    plain.mkdir()
    inside = guard_repo(fake) / "ideas"
    for bad in (plain, inside, fake / "missing"):
        assert go(fake / "out", "--guard-repo", str(bad)) == 2
        assert "top level of a git repository" in capsys.readouterr().err
    assert not (fake / "out").exists()


def test_report_regenerates_the_summary(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "trash")
    out = fake / "out"
    go(out, "--no-guard")
    res = results(out)
    (res / "summary.md").unlink()
    assert r.main(["report", str(res)]) == 0
    assert (res / "summary.md").is_file()


def test_missing_claude_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert r.main(["run", "--cases", str(CASES), "--no-guard", "--out", str(tmp_path / "o")]) == 2
    assert "claude is not on PATH" in capsys.readouterr().err
