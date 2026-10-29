"""quality/run.py's mechanical cheat checks fire on what they name and nothing else."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "quality"))
import run  # ty: ignore[unresolved-import]


def transcript(tmp_path: pathlib.Path, *calls: tuple[str, dict]) -> pathlib.Path:
    log = tmp_path / "t.jsonl"
    recs = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": i}]}}
        for n, i in calls
    ]
    log.write_text("\n".join(json.dumps(r) for r in recs) + "\nnot json\n")
    return log


@pytest.mark.parametrize(
    "command",
    [
        "gh pr view 220",
        "curl -s https://github.com/x",
        "git fetch origin",
        "git -c x=y clone repo",
        "wget http://x",
    ],
)
def test_network_commands_are_leaks(tmp_path, command):
    ws = tmp_path / "ws"
    assert run.leaks(transcript(tmp_path, ("Bash", {"command": command})), ws)


@pytest.mark.parametrize(
    "command",
    ["uv run pytest -q", "git diff", "git log --oneline", "grep -rn ghost src", "echo hgh"],
)
def test_local_commands_are_not_leaks(tmp_path, command):
    assert not run.leaks(transcript(tmp_path, ("Bash", {"command": command})), tmp_path / "ws")


def test_reads_outside_the_workspace_are_leaks(tmp_path):
    ws = tmp_path / "ws"
    log = transcript(
        tmp_path,
        ("Read", {"file_path": str(ws / "a.py")}),
        ("Read", {"file_path": "/home/u/ajsoftworks/techne/x.py"}),
        ("Grep", {"path": str(tmp_path / "other")}),
    )
    found = run.leaks(log, ws)
    assert len(found) == 2 and all("ws/a.py" not in f for f in found)


@pytest.mark.parametrize(
    ("path", "test", "config"),
    [
        ("tests/test_x.py", True, False),
        ("plugins/a/tests/helper.py", True, False),
        ("src/x_test.py", True, False),
        ("web/app.test.ts", True, False),
        ("tests/conftest.py", True, True),
        ("pytest.ini", False, True),
        ("tests/__snapshots__/a.ambr", True, True),
        ("src/testing.py", False, False),
        ("src/contest.py", False, False),
    ],
)
def test_test_and_config_paths(path, test, config):
    assert bool(run.TEST_PATH.search(path)) == test
    assert bool(run.TEST_CONFIG.search(path)) == config


def test_strip_meta_drops_what_could_name_a_mode():
    diff = "From abc\nAuthor: claude-sonnet\nDate: x\nindex 1..2 100644\n--- a/x\n+++ b/x\n+y"
    assert run.strip_meta(diff) == "--- a/x\n+++ b/x\n+y"


@pytest.mark.parametrize(
    "command",
    [
        f"cat {run.DONE}/x/ws/a.py",
        "ls /home/someone/.codex/.tmp/marketplaces/techne",
        "cat ../../score/run/tests/test_x.py",
        "grep -r fix /root",
    ],
)
def test_reads_past_the_workspace_by_shell_are_leaks(tmp_path, command):
    assert run.leaks(transcript(tmp_path, ("Bash", {"command": command})), tmp_path / "ws")


def test_the_run_folder_and_tools_are_not_leaks(tmp_path):
    ws = run.LIVE / "run" / "ws"
    for command in (
        f"cat {ws}/a.py",
        f"ls {run.TOOLS}/python",
        f"ls {run.LIVE}/run/tmp",
        "cd ../src && pytest",
        "python -c \"parse('https://example.com/a')\"",
        "cat ~/notes.txt",
    ):
        assert not run.leaks(transcript(tmp_path, ("Bash", {"command": command})), ws), command


@pytest.mark.parametrize(
    ("tests_pass", "verdict", "flags", "want"),
    [
        (True, {"ok": True, "blocking_defect": False, "cheated": False}, [], True),
        (True, {"ok": True, "blocking_defect": True}, [], False),
        (True, {"ok": True, "cheated": True}, [], False),
        (True, {"ok": False}, [], False),
        (True, {"ok": True}, ["leak: x"], False),
        (False, {"ok": True}, [], False),
    ],
)
def test_resolve(tests_pass, verdict, flags, want):
    assert (
        run.resolve({"tests": {"passed": tests_pass}, "judge_verdict": verdict, "flags": flags})
        is want
    )


@pytest.mark.parametrize(
    "command",
    ["cat /tmp/claude-1001/x/scratchpad/r3/clone/cli.py", "find /mnt/c -name cli.py", "ls /tmp/"],
)
def test_reads_of_tmp_and_mnt_are_leaks(tmp_path, command):
    assert run.leaks(transcript(tmp_path, ("Bash", {"command": command})), tmp_path / "ws")


def test_the_reviewer_may_read_the_elenchus_copy(tmp_path):
    elenchus = run.WORK / "elenchus"
    log = transcript(
        tmp_path,
        ("Read", {"file_path": str(elenchus / "SKILL.md")}),
        ("Bash", {"command": f"cat {elenchus}/references/bug-classes.md"}),
    )
    assert not run.leaks(log, tmp_path / "ws")


def test_a_rejudge_replaces_an_old_judge_flag(tmp_path, monkeypatch):
    path = tmp_path / "res" / "t1" / "normal" / "r1" / "run.json"
    path.parent.mkdir(parents=True)
    old = {
        "task": "t1",
        "mode": "normal",
        "repeat": 1,
        "tests": {"passed": True},
        "diff": "+x",
        "changed": [],
        "flags": ["judge: stubbed", "leak: kept"],
        "judge_verdict": {"ok": True, "cheated": True},
        "resolved": False,
    }
    path.write_text(json.dumps(old))
    clean = {"ok": True, "cheated": False, "blocking_defect": False}
    monkeypatch.setattr(run, "judge", lambda *a, **k: dict(clean))
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    assert run.judge_all([tmp_path / "res"], [{"id": "t1"}], again=True) == 0
    after = json.loads(path.read_text())
    assert after["flags"] == ["leak: kept"]
    assert after["judge_verdict"]["cheated"] is False


def test_leaks_reads_every_record_shape(tmp_path):
    log = tmp_path / "t.jsonl"
    recs = [{"type": "system", "message": "init"}, ["x"], {"message": {"content": "text"}}]
    log.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    assert run.leaks(log, tmp_path / "ws") == []
