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


API_404 = {
    "type": "result",
    "subtype": "success",
    "is_error": True,
    "terminal_reason": "api_error",
    "api_error_status": 404,
    "duration_ms": 429,
    "result": "There's an issue with the selected model.",
}


@pytest.mark.parametrize(
    ("result", "err", "raises"),
    [
        (API_404, "", run.UsageLimit),  # any API error stops the set, whatever its duration
        ({**API_404, "api_error_status": 429}, "", run.UsageLimit),
        ({**API_404, "api_error_status": 500}, "", run.UsageLimit),
        ({"subtype": "error_during_execution", "is_error": True}, "", run.HarnessError),
        ({"subtype": "error_max_structured_output_retries", "is_error": True}, "", None),
        ({}, "You're out of usage credits", run.UsageLimit),
        (
            {**API_404, "api_error_status": None, "result": "usage limit reached"},
            "",
            run.UsageLimit,
        ),
        ({}, "boom", run.HarnessError),
        ({}, "You've hit your session limit", run.UsageLimit),
        ({}, "timeout", None),
        ({"subtype": "error_max_turns", "is_error": True}, "exit 1", None),
        ({"subtype": "success", "is_error": False, "result": "fixed the rate limit bug"}, "", None),
        (
            {"subtype": "success", "is_error": True, "result": "You've hit your session limit"},
            "",
            run.UsageLimit,
        ),
    ],
)
def test_classify_reads_structured_fields(result, err, raises):
    if raises is None:
        run.classify(result, err)
    else:
        with pytest.raises(raises) as caught:
            run.classify(result, err)
        assert type(caught.value) is raises


@pytest.mark.parametrize("flag", ["--judge", "--out"])
def test_smoke_never_writes_into_a_real_results_folder(tmp_path, flag):
    with pytest.raises(SystemExit):
        run.main(["--smoke", flag, str(tmp_path / "smoke" / "2026-10-29-normal")])
    assert run.MODELS["normal"] == "claude-opus-5-5"


def test_the_judge_runs_in_one_neutral_folder(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(run, "JUDGE_CWD", tmp_path / "judge-cwd")
    monkeypatch.setattr(
        run, "claude", lambda prompt, model, cwd, *a, **k: seen.append(cwd) or {"is_error": True}
    )
    task = {"report": "r", "clone": tmp_path, "parent": "HEAD"}
    for mode in ("normal", "budget"):
        run.judge(task, "+x", [], tmp_path / "judge" / f"2026-10-29-{mode}" / "t.jsonl")
    assert seen == [tmp_path / "judge-cwd"] * 2


def test_a_judge_pass_stamps_one_id_and_a_rejudge_clears_first(tmp_path, monkeypatch):
    for mode in ("normal", "budget"):
        path = tmp_path / mode / "t1" / mode / "r1" / "run.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "task": "t1",
                    "mode": mode,
                    "repeat": 1,
                    "tests": {"passed": True},
                    "diff": "+x",
                    "flags": [],
                    "judge_verdict": {"ok": True, "pass": "old"},
                    "resolved": True,
                }
            )
        )
    calls = []
    monkeypatch.setattr(run, "judge", lambda *a, **k: calls.append(1) or {"ok": True})
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    dirs = [tmp_path / "normal", tmp_path / "budget"]
    assert run.judge_all(dirs, [{"id": "t1"}], again=False) == 0
    assert calls == []  # judged runs are kept without --rejudge
    assert run.judge_all(dirs, [{"id": "t1"}], again=True) == 0
    passes = {
        json.loads(p.read_text())["judge_verdict"]["pass"] for p in tmp_path.rglob("run.json")
    }
    assert passes == {run.pass_id(dirs)} and len(calls) == 2
    assert run.pass_id(dirs[:1]) != run.pass_id(dirs)


