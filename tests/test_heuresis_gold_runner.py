"""The gold runner, driven with a fake claude on PATH."""

from __future__ import annotations

import json
import os
import subprocess
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
    shim.write_text(f'#!/bin/sh\nexec python3 {FAKE} "$@"\n')
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HEURESIS_SRC", str(ROOT / "plugins" / "heuresis"))
    return tmp_path


def guard_repo(tmp: Path) -> Path:
    repo = tmp / "real-ideas"
    (repo / "ideas").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


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
    rc = r.main(
        [
            "run",
            "--cases",
            str(CASES),
            "--case",
            "bib-checker",
            "--runs",
            "2",
            "--out",
            str(out),
            "--guard-repo",
            str(guard_repo(fake)),
        ]
    )
    assert rc == 0
    res = results(out)
    grades = [json.loads(line) for line in (res / "grades.jsonl").read_text().splitlines()]
    assert [
        (g["case"], g["run"], g["state"], g["accepted"], g["prior_art_hit"]) for g in grades
    ] == [("bib-checker", 1, "trash", True, True), ("bib-checker", 2, "trash", True, True)]
    assert grades[0]["cost_usd"] == 0.25
    assert "| bib-checker |" in (res / "summary.md").read_text()
    assert json.loads((res / "summary.json").read_text())["runs"] == 2


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
    assert (
        r.main(
            [
                "run",
                "--cases",
                str(CASES),
                "--case",
                "bib-checker",
                "--case",
                "teleport",
                "--runs",
                "1",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    grades = [json.loads(x) for x in (results(out) / "grades.jsonl").read_text().splitlines()]
    assert [g["case"] for g in grades] == ["bib-checker", "teleport"]
    assert all(error in g["error"] and not g["accepted"] for g in grades)


def test_timeout_is_an_error(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    out = fake / "out"
    assert (
        r.main(
            [
                "run",
                "--cases",
                str(CASES),
                "--case",
                "bib-checker",
                "--runs",
                "1",
                "--timeout",
                "2",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    (g,) = [json.loads(x) for x in (results(out) / "grades.jsonl").read_text().splitlines()]
    assert g["error"] == "timed out after 2s"


def test_a_write_to_the_guard_repo_stops_everything(fake, monkeypatch, capsys):
    guard = guard_repo(fake)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "guard")
    monkeypatch.setenv("FAKE_CLAUDE_GUARD", str(guard))
    out = fake / "out"
    rc = r.main(
        [
            "run",
            "--cases",
            str(CASES),
            "--case",
            "bib-checker",
            "--case",
            "teleport",
            "--runs",
            "1",
            "--out",
            str(out),
            "--guard-repo",
            str(guard),
        ]
    )
    assert rc == 1
    assert "guard repository" in capsys.readouterr().err
    lines = (results(out) / "grades.jsonl").read_text().splitlines()
    assert len(lines) == 0


def test_report_regenerates_the_summary(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "trash")
    out = fake / "out"
    r.main(
        ["run", "--cases", str(CASES), "--case", "bib-checker", "--runs", "1", "--out", str(out)]
    )
    res = results(out)
    (res / "summary.md").unlink()
    assert r.main(["report", str(res)]) == 0
    assert (res / "summary.md").is_file()


def test_missing_claude_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert r.main(["run", "--cases", str(CASES), "--out", str(tmp_path / "o")]) == 2
    assert "claude is not on PATH" in capsys.readouterr().err
