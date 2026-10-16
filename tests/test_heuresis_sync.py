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


def test_unrelated_staged_file_is_not_committed(tmp_path: Path):
    a, _ = clone_pair(tmp_path)
    (a / "notes.txt").write_text("private\n")
    git(a, "add", "notes.txt")
    assert sync.publish(a, add(a, "x"), "capture x", TODAY) == "pushed"
    assert "notes.txt" not in git(a, "show", "--name-only", "--format=", "origin/main")
    assert "notes.txt" in git(a, "diff", "--cached", "--name-only")


def test_unstaged_edit_with_unmoved_origin_pushes(tmp_path: Path):
    a, _ = clone_pair(tmp_path)
    sync.publish(a, add(a, "y"), "capture y", TODAY)
    y = a / "ideas" / "y.md"
    y.write_text(y.read_text() + "\nwip\n")
    assert sync.publish(a, add(a, "x"), "capture x", TODAY) == "pushed"
    assert "wip" in y.read_text()


def test_unstaged_edit_with_moved_origin_names_the_path_and_keeps_commit(tmp_path: Path):
    a, b = clone_pair(tmp_path)
    sync.publish(a, add(a, "y"), "capture y", TODAY)
    git(b, "pull", "-q", "origin", "main")
    sync.publish(b, add(b, "z"), "capture z", TODAY)
    y = a / "ideas" / "y.md"
    y.write_text(y.read_text() + "\nwip\n")
    with pytest.raises(sync.SyncError, match=r"uncommitted changes in ideas/y\.md"):
        sync.publish(a, add(a, "x"), "capture x", TODAY)
    assert "capture x" in git(a, "log", "--oneline", "-1")
    assert "wip" in y.read_text()


def test_rejected_push_that_is_not_a_race_fails_at_once(tmp_path: Path):
    a, _ = clone_pair(tmp_path)
    hook = tmp_path / "remote.git" / "hooks" / "pre-receive"
    count = tmp_path / "attempts"
    hook.write_text(f"#!/bin/sh\necho x >> {count}\necho 'branch is protected' >&2\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(sync.SyncError, match="branch is protected"):
        sync.publish(a, add(a, "x"), "capture x", TODAY)
    assert len(count.read_text().splitlines()) == 1
    assert "capture x" in git(a, "log", "--oneline", "-1")


def test_detached_head_is_refused_before_writing(tmp_path: Path):
    a, _ = clone_pair(tmp_path)
    git(a, "checkout", "-q", "--detach")
    paths = add(a, "x")
    with pytest.raises(sync.SyncError, match="HEAD is detached"):
        sync.publish(a, paths, "capture x", TODAY)
    assert "capture x" not in git(a, "log", "--oneline")


def test_rebase_in_progress_is_refused(tmp_path: Path):
    a, b = clone_pair(tmp_path)
    for repo, text in ((a, "from a\n"), (b, "from b\n")):
        (repo / "clash.txt").write_text(text)
        git(repo, "add", "clash.txt")
        git(repo, "commit", "-qm", "clash")
    git(a, "push", "-q", "origin", "main")
    git(b, "fetch", "-q", "origin", "main")
    subprocess.run(["git", "-C", str(b), "rebase", "origin/main"], capture_output=True)
    with pytest.raises(sync.SyncError, match="rebase or merge is in progress"):
        sync.publish(b, add(b, "x"), "capture x", TODAY)
    assert "capture x" not in git(b, "log", "--oneline", "--all")


def test_cherry_pick_in_progress_is_refused(tmp_path: Path):
    a, _ = clone_pair(tmp_path)
    (a / ".git" / "CHERRY_PICK_HEAD").write_text(git(a, "rev-parse", "HEAD"))
    with pytest.raises(sync.SyncError, match="cherry-pick or revert is in progress"):
        sync.publish(a, add(a, "x"), "capture x", TODAY)


def test_first_push_losing_a_race_falls_through_to_rebase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    a, b = clone_pair(tmp_path)
    assert sync.publish(b, add(b, "from-b"), "capture from-b", TODAY) == "pushed"
    real = sync._git

    def blind_ls_remote(root: Path, *args: str, **kw):
        if args[:1] == ("ls-remote",):
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return real(root, *args, **kw)

    monkeypatch.setattr(sync, "_git", blind_ls_remote)
    assert sync.publish(a, add(a, "from-a"), "capture from-a", TODAY) == "pushed"
    log = git(tmp_path / "remote.git", "log", "--oneline", "main")
    assert "capture from-a" in log and "capture from-b" in log


def test_remote_not_named_origin_counts_as_local(tmp_path: Path):
    a, _ = clone_pair(tmp_path)
    git(a, "remote", "rename", "origin", "github")
    assert sync.publish(a, add(a, "x"), "capture x", TODAY) == "local"


def test_non_main_branch_is_refused(tmp_path: Path):
    a, _ = clone_pair(tmp_path)
    git(a, "checkout", "-q", "-b", "topic")
    with pytest.raises(sync.SyncError, match="publishes from main; current branch is topic"):
        sync.publish(a, add(a, "x"), "capture x", TODAY)
