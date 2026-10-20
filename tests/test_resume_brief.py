"""Tests for techne's opt-in resume_brief SessionStart hook and its shared resume_state module.

The hook's job is to tell a fresh session, after a restart, /clear or compaction, where the
branch's work stands. The failures that matter: a brief that misses uncommitted work or a
stale IMPL.md, output past Claude Code's 10,000-character context cap, and a hook that
prints or fails outside a repo or on an old python3. `make test-hooks-oldest` runs this file
with TECHNE_GUARD_PYTHON set to 3.9.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import HOOK_PYTHON, ROOT

PLUGIN = ROOT / "plugins" / "techne"
SCRIPT = PLUGIN / "hooks" / "resume_brief.py"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
CAP = 10_000
IMPL = "# IMPL\n\nCurrent slice: the base work.\n"


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(cwd: Path, name: str, text: str = "") -> None:
    (cwd / name).write_text(text or name)
    sh(cwd, "add", name)
    sh(cwd, "commit", "-q", "-m", f"add {name}")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A clone of a bare origin whose main carries IMPL.md."""
    for key, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
    }.items():
        monkeypatch.setenv(key, value)
    origin, clone = tmp_path / "origin.git", tmp_path / "proj"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    sh(clone, "checkout", "-q", "-b", "main")
    commit(clone, "IMPL.md", IMPL)
    sh(clone, "push", "-q", "-u", "origin", "main")
    sh(clone, "remote", "set-head", "origin", "main")
    return clone


def worktree(repo: Path, name: str) -> Path:
    path = repo / ".claude" / "worktrees" / name
    sh(repo, "worktree", "add", "-q", str(path), "-b", f"feat/{name}", "origin/main")
    return path


