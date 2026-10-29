"""quality/run.py's mechanical cheat checks fire on what they name and nothing else."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from collections.abc import Sequence

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "quality"))
import run  # ty: ignore[unresolved-import]


@pytest.fixture(autouse=True)
def _no_claude_binary(monkeypatch):
    """CI has no `claude`: every test sees one fixed version unless it sets its own."""
    monkeypatch.setattr(run, "claude_version", lambda: "v1")


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
    assert any(cache.is_relative_to(w) for w in data["sandbox"]["filesystem"]["allowWrite"])


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


def test_a_smoke_run_fails_only_on_a_blocked_uv_cache(tmp_path):
    r1 = tmp_path / "t1" / "normal" / "r1"
    (r1 / "ws" / "fixtures").mkdir(parents=True)
    (r1 / "implement.jsonl").write_text("Read-only file system: '/var/crash/x.crash'")
    (r1 / "ws" / "fixtures" / "t.jsonl").write_text("Failed to initialize cache")
    assert run.blocked_sessions(tmp_path) == []
    (r1 / "review-1.1.jsonl").write_text('error: Failed to initialize cache at "/x/uv-cache"')
    assert run.blocked_sessions(tmp_path) == [str(r1 / "review-1.1.jsonl")]


def junit(path: pathlib.Path, cases: dict[str, str]) -> None:
    body = "".join(
        f'<testcase classname="t" name="{n}">' + (f"<{k}/>" if k else "") + "</testcase>"
        for n, k in cases.items()
    )
    path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")


def test_junit_results(tmp_path):
    junit(tmp_path / "j.xml", {"a": "", "b": "failure", "c": "error", "d": "skipped"})
    assert run.junit_results(tmp_path / "j.xml") == ({"t::a"}, {"t::b", "t::c"})
    assert run.junit_results(tmp_path / "none.xml") == (set(), set())
    (tmp_path / "bad.xml").write_text("<oops")
    assert run.junit_results(tmp_path / "bad.xml") == (set(), set())


def test_junit_failures_carry_the_message_and_text(tmp_path):
    (tmp_path / "j.xml").write_text(
        '<testsuites><testsuite><testcase classname="t" name="a">'
        "<failure message=\"has no attribute 'x'\">trace</failure></testcase>"
        '<testcase classname="t" name="b"/></testsuite></testsuites>'
    )
    assert run.junit_failures(tmp_path / "j.xml") == ["has no attribute 'x'\ntrace"]
    assert run.junit_failures(tmp_path / "none.xml") == []


def test_added_lines_counts_the_new_side():
    diff = "--- a/f\n+++ b/f\n@@ -1,3 +1,4 @@\n a\n-b\n+c\n+d\n e\n@@ -9 +10,2 @@\n x\n+y\n"
    assert run.added_lines(diff) == {2, 3, 11}


def test_strings_skip_docstrings_and_keep_placeholders():
    src = (
        '"""Module doc."""\n\ndef f(x):\n    """Doc."""\n'
        '    return f"{x} stops here", "plain one"\n'
    )
    assert sorted(run.strings(src, "m.py")) == ["plain one", "{} stops here"]
    assert run.strings(src, "m.py", {1, 4}) == []
    assert run.strings('echo "a message"\n', "s.sh") == ["a message"]
    assert run.strings('echo "refused: \\"$h\\" needs"\n', "s.sh") == ['refused: \\"$h\\" needs']


PARENT_CODE = (
    "def msg(rel, where):\n"
    '    return f"{rel} stops for you → go; for a session started in {where}/"\n'
)
FIX_CODE = (
    "def msg(rel, where, nested):\n"
    '    scope = f" in a session started in {where}/" if nested else ""\n'
    '    return f"{rel} stops for you{scope} → go"\n'
)
TEST_CODE = (
    '"""Tests for the message, in a session started in a folder."""\n'
    "def test_m():\n"
    '    assert msg("a", "b", True) == "a stops for you in a session started in b/ → go"\n'
    '    assert fixture("jane.doe@example.org wrote to us")\n'
)


def gap_task(
    tmp_path: pathlib.Path,
    report: str,
    test_code: str = TEST_CODE,
    parent_code: str = PARENT_CODE,
    config: Sequence[tuple[str, str]] = (),
) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()

    def commit(files: dict[str, str]) -> str:
        for rel, body in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(body)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "x"], cwd=repo, check=True)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    for key, value in config:
        subprocess.run(["git", "config", key, value], cwd=repo, check=True)
    parent = commit({"m.py": parent_code, "tests/test_m.py": "def test_old(): pass\n"})
    fix = commit({"m.py": FIX_CODE, "tests/test_m.py": test_code})
    return {
        "clone": repo,
        "parent": parent,
        "fix": fix,
        "report": report,
        "hidden_tests": ["tests/test_m.py"],
    }


@pytest.mark.parametrize(
    "config", [(), (("color.diff", "always"), ("color.ui", "always"))]
)  # the user's git config must not hide the diff
def test_interface_gaps_name_new_wording_the_report_leaves_out(tmp_path, config):
    task = gap_task(tmp_path, "msg names the folder for a nested file.", config=config)
    assert run.interface_gaps(task, []) == [
        "wording the report does not give: a stops for you in a session started in b/ → go"
    ]


def test_interface_gaps_accept_wording_the_report_states(tmp_path):
    report = "A nested one reads `<rel> stops for you in a session started in <where>/ → go`."
    assert run.interface_gaps(gap_task(tmp_path, report), []) == []


def test_windows_read_a_closing_period_as_punctuation():
    said = run.windows("It reads `set but empty.` Then run.py stops.")
    assert {("set", "but", "empty"), ("then", "run.py", "stops")} <= said


@pytest.mark.parametrize(
    "literal",
    [
        "session go stops in",  # only the fix's words, no three-word run of its strings
        "stops for you → go",  # wording the parent already had
    ],
)
def test_interface_gaps_leave_out_strings_that_add_no_wording(tmp_path, literal):
    test_code = TEST_CODE + f'    assert fixture("{literal}")\n'
    report = "A nested one reads `<rel> stops for you in a session started in <where>/ → go`."
    assert run.interface_gaps(gap_task(tmp_path, report, test_code), []) == []


def test_interface_gaps_read_wording_the_parent_kept_in_a_dict(tmp_path):
    parent = PARENT_CODE + 'OLD = {"k": "a stops for you in a session started in b/ → go"}\n'
    task = gap_task(tmp_path, "msg names the folder for a nested file.", parent_code=parent)
    assert run.interface_gaps(task, []) == []


def test_interface_gaps_skip_a_name_the_parent_defines(tmp_path):
    report = "A nested one reads `<rel> stops for you in a session started in <where>/ → go`."
    failures = ["AttributeError: 'NoneType' object has no attribute 'msg'"]
    assert run.interface_gaps(gap_task(tmp_path, report), failures) == []


def test_interface_gaps_read_every_unrecognized_flag(tmp_path):
    report = "A nested one reads `<rel> stops for you in a session started in <where>/ → go`."
    report += " It takes `--repos-root`."
    failures = ["error: unrecognized arguments: --repos-root /a --techne-toml /b -q"]
    assert run.interface_gaps(gap_task(tmp_path, report), failures) == [
        "name the report does not give: --techne-toml",
        "name the report does not give: -q",
    ]


def test_interface_gaps_name_what_the_parent_lacks_unless_the_report_does(tmp_path):
    report = (
        "Interface: a stops for you in a session started in b/ → go. `cli.grants_file()`;"
        " it writes artifacts to the results folder."
    )
    task = gap_task(tmp_path, report)
    failures = [
        "AttributeError: module 'redact' has no attribute 'artifacts'",
        "AttributeError: module 'cli' has no attribute 'grants_file'",
        "error: unrecognized arguments: --techne-toml /x",
    ]
    assert run.interface_gaps(task, failures) == [
        "name the report does not give: --techne-toml",
        "name the report does not give: artifacts",
    ]


@pytest.mark.parametrize(
    ("report", "parent_ran", "ok"),
    [
        ("The fix adds `artifacts(results)`.", True, True),
        ("No name given.", True, False),
        ("The fix adds `artifacts(results)`.", False, False),  # a timeout: nothing was checked
    ],
)
def test_check_tasks_fails_a_task_whose_report_leaves_out_a_name(
    tmp_path, monkeypatch, capsys, report, parent_ran, ok
):
    monkeypatch.setattr(run, "CHECK", tmp_path / "check")
    monkeypatch.setattr(run, "GOLD", tmp_path / "gold.json")
    monkeypatch.setattr(run, "workspace", lambda task, dest: dest.mkdir(parents=True))
    monkeypatch.setattr(run, "git", lambda *a: "")
    monkeypatch.setattr(run, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(run, "base_of", lambda ws: "base")
    monkeypatch.setattr(run, "diff_files", lambda ws: [])
    monkeypatch.setattr(run, "audit", lambda *a: [])

    def scored(task, ws, dest, require=None, messages=False):
        if dest.name == "score-parent":
            assert messages  # the gap check reads the parent's failures
            return {
                "passed": False,
                "tests_run": ["t::a"] if parent_ran else [],
                "failures": ["module 'x' has no attribute 'artifacts'"] if parent_ran else [],
            }
        return {"passed": True, "tests_run": ["t::a"]}

    monkeypatch.setattr(run, "hidden_tests", scored)
    task = {"id": "a", "clone": tmp_path, "parent": "p", "fix": "f", "report": report}
    task["hidden_tests"] = ["tests/test_a.py"]
    assert run.check_tasks([task]) == (0 if ok else 1)
    out = capsys.readouterr().out
    assert ("BROKEN" in out) is not ok
    assert json.loads(run.GOLD.read_text()) == ({"a": ["t::a"]} if ok else {})


def test_added_lines_reads_an_added_line_that_starts_with_two_pluses():
    assert run.added_lines("--- a/f\n+++ b/f\n@@ -1 +1,3 @@\n a\n+++x\n+y\n") == {2, 3}


def test_a_name_counts_as_given_only_as_a_whole_word(monkeypatch):
    monkeypatch.setattr(run, "git", lambda *a: "")
    task = {"report": "Uses spool.", "hidden_tests": [], "clone": ".", "parent": "p", "fix": "f"}
    failures = ["module 'c' has no attribute 'pool'"]
    assert run.interface_gaps(task, failures) == ["name the report does not give: pool"]
    task["report"] = "Adds `cli.pool()`."
    assert run.interface_gaps(task, failures) == []


@pytest.mark.parametrize(
    ("rc", "cases", "require", "want"),
    [
        (0, {"a": "", "b": ""}, ["t::a", "t::b"], True),
        (0, {}, ["t::a"], False),  # --co, --setup-plan: exit 0 with no test run
        (0, {"a": ""}, ["t::a", "t::b"], False),  # a gold test deselected
        (0, {"a": "", "b": "failure"}, ["t::a"], False),  # an exit status rewritten to 0
        (1, {"a": ""}, ["t::a"], False),
    ],
)
def test_scoring_needs_every_gold_test_to_pass(tmp_path, monkeypatch, rc, cases, require, want):
    dest = tmp_path / "score" / "run"
    monkeypatch.setattr(run, "workspace", lambda task, d: d.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(run, "private_cache", lambda task, d: d)
    monkeypatch.setattr(run, "tool_env", lambda cache: {})
    monkeypatch.setenv("QUALITY_NO_LOCK", "1")

    def fake_sh(cmd, cwd=None, **kw):
        if cmd[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "unshare":
            junit(dest.parent / "run.junit.xml", cases)
            return subprocess.CompletedProcess(cmd, rc, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(run, "sh", fake_sh)
    monkeypatch.setattr(run, "staged_diff", lambda ws: b"")
    task = {"hidden_tests": [], "hidden_command": "pytest", "id": "t"}
    monkeypatch.setattr(run, "base_of", lambda ws: "base")
    assert run.hidden_tests(task, tmp_path / "ws", dest, require)["passed"] is want


def harness(tmp_path, monkeypatch, ids=("a", "b", "c"), version="v1"):
    """main()'s surroundings, faked: tasks IDS with gold ids, clean inputs, no seeds, a pinned
    elenchus, and Claude Code at VERSION (a list is read one value per call)."""
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    monkeypatch.setattr(run, "prepare_seeds", lambda: None)
    monkeypatch.setattr(run, "PHASE_REPEATS", dict.fromkeys(run.PHASES, 1))
    monkeypatch.setattr(run, "dirty_inputs", lambda: "")
    monkeypatch.setattr(
        run, "pin_elenchus", lambda commit, dest: dest.mkdir(parents=True, exist_ok=True)
    )
    monkeypatch.setattr(run, "input_hashes", lambda e: {"harness": "h", "elenchus": "e"})
    monkeypatch.setattr(run, "sh", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "c0", ""))
    versions = iter(version) if isinstance(version, list) else None
    monkeypatch.setattr(run, "claude_version", lambda: next(versions) if versions else version)
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({i: ["t::x"] for i in ids}))
    monkeypatch.setattr(run, "GOLD", gold)
    tasks = tmp_path / "tasks.toml"
    tasks.write_text("".join(f'[[task]]\nid = "{i}"\nclone = "/x"\n' for i in ids))
    return ["--tasks", str(tasks), "--repeats", "1", "--phase", "baseline"]


def recorded(task, mode, rep, out, elenchus, meta=None, total=None):
    dest = out / task["id"] / mode / f"r{rep}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "run.json").write_text(json.dumps({"task": task["id"], **(meta or {})}))


def test_two_harness_failures_in_a_row_record_neither_run(tmp_path, monkeypatch):
    args = harness(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("harness")

    monkeypatch.setattr(run, "run_one", boom)
    monkeypatch.setattr(run, "failed_run", lambda *a: {"harness_failed": True})
    out = tmp_path / "out"
    assert run.main([*args, "--out", str(out)]) == 3
    assert not list(out.rglob("run.json")) and not list(out.rglob("errors.json"))
    kinds = [json.loads(x)["kind"] for x in (out / "discards.jsonl").read_text().splitlines()]
    assert kinds == ["two_in_a_row", "two_in_a_row"]


def test_a_resume_with_another_phase_repeats_or_inputs_is_refused(tmp_path, monkeypatch):
    args = harness(tmp_path, monkeypatch)
    monkeypatch.setattr(run, "run_one", recorded)
    out = tmp_path / "out"
    assert run.main([*args, "--out", str(out)]) == 0
    assert json.loads((out / "a/normal/r1/run.json").read_text())["phase"] == "baseline"
    assert run.main([*args, "--out", str(out)]) == 0  # the same command resumes
    pilot = [x if x != "baseline" else "pilot" for x in args]
    assert run.main([*pilot, "--out", str(out)]) == 3
    monkeypatch.setattr(run, "PHASE_REPEATS", dict.fromkeys(run.PHASES, 3))
    assert run.main([*args[:-4], "--repeats", "3", *args[-2:], "--out", str(out)]) == 3
    monkeypatch.setattr(run, "PHASE_REPEATS", dict.fromkeys(run.PHASES, 1))
    monkeypatch.setattr(run, "input_hashes", lambda e: {"harness": "other", "elenchus": "e"})
    assert run.main([*args, "--out", str(out)]) == 3


def test_a_folder_with_runs_but_no_set_file_is_refused(tmp_path, monkeypatch):
    args = harness(tmp_path, monkeypatch)
    monkeypatch.setattr(run, "run_one", recorded)
    out = tmp_path / "out"
    (out / "a" / "normal" / "r1").mkdir(parents=True)
    (out / "a" / "normal" / "r1" / "run.json").write_text("{}")
    assert run.main([*args, "--out", str(out)]) == 3


def test_a_run_needs_a_phase_clean_inputs_and_gold_ids_before_any_session(tmp_path, monkeypatch):
    args = harness(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(run, "run_one", lambda *a, **k: calls.append(a))
    out = str(tmp_path / "out")
    with pytest.raises(SystemExit):
        run.main([*args[:-2], "--out", out])  # no --phase
    run.GOLD.write_text(json.dumps({"a": ["t::x"], "b": []}))
    with pytest.raises(SystemExit):
        run.main([*args, "--out", out])
    run.GOLD.write_text(json.dumps({i: ["t::x"] for i in "abc"}))
    monkeypatch.setattr(run, "dirty_inputs", lambda: " M quality/judge.md")
    with pytest.raises(SystemExit):
        run.main([*args, "--out", out])
    assert calls == []


def test_a_claude_code_update_mid_run_stops_the_set_without_a_record(tmp_path, monkeypatch):
    args = harness(tmp_path, monkeypatch, ids=("a", "b"), version=["v1", "v1", "v2"])
    monkeypatch.setattr(run, "run_one", recorded)
    out = tmp_path / "out"
    assert run.main([*args, "--out", str(out)]) == 3
    assert len(list(out.rglob("run.json"))) == 1  # the run before the update stands
    (entry,) = [json.loads(x) for x in (out / "discards.jsonl").read_text().splitlines()]
    assert (entry["kind"], entry["now"]) == ("version_change", "v2")


def test_a_usage_limit_logs_the_discarded_run_with_what_it_spent(tmp_path, monkeypatch):
    args = harness(tmp_path, monkeypatch, ids=("a",))

    def limited(task, mode, rep, out, elenchus, meta=None, total=None):
        assert total is not None
        total["cost_usd"] = 1.25
        raise run.UsageLimit("API error 529: overloaded", "api_error")

    monkeypatch.setattr(run, "run_one", limited)
    out = tmp_path / "out"
    assert run.main([*args, "--out", str(out)]) == 3
    (entry,) = [json.loads(x) for x in (out / "discards.jsonl").read_text().splitlines()]
    assert (entry["kind"], entry["usage"]) == ("api_error", {"cost_usd": 1.25})
    assert not list(out.rglob("run.json"))


def test_a_long_api_error_keeps_its_kind():
    with pytest.raises(run.UsageLimit) as exc:
        run.classify({"terminal_reason": "api_error", "result": "x" * 2000}, "")
    assert exc.value.kind == "api_error"


def test_input_hashes_follow_content_not_location(tmp_path):
    for where in ("one", "two"):
        d = tmp_path / where / "elenchus"
        (d / "references").mkdir(parents=True)
        (d / "SKILL.md").write_text("s")
        (d / "references" / "bug-classes.md").write_text("c")
    one, two = tmp_path / "one" / "elenchus", tmp_path / "two" / "elenchus"
    assert run.digest(one) == run.digest(two)
    (two / "references" / "bug-classes.md").write_text("c2")
    assert run.digest(one) != run.digest(two)
    assert run.digest(tmp_path / "absent.json") != run.digest(tmp_path / "one")


def test_pin_elenchus_copies_the_skill_as_committed(tmp_path):
    dest = tmp_path / "elenchus"
    run.pin_elenchus("HEAD", dest)
    assert (dest / "SKILL.md").read_bytes() == subprocess.run(
        ["git", "-C", str(run.ROOT), "show", f"HEAD:{run.ELENCHUS}/SKILL.md"],
        capture_output=True,
        check=True,
    ).stdout
    assert (dest / "references" / "bug-classes.md").exists()


def test_a_diff_with_bytes_that_are_not_utf8_still_applies(tmp_path, monkeypatch):
    ws, dest = tmp_path / "ws", tmp_path / "score" / "run"
    ws.mkdir()
    for c in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", "-C", str(ws), *c], check=True)
    (ws / "data.txt").write_bytes(b"caf\xe9\n")
    subprocess.run(["git", "-C", str(ws), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(ws), "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        ["git", "-C", str(ws), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    (ws / "data.txt").write_bytes(b"caf\xe9 fixed\n")

    def rebuild(task, d):
        subprocess.run(["git", "clone", "-q", str(ws), str(d)], check=True)

    monkeypatch.setattr(run, "workspace", rebuild)
    monkeypatch.setattr(run, "base_of", lambda w: base)
    monkeypatch.setattr(run, "private_cache", lambda task, d: d)
    monkeypatch.setattr(run, "tool_env", lambda cache: {})
    monkeypatch.setenv("QUALITY_NO_LOCK", "1")
    task = {"hidden_tests": [], "hidden_command": "true", "id": "t"}
    out = run.hidden_tests(task, ws, dest)
    assert out["tail"] != "the diff does not apply to a clean tree"
    assert (dest / "data.txt").read_bytes() == b"caf\xe9 fixed\n"


def test_a_timeout_while_retrying_the_api_stops_the_set(tmp_path, monkeypatch):
    log = tmp_path / "s.jsonl"

    def slow(cmd, **kw):
        log.write_text(json.dumps({"type": "system", "subtype": "api_retry"}) + "\n")
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(run.subprocess, "run", slow)
    monkeypatch.setattr(run, "settings_file", lambda: tmp_path / "settings.json")
    with pytest.raises(run.UsageLimit):
        run.claude("p", "m", tmp_path, log, "")


def test_only_one_harness_process_runs_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "WORK", tmp_path)
    held = open(tmp_path / "run.lock", "a")
    run.fcntl.flock(held, run.fcntl.LOCK_EX | run.fcntl.LOCK_NB)
    try:
        with pytest.raises(SystemExit):
            run.main(["--check-tasks"])
    finally:
        held.close()


def test_the_harness_pins_claude_code():
    assert run.clean_env()["DISABLE_AUTOUPDATER"] == "1"


def test_two_failed_judge_sessions_in_a_row_stop_the_pass_and_keep_neither(tmp_path, monkeypatch):
    for n in (1, 2, 3):
        path = tmp_path / "res" / f"t{n}" / "normal" / "r1" / "run.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "task": f"t{n}",
                    "mode": "normal",
                    "repeat": 1,
                    "tests": {"passed": True},
                    "diff": "+x",
                    "flags": [],
                    "judge_verdict": None,
                    "resolved": None,
                }
            )
        )

    def fail(*a, **k):
        raise run.HarnessError("judge down")

    monkeypatch.setattr(run, "judge", fail)
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    tasks = [{"id": f"t{n}"} for n in (1, 2, 3)]
    assert run.judge_all([tmp_path / "res"], tasks, again=False) == 3
    verdicts = [json.loads(p.read_text())["judge_verdict"] for p in tmp_path.rglob("run.json")]
    assert verdicts == [None, None, None]


@pytest.mark.parametrize(("phase", "repeats"), [("pilot", 3), ("baseline", 1), ("confirmatory", 2)])
def test_a_phase_runs_only_its_registered_repeats(tmp_path, monkeypatch, phase, repeats):
    args = harness(tmp_path, monkeypatch)
    monkeypatch.setattr(run, "PHASE_REPEATS", {"baseline": 3, "pilot": 1, "confirmatory": 3})
    monkeypatch.setattr(run, "run_one", recorded)
    argv = [*args[:2], "--repeats", str(repeats), "--phase", phase, "--out", str(tmp_path / "o")]
    with pytest.raises(SystemExit):
        run.main(argv)


def git_repo(root: pathlib.Path) -> None:
    for rel in ("quality/run.py", f"{run.ELENCHUS}/SKILL.md", "IMPL.md"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x")
    for c in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "base"],
    ):
        subprocess.run(["git", "-C", str(root), *c], check=True)


def test_results_and_unrelated_commits_never_block_a_resume(tmp_path, monkeypatch):
    git_repo(tmp_path)
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run, "HERE", tmp_path / "quality")
    (tmp_path / "quality" / "results" / "set-a").mkdir(parents=True)
    (tmp_path / "quality" / "results" / "set-a" / "set.json").write_text("{}")
    (tmp_path / "quality" / "__pycache__").mkdir()
    (tmp_path / "quality" / "__pycache__" / "run.pyc").write_text("x")
    (tmp_path / "IMPL.md").write_text("changed")
    assert run.dirty_inputs() == ""
    (tmp_path / "quality" / "run.py").write_text("edited")
    assert "quality/run.py" in run.dirty_inputs()
    (tmp_path / "quality" / "run.py").write_text("x")
    (tmp_path / run.ELENCHUS / "references").mkdir()
    (tmp_path / run.ELENCHUS / "references" / "bug-classes.md").write_text("new class")
    assert run.ELENCHUS in run.dirty_inputs()


@pytest.mark.parametrize(
    ("tool", "inp"),
    [
        ("Read", {"file_path": "{ws}/../../../../../home/ajbar/x.py"}),
        ("Grep", {"pattern": "fix", "path": "{tools}/../done"}),
        ("Glob", {"pattern": "../../../../home/**/*.py"}),
        ("Grep", {"pattern": "x", "glob": "../../../../home/**"}),
        ("Read", {"file_path": "~ajbar/ajsoftworks/techne/README.md"}),
        ("Glob", {"pattern": "/home/ajbar/**"}),
        ("Bash", {"command": "cat {ws}/../../../done/t1/normal/r1/run.json"}),
    ],
)
def test_file_tools_that_climb_out_are_leaks(tmp_path, monkeypatch, tool, inp):
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    monkeypatch.setattr(run, "LIVE", tmp_path / "work" / "live")
    monkeypatch.setattr(run, "TOOLS", tmp_path / "work" / "tools")
    ws = tmp_path / "work" / "live" / "run" / "ws"
    fill = {k: v.format(ws=ws, tools=run.TOOLS) for k, v in inp.items()}
    assert run.leaks(transcript(tmp_path, (tool, fill)), ws)


@pytest.mark.parametrize(
    ("tool", "inp"),
    [
        ("Read", {"file_path": "{ws}/src/a.py"}),
        ("Glob", {"pattern": "**/*.py"}),
        ("Grep", {"pattern": "/home/ajbar", "glob": "*.py"}),  # a regex that names a path
        ("Read", {"file_path": "{ws}/src/../tests/test_a.py"}),
        ("Read", {"file_path": "~/.cache/notes.txt"}),  # the session's own home
    ],
)
def test_file_tools_inside_the_workspace_are_not_leaks(tmp_path, monkeypatch, tool, inp):
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    monkeypatch.setattr(run, "LIVE", tmp_path / "work" / "live")
    ws = tmp_path / "work" / "live" / "run" / "ws"
    fill = {k: v.format(ws=ws) for k, v in inp.items()}
    assert run.leaks(transcript(tmp_path, (tool, fill)), ws) == []


def test_file_tools_are_denied_home_except_the_runs_saved_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    monkeypatch.setattr(run, "LIVE", tmp_path / "work" / "live")
    homes = tmp_path / "home"
    config = homes / "aj" / ".claude"
    monkeypatch.setattr(run, "HOMES", homes)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    ws = run.LIVE / "run" / "ws"
    store = run.session_store(ws)
    for d in (store / "tool-results", config / "projects" / "other", homes / "aj" / "src"):
        d.mkdir(parents=True)
    (config / ".credentials.json").write_text("{}")
    (homes / "bo").mkdir()
    denied = set(run.read_denials(ws))
    assert {"/tmp", "/mnt", "/root", str(run.WORK / "done"), str(run.WORK / "seeds")} <= denied
    assert {str(config / "projects" / "other"), str(config / ".credentials.json")} <= denied
    assert {str(homes / "aj" / "src"), str(homes / "bo")} <= denied
    under = [pathlib.Path(d) for d in denied if pathlib.Path(d).is_relative_to(homes)]
    assert not any(store.is_relative_to(d) or d.is_relative_to(store) for d in under)


def test_a_claude_code_update_mid_judge_pass_keeps_no_verdict_from_it(tmp_path, monkeypatch):
    for rep in (1, 2):
        path = tmp_path / "set" / "t1" / "normal" / f"r{rep}" / "run.json"
        path.parent.mkdir(parents=True)
        base = {"task": "t1", "mode": "normal", "repeat": rep, "tests": {"passed": True}}
        path.write_text(json.dumps({**base, "diff": "+x", "flags": [], "judge_verdict": None}))
    versions = iter(["v1", "v1", "v2"])
    monkeypatch.setattr(run, "claude_version", lambda: next(versions))
    monkeypatch.setattr(run, "judge", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    assert run.judge_all([tmp_path / "set"], [{"id": "t1"}], again=False) == 3
    verdicts = [json.loads(p.read_text())["judge_verdict"] for p in tmp_path.rglob("run.json")]
    assert sorted(v is None for v in verdicts) == [False, True]
    assert [v["claude_code"] for v in verdicts if v] == ["v1"]


def test_a_symlinked_config_folder_keeps_the_saved_outputs_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    monkeypatch.setattr(run, "LIVE", tmp_path / "work" / "live")
    homes = tmp_path / "home"
    real, linked = homes / "aj" / ".claude", homes / "aj" / ".claude-rit"
    (real / "projects" / "other").mkdir(parents=True)
    linked.mkdir()
    (linked / "projects").symlink_to(real / "projects")
    (linked / ".credentials.json").write_text("{}")
    monkeypatch.setattr(run, "HOMES", homes)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(linked))
    ws = run.LIVE / "run" / "ws"
    store = run.session_store(ws)
    (store / "tool-results").mkdir(parents=True)
    under = [pathlib.Path(d) for d in run.read_denials(ws) if pathlib.Path(d).is_relative_to(homes)]
    for s in (store, store.resolve()):
        assert not any(s.is_relative_to(d) or d.is_relative_to(s) for d in under), s
    assert real / "projects" / "other" in under or linked / "projects" / "other" in under
    assert linked / ".credentials.json" in under
    saved = store.resolve() / "tool-results" / "out.txt"
    log = transcript(tmp_path, ("Read", {"file_path": str(saved)}))
    assert run.leaks(log, ws) == []


@pytest.mark.parametrize("run_session", [True, False])
def test_only_a_runs_own_sessions_may_read_back_their_saved_outputs(
    tmp_path, monkeypatch, run_session
):
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    monkeypatch.setattr(run, "LIVE", tmp_path / "work" / "live")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(run, "settings_file", lambda: tmp_path / "settings.json")
    seen = []

    def fake(cmd, **kw):
        seen.append(cmd)
        kw["stdout"].write(json.dumps({"type": "result", "subtype": "success"}) + "\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(run.subprocess, "run", fake)
    cwd = run.LIVE / "run" / "ws" if run_session else tmp_path / "judge-cwd"
    cwd.mkdir(parents=True)
    run.claude("p", "m", cwd, tmp_path / "s.jsonl", "Read")
    dirs = [seen[0][i + 1] for i, x in enumerate(seen[0]) if x == "--add-dir"]
    assert (str(run.session_store(cwd)) in dirs) is run_session
