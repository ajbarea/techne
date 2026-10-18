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


def plugin_repo(tmp: Path) -> Path:
    """A repository whose plugins/heuresis folder is the plugin under test, version 9.9.9."""
    repo = tmp / "plugin-repo"
    manifest = repo / "plugins" / "heuresis" / ".claude-plugin"
    manifest.mkdir(parents=True)
    (manifest / "plugin.json").write_text('{"name": "heuresis", "version": "9.9.9"}')
    (repo / "other.txt").write_text("a")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo


def identity_of(grades: list[dict]) -> list[tuple]:
    return [(g["commit"], g["dirty"], g["plugin_version"]) for g in grades]


def test_each_grade_records_the_code_under_test_and_the_summary_names_it(fake, monkeypatch):
    repo = plugin_repo(fake)
    mine = repo / "plugins" / "heuresis"
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "two-plugins")
    monkeypatch.setenv("FAKE_PLUGIN_DIR", str(mine))
    out = fake / "out"
    assert go(out, "--no-guard", "--plugin-dir", str(mine)) == 0
    assert identity_of(grades_of(out)) == [(head, False, "9.9.9")]
    summary = (results(out) / "summary.md").read_text()
    assert f"- Code under test: {head[:12]}, clean, plugin version 9.9.9" in summary
    (repo / "other.txt").write_text("b")
    out = fake / "out2"
    assert go(out, "--no-guard", "--plugin-dir", str(mine)) == 0
    assert identity_of(grades_of(out)) == [(head, False, "9.9.9")]
    (mine / "new.py").write_text("x = 1\n")
    out = fake / "out3"
    assert go(out, "--no-guard", "--plugin-dir", str(mine)) == 0
    assert identity_of(grades_of(out)) == [(head, True, "9.9.9")]
    assert "uncommitted changes" in (results(out) / "summary.md").read_text()


def test_code_identity_is_unknown_without_a_readable_folder(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "trash")
    out = fake / "out"
    assert go(out, "--no-guard") == 0
    assert identity_of(grades_of(out)) == [(None, None, None)]
    assert "- Code under test: commit unknown, dirty state unknown" in (
        (results(out) / "summary.md").read_text()
    )
    bare = fake / "bare"
    bare.mkdir()
    assert r.code_identity(bare) == {"commit": None, "dirty": None, "plugin_version": None}
    assert r.code_identity(None)["commit"] is None


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


def test_a_capture_that_prints_no_id_is_a_setup_error(fake, monkeypatch):
    real = r.heuresis
    monkeypatch.setattr(r, "heuresis", lambda *a, **k: "" if a[0] == "capture" else real(*a, **k))
    out = fake / "out"
    assert go(out, "--no-guard", case=("bib-checker", "teleport")) == 0
    grades = grades_of(out)
    assert [g["case"] for g in grades] == ["bib-checker", "teleport"]
    assert all(g["error"] == "setup failed: capture printed no id" for g in grades)


def test_a_crashed_session_keeps_its_stderr(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "crash")
    out = fake / "out"
    assert go(out, "--no-guard") == 0
    stderr = results(out) / "logs" / "bib-checker-1.stderr"
    assert "fatal: session diagnostics" in stderr.read_text()


def test_plugin_path_is_the_entry_that_matches_plugin_dir(fake, monkeypatch):
    mine = fake / "mine"
    mine.mkdir()
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "two-plugins")
    monkeypatch.setenv("FAKE_PLUGIN_DIR", str(mine))
    out = fake / "out"
    assert go(out, "--no-guard", "--plugin-dir", str(mine)) == 0
    assert grades_of(out)[0]["plugin_path"] == str(mine)
    out = fake / "out2"
    assert go(out, "--no-guard") == 0
    assert grades_of(out)[0]["plugin_path"] == "/plugins/other"


def settings_of(argv: list[str]) -> dict | None:
    return json.loads(argv[argv.index("--settings") + 1]) if "--settings" in argv else None


