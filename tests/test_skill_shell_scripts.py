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
    env: dict[str, str] = {
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


def test_partial_stagings_of_one_file_differ(repo):
    """A plan made with one hunk staged must go stale when a different hunk is staged."""
    (repo / "c.txt").write_text("".join(f"{n}\n" for n in range(1, 11)))
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-qm", "c")
    (repo / "c.txt").write_text("X\n" + "".join(f"{n}\n" for n in range(2, 10)) + "Y\n")

    def stage(text: str) -> None:
        blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=repo,
            input=text,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        _git(repo, "update-index", "--cacheinfo", f"100644,{blob},c.txt")

    stage("X\n" + "".join(f"{n}\n" for n in range(2, 11)))
    first = _fp(repo)
    stage("".join(f"{n}\n" for n in range(1, 10)) + "Y\n")
    assert _fp(repo) != first


def test_untracked_nested_repo_is_hashed_not_fatal(repo):
    nested = repo / "nested"
    nested.mkdir()
    _git(nested, "init", "-q")
    assert len(_fp(repo)) == 12


def test_a_repo_with_no_commits_still_fingerprints(tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    _git(fresh, "init", "-q")
    empty = _fp(fresh)
    (fresh / "a.txt").write_text("a\n")
    assert _fp(fresh) != empty


def test_outside_a_repo_it_fails_without_printing_a_hash(tmp_path):
    done = subprocess.run(["bash", str(FINGERPRINT)], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode != 0
    assert done.stdout == ""


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
    """A private tmux server and HOME, so no live session or personal tmux.conf is touched."""
    session = f"techne-test-{uuid.uuid4().hex[:8]}"
    home = tmp_path / "home"
    home.mkdir()
    sock = tmp_path / "sock"
    sock.mkdir()
    env: dict[str, str] = {
        **os.environ,
        "THEOROS_STATE_DIR": str(tmp_path),
        "HOME": str(home),
        "TMUX_TMPDIR": str(sock),
    }
    env.pop("TMUX", None)
    (repo / ".claude").mkdir()

    def configure(extra: str = "", repl: str = "cat", name: str | None = None) -> None:
        (repo / ".claude" / "skill-context.md").write_text(
            "# ctx\n\n## theoros\n\n```yaml\n"
            f"repl_command: {repl}\nsession_name: {name or session}\n{extra}```\n\n## other\n"
        )

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(THEOROS), *args], cwd=repo, capture_output=True, text=True, env=env
        )

    def tmux(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["tmux", *args], capture_output=True, text=True, env=env)

    configure()
    yield session, configure, run, tmux, home
    if HAVE_TMUX:
        tmux("kill-server")


def _alive(tmux, session: str) -> bool:
    return tmux("has-session", "-t", f"={session}").returncode == 0


@needs_tmux
def test_up_status_down(theoros):
    session, _, run, tmux, _ = theoros
    up = run("up")
    assert up.returncode == 0, up.stderr
    assert _alive(tmux, session)
    status = json.loads(run("status").stdout)
    assert status["session"] == session
    assert status["ops_pane"] is None
    assert status["driver_pane"].startswith("%")
    assert run("down").returncode == 0
    assert not _alive(tmux, session)
    assert "No theoros session running" in run("status").stdout


@needs_tmux
def test_up_refuses_a_running_session(theoros):
    session, _, run, _, _ = theoros
    assert run("up").returncode == 0
    again = run("up")
    assert again.returncode == 1
    assert f"tmux attach -t {session} -r" in again.stderr


@needs_tmux
def test_panes_are_found_under_base_index_one(theoros):
    """The first review finding: a tmux.conf numbering from 1 broke the split and the ids."""
    session, configure, run, tmux, home = theoros
    (home / ".tmux.conf").write_text("set -g base-index 1\nsetw -g pane-base-index 1\n")
    configure("ops_command: cat\n")
    up = run("up")
    assert up.returncode == 0, up.stderr
    status = json.loads(run("status").stdout)
    panes = tmux("list-panes", "-t", f"={session}", "-F", "#{pane_id}").stdout.split()
    assert sorted(panes) == sorted([status["driver_pane"], status["ops_pane"]])


@needs_tmux
def test_failing_prerequisite_aborts_in_either_key_order(theoros):
    session, configure, run, tmux, _ = theoros
    for item in (
        '  - command: "false"\n    message: "Start the stack first."\n',
        '  - message: "Start the stack first."\n    command: "false"\n',
    ):
        configure("prerequisites:\n" + item)
        up = run("up")
        assert up.returncode == 1
        assert "Start the stack first." in up.stderr
        assert not _alive(tmux, session)


@needs_tmux
def test_quoted_values_are_unquoted(theoros):
    session, configure, run, tmux, _ = theoros
    configure(repl='"cat -u"', name=f'"{session}"')
    assert run("up").returncode == 0
    assert _alive(tmux, session)


@needs_tmux
def test_a_dotted_session_name_is_the_one_tmux_holds(theoros):
    """tmux turns "." into "_"; a repo slug like ajbarea.github.io used to orphan a session."""
    _, configure, run, tmux, _ = theoros
    configure(name="demo.site-theoros")
    up = run("up")
    assert up.returncode == 0, up.stderr
    assert json.loads(run("status").stdout)["session"] == "demo_site-theoros"
    assert run("down").returncode == 0
    assert not _alive(tmux, "demo_site-theoros")


@needs_tmux
def test_a_repl_that_exits_at_once_is_an_error_not_ready(theoros):
    _, configure, run, _, _ = theoros
    configure(repl="false")
    up = run("up")
    assert up.returncode == 1
    assert "exited" in up.stderr
    assert "No theoros session running" in run("status").stdout


@needs_tmux
def test_status_drops_a_state_file_whose_session_is_gone(theoros):
    session, _, run, tmux, _ = theoros
    assert run("up").returncode == 0
    tmux("kill-session", "-t", f"={session}")
    assert "stale" in run("status").stdout
    assert "No theoros session running." in run("status").stdout


@needs_tmux
def test_state_file_is_valid_json_for_awkward_paths(theoros, tmp_path):
    session, _, _, _, home = theoros
    odd = tmp_path / 'we"ird\\dir'
    odd.mkdir()
    _git(odd, "init", "-q")
    (odd / ".claude").mkdir()
    (odd / ".claude" / "skill-context.md").write_text(
        f"## theoros\n\n```yaml\nrepl_command: cat\nsession_name: {session}\n```\n"
    )
    env: dict[str, str] = {
        **os.environ,
        "THEOROS_STATE_DIR": str(tmp_path),
        "HOME": str(home),
        "TMUX_TMPDIR": str(tmp_path / "sock"),
    }
    env.pop("TMUX", None)
    up = subprocess.run(
        ["bash", str(THEOROS), "up"], cwd=odd, capture_output=True, text=True, env=env
    )
    assert up.returncode == 0, up.stderr
    status = subprocess.run(
        ["bash", str(THEOROS), "status"], cwd=odd, capture_output=True, text=True, env=env
    )
    assert json.loads(status.stdout)["cwd"] == str(odd)


def test_missing_required_field_fails_in_every_command(theoros, repo):
    _, _, run, _, _ = theoros
    (repo / ".claude" / "skill-context.md").write_text(
        "## theoros\n\n```yaml\nrepl_command: cat\n```\n"
    )
    for cmd in ("up", "status", "down"):
        done = run(cmd)
        assert done.returncode == 1, cmd
        assert "session_name" in done.stderr