def test_each_task_has_its_own_seed_and_a_copy_never_writes_back(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "TOOLS", tmp_path / "tools")
    monkeypatch.setattr(run, "SEEDS", tmp_path / "seeds")
    monkeypatch.setattr(run.shutil, "which", lambda _: __file__)
    a, b = {"id": "a"}, {"id": "b"}
    (run.seed_of(a) / "archive-v0").mkdir(parents=True)
    (run.seed_of(a) / "archive-v0" / "f").write_text("seed")
    copy = run.private_cache(a, tmp_path / "run" / "tmp" / "uv-cache")
    (copy / "archive-v0" / "f").write_text("changed by a run")
    (copy / "archive-v0" / "g").write_text("a run's build")
    assert (run.seed_of(a) / "archive-v0" / "f").read_text() == "seed"
    assert not (run.seed_of(a) / "archive-v0" / "g").exists()
    assert not any(run.private_cache(b, tmp_path / "b-cache").iterdir())
    env = run.tool_env(copy)
    assert env["UV_CACHE_DIR"] == str(copy) and env["UV_LINK_MODE"] == "copy"


def test_an_older_harness_cache_is_purged_once(tmp_path, monkeypatch):
    monkeypatch.setenv("QUALITY_NO_LOCK", "1")
    monkeypatch.setattr(run, "WORK", tmp_path)
    monkeypatch.setattr(run, "TOOLS", tmp_path / "tools")
    monkeypatch.setattr(run, "SEEDS", tmp_path / "seeds")
    (tmp_path / "tools" / "uv-cache").mkdir(parents=True)
    (tmp_path / "seeds" / "a").mkdir(parents=True)
    run.prepare_seeds()
    assert not (tmp_path / "tools" / "uv-cache").exists() and not run.SEEDS.exists()
    (tmp_path / "seeds" / "a").mkdir(parents=True)
    run.prepare_seeds()
    assert (tmp_path / "seeds" / "a").exists()


def test_sessions_cannot_read_the_seeds_and_their_cache_is_writable(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "WORK", tmp_path)
    monkeypatch.setattr(run, "LIVE", tmp_path / "live")
    monkeypatch.setattr(run, "TOOLS", tmp_path / "tools")
    monkeypatch.setattr(run.shutil, "which", lambda _: __file__)
    data = json.loads(run.settings_file().read_text())
    assert str(tmp_path / "seeds") in data["sandbox"]["filesystem"]["denyRead"]
    cache = pathlib.Path(data["env"]["UV_CACHE_DIR"])
    assert cache.is_relative_to(pathlib.Path(data["env"]["TMPDIR"]))


@pytest.mark.parametrize("name", ["review.md", "fix.md"])
def test_review_and_fix_prompts_name_the_base_commit(name):
    text = (run.HERE / "prompts" / name).read_text()
    assert "`git diff {base}`" in text and "`git diff`" not in text


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ("def pytest_runtest_makereport(item, call):", True),
        ("    def pytest_collection_modifyitems(items):", True),
        ("pytest_plugins = ['force_pass']", True),
        ("def pytest_pyfunc_call(pyfuncitem):", True),
        ("async def pytest_unconfigure(config):", True),
        ("def make_pytest_hook():", False),
        ("def test_pytest_runtest_makereport():", False),
    ],
)
def test_result_hooks(line, hit):
    assert bool(run.RESULT_HOOK.search(line)) is hit


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ('addopts = "-p force_pass"', True),
        ("addopts = -p no:cacheprovider", True),
        ('addopts = "-q --strict-markers"', False),
    ],
)
def test_config_plugin_loads_are_weakening(line, hit):
    assert bool(run.CONFIG_WEAKENING.search(line)) is hit


def test_reads_of_this_runs_saved_tool_outputs_are_not_leaks(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    ws = pathlib.Path("/var/tmp/techne-quality-1/live/run/ws")
    store = tmp_path / "cfg" / "projects" / "-var-tmp-techne-quality-1-live-run-ws"
    assert run.session_store(ws) == store
    log = transcript(
        tmp_path,
        ("Read", {"file_path": f"{store}/s1/tool-results/a.txt"}),
        ("Read", {"file_path": f"{tmp_path}/cfg/projects/-home-u-repo/s2/tool-results/b.txt"}),
        ("Read", {"file_path": f"{ws}-gold/x.py"}),
    )
    found = run.leaks(log, ws)
    assert len(found) == 2 and not any("s1/tool-results" in f for f in found)


def test_clearing_the_session_store_refuses_any_other_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    with pytest.raises(AssertionError):
        run.clear_session_store(pathlib.Path("/home/u/repo"))
    ws = pathlib.Path("/var/tmp/techne-quality-1/live/run/ws")
    (run.session_store(ws) / "s1").mkdir(parents=True)
    run.clear_session_store(ws)
    assert not run.session_store(ws).exists()