def test_plugin_dir_disables_every_installed_heuresis(fake, monkeypatch):
    mine = fake / "mine"
    mine.mkdir()
    record = fake / "record.json"
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "two-plugins")
    monkeypatch.setenv("FAKE_PLUGIN_DIR", str(mine))
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    assert go(fake / "out", "--no-guard", "--plugin-dir", str(mine)) == 0
    argv = json.loads(record.read_text())["argv"]
    assert argv.count("--settings") == 1
    assert settings_of(argv) == {"enabledPlugins": {"heuresis@techne": False}}


def test_every_run_gets_the_settings_and_discovery_runs_once(fake, monkeypatch):
    mine = fake / "mine"
    mine.mkdir()
    calls = fake / "calls.log"
    real = r.subprocess.run

    def spy(cmd, *a, **k):
        if cmd[:3] == ["claude", "plugin", "list"]:
            calls.write_text(calls.read_text() + "x" if calls.exists() else "x")
        return real(cmd, *a, **k)

    monkeypatch.setattr(r.subprocess, "run", spy)
    seen = []
    real_session = r.run_session
    monkeypatch.setattr(
        r, "run_session", lambda cmd, *a: (seen.append(cmd), real_session(cmd, *a))[1]
    )
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "two-plugins")
    monkeypatch.setenv("FAKE_PLUGIN_DIR", str(mine))
    assert (
        go(fake / "out", "--no-guard", "--plugin-dir", str(mine), case=("bib-checker", "teleport"))
        == 0
    )
    assert calls.read_text() == "x"
    assert [settings_of(c) for c in seen] == [{"enabledPlugins": {"heuresis@techne": False}}] * 2


def test_without_plugin_dir_nothing_is_disabled_or_discovered(fake, monkeypatch):
    record = fake / "record.json"
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "trash")
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("FAKE_PLUGIN_LIST", "fail")
    assert go(fake / "out", "--no-guard") == 0
    assert "--settings" not in json.loads(record.read_text())["argv"]


def test_failed_discovery_warns_once_and_runs_without_settings(fake, monkeypatch, capsys):
    mine = fake / "mine"
    mine.mkdir()
    record = fake / "record.json"
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "two-plugins")
    monkeypatch.setenv("FAKE_PLUGIN_DIR", str(mine))
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("FAKE_PLUGIN_LIST", "fail")
    code = go(
        fake / "out", "--no-guard", "--plugin-dir", str(mine), case=("bib-checker", "teleport")
    )
    assert code == 0
    assert capsys.readouterr().err.count("warning") == 1
    assert "--settings" not in json.loads(record.read_text())["argv"]
    assert [g["error"] for g in grades_of(fake / "out")] == ["", ""]


def test_plugin_dir_that_did_not_load_is_an_error(fake, monkeypatch):
    mine = fake / "mine"
    mine.mkdir()
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "wrong-dir")
    out = fake / "out"
    assert go(out, "--no-guard", "--plugin-dir", str(mine)) == 0
    (g,) = grades_of(out)
    assert g["error"] == "heuresis plugin from --plugin-dir did not load"
    assert not g["accepted"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "no-plugin")
    out = fake / "out2"
    assert go(out, "--no-guard", "--plugin-dir", str(mine)) == 0
    assert grades_of(out)[0]["error"] == "heuresis plugin from --plugin-dir did not load"


def test_only_a_snapshot_failure_is_labelled_as_one(fake, monkeypatch, capsys):
    def broken(repo):
        raise RuntimeError("git write-tree failed")

    monkeypatch.setattr(r, "snapshot", broken)
    assert go(fake / "out", "--guard-repo", str(guard_repo(fake))) == 1
    assert "cannot snapshot the guard repository" in capsys.readouterr().err


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


SPAWN = (
    "import subprocess, sys, time\n"
    "c = subprocess.Popen(['sleep', '30'])\n"
    "open(sys.argv[1], 'w').write(str(c.pid))\n"
    "time.sleep(30)\n"
)


