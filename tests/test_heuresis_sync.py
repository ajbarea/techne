"""publish: commit, rebase onto the remote, regenerate the board, push."""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest
from heuresis import board, store, sync
from heuresis.model import Idea

TODAY = dt.date(2026, 10, 15)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def configure(repo: Path) -> None:
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "commit.gpgsign", "false")


def clone_pair(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    a, b = tmp_path / "a", tmp_path / "b"
    for repo in (a, b):
        subprocess.run(
            ["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True
        )
        configure(repo)
    (a / "ideas").mkdir()
    board.write(a, TODAY)
    git(a, "add", "-A")
    git(a, "commit", "-qm", "init")
    git(a, "push", "-q", "origin", "main")
    git(b, "pull", "-q", "origin", "main")
    return a, b


def add(repo: Path, idea_id: str) -> list[Path]:
    i = Idea(
        id=idea_id,
        title=idea_id,
        captured="2026-10-15T00:00:00",
        captured_via="terminal",
        sections={"Idea": "x"},
    )
    return [store.save(repo, i)]


def test_publish_without_remote_commits_locally(tmp_path: Path):
    repo = tmp_path / "solo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    configure(repo)
    assert sync.publish(repo, add(repo, "a"), "capture a", TODAY) == "local"
    assert "capture a" in git(repo, "log", "--oneline")


def test_publish_to_an_empty_remote_pushes_and_sets_upstream(tmp_path: Path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    configure(repo)
    git(repo, "remote", "add", "origin", str(remote))
    assert sync.publish(repo, add(repo, "a"), "capture a", TODAY) == "pushed"
    assert "capture a" in git(remote, "log", "--oneline", "main")
    assert git(repo, "rev-parse", "--abbrev-ref", "main@{upstream}").strip() == "origin/main"


def test_publish_rebases_over_a_remote_change_and_regenerates_board(tmp_path: Path):
    a, b = clone_pair(tmp_path)
    assert sync.publish(b, add(b, "from-phone"), "capture from-phone", TODAY) == "pushed"
    assert sync.publish(a, add(a, "from-terminal"), "capture from-terminal", TODAY) == "pushed"
    git(b, "pull", "-q", "origin", "main")
    text = (b / "BOARD.md").read_text()
    assert "from-phone" in text and "from-terminal" in text


def test_conflicting_idea_edit_aborts_and_keeps_local_commit(tmp_path: Path):
    a, b = clone_pair(tmp_path)
    sync.publish(a, add(a, "same"), "capture same", TODAY)
    git(b, "pull", "-q", "origin", "main")
    (a / "ideas" / "same.md").write_text((a / "ideas" / "same.md").read_text() + "\nedit A\n")
    sync.publish(a, [a / "ideas" / "same.md"], "edit A", TODAY)
    (b / "ideas" / "same.md").write_text((b / "ideas" / "same.md").read_text() + "\nedit B\n")
    with pytest.raises(sync.SyncError, match=r"same\.md"):
        sync.publish(b, [b / "ideas" / "same.md"], "edit B", TODAY)
    assert "edit B" in git(b, "log", "--oneline", "-1")
    assert not (b / ".git" / "rebase-merge").exists()
