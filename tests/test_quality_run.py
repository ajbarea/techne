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
        "python3 -c 'import urllib; urllib.request.urlopen(\"https://x\")'",
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
        "cat ~/.cache/techne-quality/done/x/ws/a.py",
        "ls /home/someone/ajsoftworks",
        "cat ../../score/run/tests/test_x.py",
        "grep -r fix $HOME/.claude",
    ],
)
def test_reads_past_the_workspace_by_shell_are_leaks(tmp_path, command):
    assert run.leaks(transcript(tmp_path, ("Bash", {"command": command})), tmp_path / "ws")


def test_tool_folders_and_the_workspace_are_not_leaks(tmp_path):
    ws = pathlib.Path.home() / ".cache" / "techne-quality" / "live" / "run" / "ws"
    for command in (f"cat {ws}/a.py", "ls ~/.cache/uv", "cd ../src && pytest"):
        assert not run.leaks(transcript(tmp_path, ("Bash", {"command": command})), ws)


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