def interrupt_after_the_child_started(monkeypatch, pidfile: Path, exc: BaseException):
    """Make communicate raise exc once the session has started its child."""

    def interrupted(self, *args, **kwargs):
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text():
                break
            time.sleep(0.05)
        raise exc

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), RuntimeError("boom")])
def test_an_interrupted_session_is_killed_with_its_children(tmp_path, monkeypatch, exc):
    pidfile = tmp_path / "child.pid"
    interrupt_after_the_child_started(monkeypatch, pidfile, exc)
    cmd = [sys.executable, "-c", SPAWN, str(pidfile)]
    with pytest.raises(type(exc)):
        r.run_session(cmd, tmp_path, 60)
    monkeypatch.undo()  # alive() runs ps through subprocess.run, which calls communicate
    child = int(pidfile.read_text())
    for _ in range(50):
        if not alive(child):
            break
        time.sleep(0.1)
    assert not alive(child)


def test_an_interrupt_after_the_session_ended_still_propagates(tmp_path, monkeypatch):
    real = subprocess.Popen.communicate

    def finish_then_interrupt(self, *args, **kwargs):
        real(self, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess.Popen, "communicate", finish_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        r.run_session([sys.executable, "-c", "pass"], tmp_path, 60)


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


def tree_listing(root: Path) -> list[tuple[str, int]]:
    return sorted(
        (str(f.relative_to(root)), f.stat().st_size) for f in root.rglob("*") if f.is_file()
    )


def test_snapshot_writes_nothing_into_the_guarded_repository(tmp_path):
    repo = dirty_guard_repo(tmp_path)
    (repo / "fresh.md").write_text("content no object holds yet\n")
    before = tree_listing(repo / ".git")
    r.snapshot(repo)
    assert tree_listing(repo / ".git") == before


def test_snapshot_sees_local_config_hooks_and_info_changes(tmp_path):
    repo = dirty_guard_repo(tmp_path)
    base = r.snapshot(repo)
    git(repo, "config", "--local", "core.hooksPath", "/elsewhere")
    assert r.snapshot(repo) != base
    base = r.snapshot(repo)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    assert r.snapshot(repo) != base
    base = r.snapshot(repo)
    hook.chmod(0o755)
    assert r.snapshot(repo) != base
    base = r.snapshot(repo)
    hook.write_text("#!/bin/sh\nexit 1\n")
    assert r.snapshot(repo) != base
    base = r.snapshot(repo)
    (repo / ".git" / "info" / "exclude").write_text("# a different note\n")
    assert r.snapshot(repo) != base
    base = r.snapshot(repo)
    (repo / ".git" / "info" / "attributes").write_text("*.md text\n")
    assert r.snapshot(repo) != base
    assert r.snapshot(repo) == r.snapshot(repo)


def test_snapshot_of_a_linked_worktree_reads_the_shared_git_dir(tmp_path):
    repo = dirty_guard_repo(tmp_path)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "two")
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", str(linked), "-b", "side")
    base = r.snapshot(linked)
    (repo / ".git" / "hooks" / "post-merge").write_text("#!/bin/sh\n")
    assert r.snapshot(linked) != base


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


def run_once(fake, monkeypatch, name: str, mode: str, **kw) -> Path:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    out = fake / name
    assert go(out, "--no-guard", **kw) == 0
    return results(out)


def graded(path: Path) -> list[dict]:
    return [json.loads(x) for x in (path / "grades.jsonl").read_text().splitlines()]


