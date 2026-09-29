"""Tests for techne:sisters' hygiene survey and its clean mode.

The failure this script cannot recover from is deleting work: a branch with
commits nobody merged, a worktree another session is standing in, a branch that
moved between the plan being shown and being applied. Each test below builds
real repositories (a bare origin and a clone) so git itself decides ancestry,
and only the GitHub PR lookup is faked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ME = "ajbarea"


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(cwd: Path, name: str) -> str:
    (cwd / name).write_text(name)
    sh(cwd, "add", name)
    sh(cwd, "commit", "-q", "-m", name)
    return sh(cwd, "rev-parse", "HEAD")


def pr(number: int, state: str, head: str, author: str = ME, base: str = "main") -> dict:
    return {
        "number": number,
        "state": state,
        "headRefOid": head,
        "baseRefName": base,
        "author": {"login": author},
    }


@pytest.fixture
def fleet(tmp_path, monkeypatch, hy):
    """A clone of a bare origin, idle and unobserved unless a test says otherwise."""
    for key, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
    }.items():
        monkeypatch.setenv(key, value)
    origin, clone = tmp_path / "origin.git", tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    sh(clone, "checkout", "-q", "-b", "main")
    commit(clone, "base")
    sh(clone, "push", "-q", "-u", "origin", "main")
    sh(clone, "remote", "set-head", "origin", "main")

    monkeypatch.setattr(hy, "busy_paths", lambda: [])
    monkeypatch.setattr(hy, "default_branch", lambda slug: "main")
    monkeypatch.setattr(hy, "IDLE_SECONDS", 0)
    monkeypatch.setattr(
        hy, "load_sisters", lambda names: ([("repo", f"{ME}/repo", str(clone))], ME)
    )

    class Fleet:
        path = clone

        def __init__(self) -> None:
            self.prs: dict[str, dict] = {}

        def branch(self, name: str, *files: str) -> str:
            sh(clone, "checkout", "-q", "-b", name, "main")
            tip = sh(clone, "rev-parse", "HEAD")
            for f in files:
                tip = commit(clone, f)
            sh(clone, "checkout", "-q", "main")
            return tip

        def survey(self) -> dict[tuple[str, str], object]:
            (repo,) = hy.survey(hy.load_sisters([])[0], ME)
            assert not repo.error, repo.error
            return {(i.kind, i.name): i for i in repo.items}

        def plan(self, tmp: Path) -> Path:
            (repo,) = hy.survey(hy.load_sisters([])[0], ME)
            remove = [
                {"repo": "repo", "kind": i.kind, "name": i.name, "sha": i.sha}
                for i in repo.items
                if i.group == "remove"
            ]
            out = tmp / "plan.json"
            out.write_text(json.dumps({"remove": remove}))
            return out

    f = Fleet()
    monkeypatch.setattr(hy, "fetch_prs", lambda slug: f.prs)
    return f


def local_branches(path: Path) -> set[str]:
    return set(sh(path, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split())


# ------------------------------------------------------------- branches --


def test_a_squash_merged_branch_is_removable_although_main_lacks_its_commits(fleet):
    tip = fleet.branch("feat/a", "a1", "a2")
    fleet.prs["feat/a"] = pr(1, "MERGED", tip)
    item = fleet.survey()[("local-branch", "feat/a")]
    assert (item.group, item.reason) == ("remove", "PR #1 merged")


def test_commits_added_after_the_merge_hold_the_branch(fleet):
    merged = fleet.branch("feat/a", "a1")
    fleet.prs["feat/a"] = pr(1, "MERGED", merged)
    sh(fleet.path, "checkout", "-q", "feat/a")
    commit(fleet.path, "later")
    sh(fleet.path, "checkout", "-q", "main")
    item = fleet.survey()[("local-branch", "feat/a")]
    assert item.group == "review"
    assert "1 commit(s) added after PR #1 merged" in item.reason


def test_a_tip_the_pr_head_contains_is_finished(fleet):
    early = fleet.branch("feat/a", "a1")
    sh(fleet.path, "checkout", "-q", "feat/a")
    head = commit(fleet.path, "a2")
    sh(fleet.path, "checkout", "-q", "main")
    sh(fleet.path, "update-ref", "refs/heads/feat/a", early)  # local copy is behind the PR
    fleet.prs["feat/a"] = pr(1, "MERGED", head)
    assert fleet.survey()[("local-branch", "feat/a")].group == "remove"


def test_a_pr_head_that_is_not_in_the_clone_holds_the_branch(fleet):
    tip = fleet.branch("feat/a", "a1")
    fleet.prs["feat/a"] = pr(1, "MERGED", "0" * 40)
    assert tip
    item = fleet.survey()[("local-branch", "feat/a")]
    assert (item.group, item.reason) == ("review", "tip differs from PR #1's head")


def test_a_closed_unmerged_pr_is_for_a_person_to_decide(fleet):
    fleet.prs["feat/a"] = pr(1, "CLOSED", fleet.branch("feat/a", "a1"))
    assert fleet.survey()[("local-branch", "feat/a")].group == "review"


def test_an_open_pr_is_information_not_a_problem(fleet):
    fleet.prs["feat/a"] = pr(1, "OPEN", fleet.branch("feat/a", "a1"))
    assert fleet.survey()[("local-branch", "feat/a")].group == "info"


def test_a_branch_with_no_pr_and_unmerged_commits_is_held(fleet):
    fleet.branch("wip", "w1", "w2")
    item = fleet.survey()[("local-branch", "wip")]
    assert (item.group, item.reason) == ("review", "no PR; 2 commit(s) not in main")


def test_a_branch_with_no_pr_already_in_main_is_removable(fleet):
    fleet.branch("spent")
    assert fleet.survey()[("local-branch", "spent")].group == "remove"


def test_a_branch_checked_out_in_the_main_checkout_is_held(fleet):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    sh(fleet.path, "checkout", "-q", "feat/a")
    item = fleet.survey()[("local-branch", "feat/a")]
    assert item.group == "review"
    assert "checked out in the main checkout" in item.reason


# ------------------------------------------------------------ worktrees --


def add_worktree(fleet, name: str, branch: str) -> Path:
    path = fleet.path / ".claude" / "worktrees" / name
    sh(fleet.path, "worktree", "add", "-q", str(path), branch)
    return path


def test_a_clean_idle_worktree_on_a_merged_branch_is_removable(fleet):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    add_worktree(fleet, "a", "feat/a")
    items = fleet.survey()
    assert items[("worktree", ".claude/worktrees/a")].group == "remove"
    assert ("local-branch", "feat/a") not in items  # goes with its worktree


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("dirty", "1 uncommitted change(s)"),
        ("busy", "a live process is using it"),
        ("recent", "active 0 min ago"),
        ("locked", "locked"),
    ],
)
def test_a_worktree_someone_may_be_using_is_held(fleet, hy, monkeypatch, setup, expected):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    if setup == "dirty":
        (path / "a1").write_text("edited")
    elif setup == "busy":
        monkeypatch.setattr(hy, "busy_paths", lambda: [str(path / "src")])
    elif setup == "recent":
        monkeypatch.setattr(hy, "IDLE_SECONDS", 3600)
    else:
        sh(fleet.path, "worktree", "lock", str(path))
    item = fleet.survey()[("worktree", ".claude/worktrees/a")]
    assert item.group == "review"
    assert expected in item.reason


def test_a_detached_worktree_with_its_own_commits_is_held(fleet):
    path = fleet.path / ".claude" / "worktrees" / "preview"
    sh(fleet.path, "worktree", "add", "-q", "--detach", str(path), "main")
    commit(path, "local-merge")
    assert fleet.survey()[("worktree", ".claude/worktrees/preview")].group == "review"


def test_a_worktree_whose_directory_is_gone_is_pruned(fleet):
    import shutil

    fleet.branch("x")
    path = add_worktree(fleet, "gone", "x")
    shutil.rmtree(path)
    assert fleet.survey()[("prune", ".claude/worktrees/gone")].group == "remove"


# --------------------------------------------------------- remote, info --


def test_a_merged_remote_branch_is_removable_only_when_it_is_yours(fleet):
    for name, author in (("mine", ME), ("theirs", "someone-else")):
        tip = fleet.branch(name, name)
        sh(fleet.path, "push", "-q", "origin", name)
        sh(fleet.path, "branch", "-q", "-D", name)
        fleet.prs[name] = pr(1, "MERGED", tip, author)
    items = fleet.survey()
    assert items[("remote-branch", "mine")].group == "remove"
    assert items[("remote-branch", "theirs")].group == "review"


def test_stashes_and_a_dirty_main_checkout_are_reported_not_touched(fleet):
    (fleet.path / "base").write_text("stashed")
    sh(fleet.path, "stash", "push", "-q", "-m", "keep me")
    (fleet.path / "base").write_text("uncommitted")
    items = fleet.survey()
    assert items[("stash", "stash@{0}")].group == "info"
    assert "keep me" in items[("stash", "stash@{0}")].reason
    assert items[("dirty-main", "main")].group == "info"


# ----------------------------------------------------------------- apply --


def test_apply_removes_exactly_what_was_approved(fleet, hy, tmp_path, capsys):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    fleet.prs["feat/b"] = pr(2, "MERGED", fleet.branch("feat/b", "b1"))
    wt = add_worktree(fleet, "b", "feat/b")
    tip = fleet.branch("remote-only", "r1")
    sh(fleet.path, "push", "-q", "origin", "remote-only")
    sh(fleet.path, "branch", "-q", "-D", "remote-only")
    fleet.prs["remote-only"] = pr(3, "MERGED", tip)
    fleet.branch("wip", "w1")

    assert hy.apply(fleet.plan(tmp_path)) == 0
    assert local_branches(fleet.path) == {"main", "wip"}
    assert not wt.exists()
    assert sh(fleet.path, "ls-remote", "--heads", "origin", "remote-only") == ""


def test_apply_keeps_a_branch_that_moved_after_the_plan(fleet, hy, tmp_path, capsys):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    plan = fleet.plan(tmp_path)
    sh(fleet.path, "checkout", "-q", "feat/a")
    commit(fleet.path, "late")
    sh(fleet.path, "checkout", "-q", "main")

    assert hy.apply(plan) == 0
    assert "feat/a" in local_branches(fleet.path)
    assert "no longer safe or it moved" in capsys.readouterr().out


def test_apply_keeps_a_worktree_that_became_dirty(fleet, hy, tmp_path):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    wt = add_worktree(fleet, "a", "feat/a")
    plan = fleet.plan(tmp_path)
    (wt / "notes.txt").write_text("new work")

    assert hy.apply(plan) == 0
    assert (wt / "notes.txt").exists()
    assert "feat/a" in local_branches(fleet.path)


def test_the_remote_delete_is_leased_on_the_planned_tip(fleet, hy):
    tip = fleet.branch("r", "r1")
    sh(fleet.path, "push", "-q", "origin", "r")
    other = fleet.branch("r2", "r2")
    sh(fleet.path, "push", "-q", "--force", "origin", "r2:r")  # someone pushed since
    repo = hy.Repo("repo", f"{ME}/repo", str(fleet.path))
    item = hy.Item("remote-branch", "r", "remove", "", sha=tip)
    with pytest.raises(RuntimeError):
        hy.execute(repo, item)
    assert sh(fleet.path, "ls-remote", "--heads", "origin", "r").split()[0] == other


def test_a_file_created_between_survey_and_removal_stops_the_removal(fleet, hy):
    tip = fleet.branch("feat/a", "a1")
    wt = add_worktree(fleet, "a", "feat/a")
    (wt / "notes.txt").write_text("written after the survey")
    repo = hy.Repo("repo", f"{ME}/repo", str(fleet.path))
    item = hy.Item("worktree", "a", "remove", "", sha=tip, path=str(wt), branch="feat/a")
    with pytest.raises(RuntimeError):
        hy.execute(repo, item)
    assert (wt / "notes.txt").exists()


# ------------------------------------------------- regressions from review --


def test_a_remote_branch_with_no_pr_is_never_removed_even_inside_main(fleet):
    sh(fleet.path, "push", "-q", "origin", "main:develop")  # a long-lived branch, or a teammate's
    item = fleet.survey()[("remote-branch", "develop")]
    assert (item.group, item.reason) == ("review", "no PR")


def test_a_pr_merged_into_another_branch_is_not_finished(fleet):
    fleet.prs["feat/child"] = pr(2, "MERGED", fleet.branch("feat/child", "c1"), base="feat/parent")
    item = fleet.survey()[("local-branch", "feat/child")]
    assert item.group == "review"
    assert "merged into feat/parent, not main" in item.reason


def ignore(fleet, *patterns: str) -> None:
    (fleet.path / ".gitignore").write_text("\n".join(patterns) + "\n")
    sh(fleet.path, "add", ".gitignore")
    sh(fleet.path, "commit", "-q", "-m", "ignore")
    sh(fleet.path, "push", "-q", "origin", "main")


def test_ignored_work_holds_a_worktree_but_build_output_does_not(fleet):
    ignore(fleet, "COMMITS.md", ".venv/", "site/")
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    fleet.prs["feat/b"] = pr(2, "MERGED", fleet.branch("feat/b", "b1"))
    a, b = add_worktree(fleet, "a", "feat/a"), add_worktree(fleet, "b", "feat/b")
    (a / "COMMITS.md").write_text("plan")
    for d in (b / ".venv" / "lib", b / "site"):
        d.mkdir(parents=True)
        (d / "x").write_text("x")
    items = fleet.survey()
    held = items[("worktree", ".claude/worktrees/a")]
    assert held.group == "review"
    assert "ignored files that are not build output: COMMITS.md" in held.reason
    assert items[("worktree", ".claude/worktrees/b")].group == "remove"


def test_a_worktree_holding_another_worktree_is_held(fleet):
    ignore(fleet, ".claude/worktrees/")
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    outer = add_worktree(fleet, "a", "feat/a")
    fleet.branch("inner")
    sh(fleet.path, "worktree", "add", "-q", str(outer / ".claude" / "worktrees" / "n"), "inner")
    item = fleet.survey()[("worktree", ".claude/worktrees/a")]
    assert item.group == "review"
    assert "1 worktree(s) inside it" in item.reason


def test_a_config_hiding_untracked_files_does_not_hide_them_here(fleet):
    sh(fleet.path, "config", "status.showUntrackedFiles", "no")
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    wt = add_worktree(fleet, "a", "feat/a")
    (wt / "untracked_work.py").write_text("x = 1")
    item = fleet.survey()[("worktree", ".claude/worktrees/a")]
    assert item.group == "review"
    assert "1 uncommitted change(s)" in item.reason


def test_a_platform_that_cannot_list_working_directories_holds_every_worktree(
    fleet, hy, monkeypatch
):
    monkeypatch.setattr(hy, "busy_paths", lambda: None)
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    add_worktree(fleet, "a", "feat/a")
    item = fleet.survey()[("worktree", ".claude/worktrees/a")]
    assert "cannot tell whether a process is using it" in item.reason


def test_apply_checks_a_worktree_again_just_before_removing_it(fleet, hy, monkeypatch, tmp_path):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    wt = add_worktree(fleet, "a", "feat/a")
    item = next(i for i in fleet.survey().values() if i.kind == "worktree")
    monkeypatch.setattr(hy, "busy_paths", lambda: [str(wt)])  # a session arrives
    repo = hy.Repo("repo", f"{ME}/repo", str(fleet.path))
    with pytest.raises(RuntimeError, match="a live process is using it"):
        hy.execute(repo, item)
    assert wt.exists()


def test_an_open_pr_outranks_a_newer_closed_one_on_the_same_branch(hy, monkeypatch):
    listed = [
        {"number": 9, "state": "CLOSED", "headRefName": "b", "isCrossRepository": False},
        {"number": 4, "state": "OPEN", "headRefName": "b", "isCrossRepository": False},
        {"number": 3, "state": "MERGED", "headRefName": "c", "isCrossRepository": False},
        {"number": 7, "state": "MERGED", "headRefName": "c", "isCrossRepository": False},
        {"number": 8, "state": "OPEN", "headRefName": "d", "isCrossRepository": True},
    ]
    monkeypatch.setattr(hy, "run", lambda cmd: json.dumps(listed))
    prs = hy.fetch_prs("o/r")
    assert (prs["b"]["number"], prs["c"]["number"]) == (4, 7)
    assert "d" not in prs


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".venv/", True),
        ("pkg/__pycache__/", True),
        ("paper/main.aux", True),
        (".bibcache.json", True),
        ("mutants/", True),
        ("COMMITS.md", False),
        (".env", False),
        (".superpowers/", False),
        (".claude/worktrees/", False),
    ],
)
def test_only_build_output_counts_as_regenerable(hy, path, expected):
    assert hy.regenerable(path) is expected