def run(cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess:
    payload = json.dumps({"cwd": str(cwd), "source": "startup"}) if stdin is None else stdin
    return subprocess.run(
        [HOOK_PYTHON, str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def context(cwd: Path) -> str | None:
    proc = run(cwd)
    assert (proc.returncode, proc.stderr) == (0, "")
    if not proc.stdout:
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    return out["additionalContext"]


def test_outside_a_repo_it_says_nothing(tmp_path):
    assert context(tmp_path) is None


def test_a_repo_that_keeps_no_impl_says_nothing(repo):
    sh(repo, "rm", "-q", "IMPL.md")
    sh(repo, "commit", "-q", "-m", "drop")
    assert context(repo) is None


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"cwd": 3}'])
def test_bad_hook_input_falls_back_to_the_working_directory(repo, stdin):
    proc = run(repo, stdin)
    assert (proc.returncode, proc.stderr) == (0, "")
    assert "Current slice: the base work." in proc.stdout


def test_the_default_branch_points_new_work_at_a_branch(repo):
    text = context(repo)
    assert text is not None
    assert "for `proj`, branch `main`" in text
    assert "Uncommitted: nothing" in text
    assert "Pushed: origin/main is up to date (as of the last fetch)" in text
    assert "Start new work on a branch in its own worktree" in text
    assert "Commits past" not in text and "unchanged since" not in text
    assert text.endswith("Current slice: the base work.")


def test_a_branch_that_never_described_itself_is_flagged_with_its_diff(repo):
    wt = worktree(repo, "faces")
    (wt / "src").mkdir()
    (wt / "src" / "geometry.rs").write_text("fn main() {}")
    (wt / "IMPL.md").write_text(IMPL)  # touched, but identical
    text = context(wt / "src")  # the session starts in a subfolder
    assert text is not None
    assert "for `proj`, branch `feat/faces`" in text  # the repo, not the worktree folder
    assert "Commits past origin/main: 0" in text
    assert "Uncommitted: 1 path(s)" in text and "src/" in text
    assert "Pushed: never" in text
    assert "IMPL.md: unchanged since this branch left origin/main" in text
    assert "IMPL.md (as inherited, not this branch's):" in text
    assert "rewrite what the slice is" in text


def test_a_branch_with_its_own_impl_lists_commits_and_what_is_unpushed(repo):
    wt = worktree(repo, "launch")
    commit(wt, "IMPL.md", "# IMPL\n\nCurrent slice: launch sessions.\n")
    sh(wt, "push", "-q", "-u", "origin", "feat/launch")
    commit(wt, "launch.sh")
    text = context(wt)
    assert text is not None
    assert "Commits past origin/main: 2 (newest first)" in text
    assert "add launch.sh" in text and "add IMPL.md" in text
    assert "Pushed: to origin/feat/launch, 1 commit(s) not pushed yet (as" in text
    assert "unchanged since" not in text
    assert text.endswith("Current slice: launch sessions.")


def test_an_uncommitted_impl_rewrite_counts_as_described(repo):
    wt = worktree(repo, "draft")
    (wt / "IMPL.md").write_text("# IMPL\n\nCurrent slice: a draft.\n")
    text = context(wt)
    assert text is not None
    assert "unchanged since" not in text
    assert "Current slice: a draft." in text


def test_a_branch_missing_the_impl_main_keeps_is_told_to_write_one(repo):
    wt = worktree(repo, "gone")
    sh(wt, "rm", "-q", "IMPL.md")
    text = context(wt)
    assert text is not None
    assert "IMPL.md: missing here although origin/main has one" in text


def test_a_huge_impl_and_status_stay_under_the_context_cap(repo):
    wt = worktree(repo, "big")
    (wt / "IMPL.md").write_text("# IMPL\n\n" + "a long line of notes\n" * 2000)
    for i in range(40):
        (wt / f"f{i:02}.txt").write_text("x")
    text = context(wt)
    assert text is not None
    assert len(text) < CAP
    assert "Uncommitted: 41 path(s)" in text and "and 26 more (`git status`)" in text
    assert text.endswith("[... cut here; read IMPL.md for the rest]")


def test_many_commits_are_capped_with_a_count_of_the_rest(repo):
    wt = worktree(repo, "long")
    for i in range(13):
        commit(wt, f"c{i:02}")
    text = context(wt)
    assert text is not None
    assert "Commits past origin/main: 13" in text and "and 3 older" in text


def test_a_detached_head_is_named_by_its_commit(repo):
    sh(repo, "checkout", "-q", "--detach")
    text = context(repo)
    assert text is not None
    assert "detached HEAD at" in text and "Pushed:" not in text


def test_it_leaves_no_bytecode_in_the_plugin(repo):
    before = set(PLUGIN.rglob("__pycache__"))
    subprocess.run(
        [HOOK_PYTHON, str(SCRIPT)],
        input=json.dumps({"cwd": str(repo)}),
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"},
        check=True,
    )
    assert set(PLUGIN.rglob("__pycache__")) == before


def _handler() -> dict:
    groups = json.loads(HOOKS_JSON.read_text())["hooks"]["SessionStart"]
    (handler,) = [h for g in groups for h in g["hooks"] if "resume_brief.py" in h["command"]]
    return handler


def run_handler(cwd: Path, on: bool) -> str:
    shell = _handler()["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    shell = shell.replace("exec python3 ", f"exec {HOOK_PYTHON} ")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PLUGIN_OPTION_")}
    if on:
        env["CLAUDE_PLUGIN_OPTION_RESUME_BRIEF"] = "true"
    proc = subprocess.run(
        ["sh", "-c", shell],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert (proc.returncode, proc.stderr) == (0, "")
    return proc.stdout


def test_the_hook_runs_only_when_switched_on(repo):
    assert run_handler(repo, on=False) == ""
    assert "Resume brief (techne)" in run_handler(repo, on=True)


def test_the_hook_is_synchronous_and_fires_on_every_fresh_context():
    groups = json.loads(HOOKS_JSON.read_text())["hooks"]["SessionStart"]
    (group,) = [g for g in groups if "resume_brief.py" in json.dumps(g)]
    assert set(group["matcher"].split("|")) == {"startup", "resume", "clear", "compact"}
    assert not _handler().get("async")


def test_main_moving_on_does_not_hide_a_branch_that_never_described_itself(repo):
    wt = worktree(repo, "old")
    commit(repo, "IMPL.md", "# IMPL\n\nCurrent slice: the next merged work.\n")
    sh(repo, "push", "-q", "origin", "main")
    sh(wt, "fetch", "-q", "origin")
    (wt / "work.rs").write_text("x")
    text = context(wt)
    assert text is not None
    assert "unchanged since this branch left origin/main" in text


def test_after_its_squash_merge_a_branch_is_not_told_to_describe_itself(repo):
    wt = worktree(repo, "done")
    mine = "# IMPL\n\nCurrent slice: done.\n"
    commit(wt, "IMPL.md", mine)
    (repo / "IMPL.md").write_text(mine)  # the squash merge: same text, its own commit
    sh(repo, "commit", "-q", "-am", "squash of feat/done")
    sh(repo, "push", "-q", "origin", "main")
    sh(wt, "fetch", "-q", "origin")
    text = context(wt)
    assert text is not None
    assert "unchanged since" not in text


def test_an_impl_that_is_not_utf8_is_compared_not_crashed_on(repo):
    (repo / "IMPL.md").write_bytes(b"caf\xe9 slice\n")
    sh(repo, "commit", "-q", "-am", "latin-1")
    sh(repo, "push", "-q", "origin", "main")
    wt = worktree(repo, "enc")
    (wt / "work.rs").write_text("x")
    text = context(wt)
    assert text is not None
    assert "unchanged since this branch left origin/main" in text


def test_a_pushed_branch_with_commits_this_worktree_lacks_says_so(repo, tmp_path):
    wt = worktree(repo, "two")
    sh(wt, "push", "-q", "-u", "origin", "feat/two")
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "-q", "-b", "feat/two", str(repo.parent / "origin.git"), str(other)],
        check=True,
    )
    commit(other, "elsewhere.txt")
    sh(other, "push", "-q", "origin", "feat/two")
    sh(wt, "fetch", "-q", "origin")
    text = context(wt)
    assert text is not None
    assert "1 commit(s) there are not here: pull before you build on it" in text