def test_regrade_prefers_the_later_folder_only_when_it_did_not_fail(fake, monkeypatch, capsys):
    both = ("bib-checker", "teleport")
    failed = run_once(fake, monkeypatch, "o1", "crash", case=both, runs=2)
    good = run_once(fake, monkeypatch, "o2", "trash", case=("bib-checker",), runs=2)
    into = fake / "merged"
    capsys.readouterr()
    assert r.main(["regrade", str(failed), str(good), "--into", str(into)]) == 0
    assert capsys.readouterr().out.strip() == str(into / "summary.md")
    rows = graded(into)
    assert [(g["case"], g["run"], g["state"], g["error"]) for g in rows] == [
        ("bib-checker", 1, "trash", ""),
        ("bib-checker", 2, "trash", ""),
        ("teleport", 1, None, "claude exited 3"),
        ("teleport", 2, None, "claude exited 3"),
    ]
    assert rows[0]["accepted"] and rows[0]["cost_usd"] == 0.25
    assert rows[0]["plugin_path"] == "/plugins/heuresis"
    assert json.loads((into / "cases.json").read_text())["ids"] == ["bib-checker", "teleport"]
    md = (into / "summary.md").read_text()
    assert "- bib-checker run 1: [dokimasia: bibliography checks]" in md
    assert "(https://github.com/ajbarea/techne) (verified)" in md
    assert "- teleport run 1: error: claude exited 3" in md
    assert json.loads((into / "summary.json").read_text())["runs"] == 4
    # Argument order decides: a later folder that failed does not displace the earlier success.
    again = fake / "again"
    assert r.main(["regrade", str(good), str(failed), "--into", str(again)]) == 0
    assert [(g["case"], g["run"], g["error"]) for g in graded(again)][:2] == [
        ("bib-checker", 1, ""),
        ("bib-checker", 2, ""),
    ]


def rewrite_grades(res: Path, **changes) -> None:
    rows = [{**g, **changes} for g in graded(res)]
    (res / "grades.jsonl").write_text("".join(json.dumps(g) + "\n" for g in rows))


def test_regrade_reads_the_files_not_the_original_grade(fake, monkeypatch):
    res = run_once(fake, monkeypatch, "o1", "trash")
    rewrite_grades(res, state="do", accepted=False, closest_hit=False, closest_verified=False)
    into = fake / "merged"
    assert r.main(["regrade", str(res), "--into", str(into)]) == 0
    (g,) = graded(into)
    assert (g["state"], g["accepted"], g["closest_hit"], g["closest_verified"]) == (
        "trash",
        True,
        True,
        True,
    )


def test_regrade_carries_the_plugin_path_and_code_identity_of_the_original(fake, monkeypatch):
    res = run_once(fake, monkeypatch, "o1", "trash")
    rewrite_grades(res, commit="c" * 40, dirty=True, plugin_version="3.1.4")
    into = fake / "merged"
    assert r.main(["regrade", str(res), "--into", str(into)]) == 0
    (g,) = graded(into)
    assert g["plugin_path"] == "/plugins/heuresis"
    assert (g["commit"], g["dirty"], g["plugin_version"]) == ("c" * 40, True, "3.1.4")
    assert "- Code under test: cccccccccccc, uncommitted changes, plugin version 3.1.4" in (
        (into / "summary.md").read_text()
    )


def test_regrade_never_revives_a_run_that_recorded_an_error(fake, monkeypatch):
    res = run_once(fake, monkeypatch, "o1", "trash")
    rewrite_grades(res, error="timed out after 2s")
    into = fake / "merged"
    assert r.main(["regrade", str(res), "--into", str(into)]) == 0
    (g,) = graded(into)
    assert (g["state"], g["accepted"], g["error"]) == (None, False, "timed out after 2s")
    assert g["plugin_path"] == "/plugins/heuresis"


def test_regrade_makes_an_error_of_a_work_folder_with_no_grade_line(fake, monkeypatch, capsys):
    res = run_once(fake, monkeypatch, "o1", "trash")
    (res / "grades.jsonl").write_text("")
    into = fake / "merged"
    assert r.main(["regrade", str(res), "--into", str(into)]) == 0
    (g,) = graded(into)
    assert (g["state"], g["accepted"], g["error"]) == (None, False, "no grade recorded")
    assert g["prior_art_hit"] is False and g["plugin_path"] is None


