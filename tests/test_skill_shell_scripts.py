"""Tests for the shell scripts that skills ship: auto-commit's fingerprint and theoros.sh.

The theoros cases drive real tmux sessions under unique names. A runner without tmux
must set TECHNE_NO_TMUX=1 to say so; otherwise the suite fails instead of skipping the
lifecycle unseen.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS = ROOT / "plugins" / "techne" / "skills"
FINGERPRINT = SKILLS / "auto-commit" / "scripts" / "fingerprint.sh"
THEOROS = SKILLS / "theoros" / "scripts" / "theoros.sh"

NO_TMUX = os.environ.get("TECHNE_NO_TMUX") == "1"
HAVE_TMUX = shutil.which("tmux") is not None


def _git(repo: pathlib.Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    ).stdout


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "a.txt").write_text("a\n")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-qm", "init")
    return r


def _fp(cwd: pathlib.Path) -> str:
    out = subprocess.run(
        ["bash", str(FINGERPRINT)], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


# ------------------------------------------------------------- fingerprint --


def test_fingerprint_is_short_and_stable(repo):
    first = _fp(repo)
    assert len(first) == 12
    assert _fp(repo) == first


def test_writing_the_plan_does_not_make_it_stale(repo):
    before = _fp(repo)
    (repo / "COMMITS.md").write_text("plan\n")
    assert _fp(repo) == before


def test_a_new_untracked_file_makes_the_plan_stale(repo):
    """The bug this script replaced: `git diff HEAD | git hash-object` ignores untracked files."""
    before = _fp(repo)
    (repo / "new.py").write_text("x = 1\n")
    after_add = _fp(repo)
    assert after_add != before
    (repo / "new.py").write_text("x = 2\n")
    assert _fp(repo) != after_add


def test_tracked_and_staged_edits_change_it(repo):
    base = _fp(repo)
    (repo / "a.txt").write_text("b\n")
    edited = _fp(repo)
    assert edited != base
    _git(repo, "add", "a.txt")
    assert _fp(repo) != edited


def test_fingerprint_is_the_same_from_a_subdirectory(repo):
    (repo / "sub").mkdir()
    (repo / "sub" / "x.txt").write_text("x\n")
    assert _fp(repo / "sub") == _fp(repo)


# ----------------------------------------------------------------- theoros --


def test_tmux_is_present_or_the_opt_out_is_declared():
    assert HAVE_TMUX or NO_TMUX, (
        "tmux missing and TECHNE_NO_TMUX is unset: set TECHNE_NO_TMUX=1 to opt out"
    )


needs_tmux = pytest.mark.skipif(
    not HAVE_TMUX, reason="tmux unavailable (declared by TECHNE_NO_TMUX)"
)


@pytest.fixture
def theoros(repo, tmp_path):
    session = f"techne-test-{uuid.uuid4().hex[:8]}"
    ctx = repo / ".claude"
    ctx.mkdir()

    def configure(extra: str = "") -> None:
        (ctx / "skill-context.md").write_text(
            "# ctx\n\n## theoros\n\n```yaml\n"
            f"repl_command: cat\nsession_name: {session}\n{extra}```\n\n## other\n"
        )

    def run(*args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "THEOROS_STATE_DIR": str(tmp_path)}
        return subprocess.run(
            ["bash", str(THEOROS), *args], cwd=repo, capture_output=True, text=True, env=env
        )

    configure()
    yield session, configure, run, tmp_path / f"{session}.state"
    subprocess.run(["tmux", "kill-session", "-t", f"={session}"], capture_output=True)


def _alive(session: str) -> bool:
    return (
        subprocess.run(["tmux", "has-session", "-t", f"={session}"], capture_output=True).returncode
        == 0
    )


@needs_tmux
def test_up_status_down(theoros):
    session, _, run, state = theoros
    up = run("up")
    assert up.returncode == 0, up.stderr
    assert _alive(session)
    status = json.loads(run("status").stdout)
    assert status["session"] == session
    assert status["ops_pane"] is None
    assert run("down").returncode == 0
    assert not _alive(session)
    assert not state.exists()
    assert "No theoros session running" in run("status").stdout


@needs_tmux
def test_up_refuses_a_running_session(theoros):
    session, _, run, _ = theoros
    assert run("up").returncode == 0
    again = run("up")
    assert again.returncode == 1
    assert f"tmux attach -t {session} -r" in again.stderr


@needs_tmux
def test_ops_command_adds_a_second_pane(theoros):
    session, configure, run, _ = theoros
    configure("ops_command: cat\n")
    assert run("up").returncode == 0
    panes = subprocess.run(
        ["tmux", "list-panes", "-t", f"={session}"], capture_output=True, text=True
    ).stdout
    assert len(panes.strip().splitlines()) == 2
    assert json.loads(run("status").stdout)["ops_pane"] == f"{session}:0.1"


@needs_tmux
def test_failing_prerequisite_aborts_before_any_session(theoros):
    session, configure, run, _ = theoros
    configure('prerequisites:\n  - command: "false"\n    message: "Start the stack first."\n')
    up = run("up")
    assert up.returncode == 1
    assert "Start the stack first." in up.stderr
    assert not _alive(session)


def test_missing_required_field_names_it(theoros, repo):
    _, _, run, _ = theoros
    (repo / ".claude" / "skill-context.md").write_text(
        "## theoros\n\n```yaml\nsession_name: x\n```\n"
    )
    up = run("up")
    assert up.returncode == 1
    assert "repl_command" in up.stderr