def test_a_bare_repo_with_worktrees_is_named_by_its_repo(tmp_path, repo):
    bare = tmp_path / "proj2.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(bare)], check=True)
    wt = tmp_path / "wt"
    sh(bare, "worktree", "add", "-q", str(wt), "main")
    text = context(wt)
    assert text is not None
    assert "for `proj2`" in text


@pytest.fixture
def hook(monkeypatch):
    """The hook script as a module, importing the plugin's resume_state."""
    monkeypatch.syspath_prepend(str(PLUGIN / "_shared"))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("resume_brief_hook", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "resume_brief_hook", mod)
    spec.loader.exec_module(mod)
    return mod


def test_a_git_failure_reads_as_unknown_not_as_a_clean_tree(repo, hook, monkeypatch):
    real = hook.resume_state.git

    def failing(root, *args):
        return None if args[0] in ("status", "rev-list") else real(root, *args)

    wt = worktree(repo, "slow")
    monkeypatch.setattr(hook.resume_state, "git", failing)
    text = hook.brief(hook.resume_state.read(str(wt)))
    assert "Uncommitted: unknown" in text
    assert "Commits past origin/main: unknown" in text
    assert "ahead and behind unknown" not in text  # never pushed, so nothing to count
    assert "Uncommitted: nothing" not in text


def test_the_read_budget_stops_git_once_spent(repo, hook, monkeypatch):
    monkeypatch.setattr(hook.resume_state, "READ_BUDGET", 0)
    assert hook.resume_state.read(str(repo)) is None  # not even the toplevel is read
    assert hook.resume_state._deadline is None  # and the budget does not leak into later calls