def test_regrade_of_a_guard_tripped_run_does_not_grade_the_stopped_session(fake, monkeypatch):
    guard = guard_repo(fake)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "guard")
    monkeypatch.setenv("FAKE_CLAUDE_GUARD", str(guard))
    out = fake / "out"
    assert go(out, "--guard-repo", str(guard)) == 1
    into = fake / "merged"
    assert r.main(["regrade", str(results(out)), "--into", str(into)]) == 0
    (g,) = graded(into)
    assert (g["accepted"], g["error"]) == (False, "no grade recorded")


def test_regrade_needs_exactly_one_idea_file(fake, monkeypatch):
    res = run_once(fake, monkeypatch, "o1", "trash")
    ideas = res / "work" / "bib-checker-1" / "ideas" / "ideas"
    (ideas / "second.md").write_text((next(ideas.glob("2*.md"))).read_text())
    into = fake / "merged"
    assert r.main(["regrade", str(res), "--into", str(into)]) == 0
    (g,) = graded(into)
    assert g["state"] is None and "found 2" in g["error"]
    for f in ideas.glob("*.md"):
        f.unlink()
    again = fake / "again"
    assert r.main(["regrade", str(res), "--into", str(again)]) == 0
    assert "found 0" in graded(again)[0]["error"]


def test_regrade_refuses_a_folder_that_already_holds_grades_or_runs(fake, monkeypatch, capsys):
    res = run_once(fake, monkeypatch, "o1", "trash")
    other = run_once(fake, monkeypatch, "o2", "trash")
    only_work = fake / "only-work"
    (only_work / "work").mkdir(parents=True)
    for target in (other, only_work):
        assert r.main(["regrade", str(res), "--into", str(target)]) == 2
        assert "already holds" in capsys.readouterr().err
    into = fake / "merged"
    assert r.main(["regrade", str(res), "--into", str(into)]) == 0
    before = (into / "grades.jsonl").read_text()
    assert r.main(["regrade", str(res), "--into", str(into)]) == 2
    assert (into / "grades.jsonl").read_text() == before
    empty = fake / "empty"
    empty.mkdir()
    assert r.main(["regrade", str(res), "--into", str(empty)]) == 0


def test_regrade_warns_when_a_later_folder_replaces_a_good_grade(fake, monkeypatch, capsys):
    first = run_once(fake, monkeypatch, "o1", "trash")
    second = run_once(fake, monkeypatch, "o2", "trash")
    failed = run_once(fake, monkeypatch, "o3", "crash")
    capsys.readouterr()
    assert r.main(["regrade", str(first), str(second), "--into", str(fake / "m1")]) == 0
    err = capsys.readouterr().err
    assert "bib-checker run 1" in err and str(second) in err and str(first) in err
    assert "does not pool" in err
    assert len(graded(fake / "m1")) == 1
    assert r.main(["regrade", str(failed), str(first), "--into", str(fake / "m2")]) == 0
    assert "warning" not in capsys.readouterr().err
    assert r.main(["regrade", str(first), str(failed), "--into", str(fake / "m3")]) == 0
    assert "warning" not in capsys.readouterr().err
    assert graded(fake / "m3")[0]["error"] == ""


def edited_cases(fake: Path) -> Path:
    """A copy of the fixture cases the test may edit after a run recorded it."""
    path = fake / "cases.yaml"
    path.write_text(CASES.read_text())
    return path


def test_report_refuses_stale_labels_until_the_run_is_regraded(fake, monkeypatch, capsys):
    cases = edited_cases(fake)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "trash")
    out = fake / "out"
    argv = ["run", "--cases", str(cases), "--case", "bib-checker", "--runs", "1"]
    assert r.main([*argv, "--out", str(out), "--no-guard"]) == 0
    res = results(out)
    cases.write_text(cases.read_text().replace("expected_state: trash", "expected_state: later", 1))
    capsys.readouterr()
    assert r.main(["report", str(res)]) == 2
    err = capsys.readouterr().err
    assert "bib-checker run 1" in err and "regrade" in err
    into = fake / "fresh"
    assert r.main(["regrade", str(res), "--into", str(into)]) == 0
    assert graded(into)[0]["expected_state"] == "later"
    assert r.main(["report", str(into)]) == 0


def test_report_refuses_a_grade_line_from_before_labels_were_recorded(fake, monkeypatch, capsys):
    res = run_once(fake, monkeypatch, "o1", "trash")
    rows = graded(res)
    for g in rows:
        for key in ("expected_state", "kind", "labels"):
            del g[key]
    (res / "grades.jsonl").write_text("".join(json.dumps(g) + "\n" for g in rows))
    assert r.main(["report", str(res)]) == 2
    assert "bib-checker run 1" in capsys.readouterr().err


def test_case_pool_rejects_one_id_in_two_files_and_warns_about_a_missing_file(fake, capsys):
    twin = fake / "twin.yaml"
    twin.write_text(CASES.read_text())
    with pytest.raises(r.gold.GoldError, match="bib-checker"):
        r.case_pool([CASES, twin])
    assert [*r.case_pool([CASES, CASES])] == ["bib-checker", "teleport", "new-thing"]
    capsys.readouterr()
    assert "bib-checker" in r.case_pool([fake / "gone.yaml", CASES])
    assert "gone.yaml" in capsys.readouterr().err


def test_regrade_with_a_cases_file_when_the_recorded_one_is_gone(fake, monkeypatch):
    res = run_once(fake, monkeypatch, "o1", "trash")
    twin = fake / "twin.yaml"
    twin.write_text(CASES.read_text())
    meta = json.loads((res / "cases.json").read_text())
    (res / "cases.json").write_text(json.dumps({**meta, "files": [str(fake / "gone.yaml")]}))
    into = fake / "merged"
    assert r.main(["regrade", str(res), "--into", str(into)]) == 2
    assert r.main(["regrade", str(res), "--into", str(into), "--cases", str(twin)]) == 0
    assert graded(into)[0]["state"] == "trash"


def test_regrade_refuses_a_missing_folder_and_an_input_as_output(fake, monkeypatch, capsys):
    res = run_once(fake, monkeypatch, "o1", "trash")
    assert r.main(["regrade", str(fake / "nope"), "--into", str(fake / "m")]) == 2
    assert "results folder not found" in capsys.readouterr().err
    assert r.main(["regrade", str(res), str(fake / "nope"), "--into", str(fake / "m")]) == 2
    before = (res / "grades.jsonl").read_text()
    assert r.main(["regrade", str(res), "--into", str(res)]) == 2
    assert "one of the results folders" in capsys.readouterr().err
    assert (res / "grades.jsonl").read_text() == before
    assert not (fake / "m").exists()


def test_missing_claude_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert r.main(["run", "--cases", str(CASES), "--no-guard", "--out", str(tmp_path / "o")]) == 2
    assert "claude is not on PATH" in capsys.readouterr().err


def test_make_target_and_ignore_rule_exist():
    makefile = (ROOT / "Makefile").read_text()
    assert "heuresis-gold:" in makefile and "scripts/heuresis_gold.py run" in makefile
    assert '-n "$(GUARD)"' in makefile and '--guard-repo "$(GUARD)"' in makefile
    assert ".heuresis-gold/" in (ROOT / ".gitignore").read_text()


def test_duplicate_case_id_across_files_is_rejected(fake, capsys):
    twin = fake / "twin.yaml"
    twin.write_text(CASES.read_text())
    out = fake / "out"
    code = r.main(
        ["run", "--cases", str(CASES), "--cases", str(twin), "--no-guard", "--out", str(out)]
    )
    err = capsys.readouterr().err
    assert code == 2 and str(CASES) in err and str(twin) in err and "bib-checker" in err
    assert not out.exists()
