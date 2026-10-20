"""Tests for techne:sisters' hygiene survey and its clean mode.

The failure this script cannot recover from is deleting work: a branch with
commits nobody merged, a worktree another session is standing in, a branch that
moved between the plan being shown and being applied. Each test below builds
real repositories (a bare origin and a clone) so git itself decides ancestry,
and only the GitHub PR lookup is faked.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import HYGIENE_SCRIPT, ROOT

ME = "ajbarea"
NO_ISSUES = {"data": {"repository": {"issues": {"nodes": []}}}}


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
    monkeypatch.setattr(hy, "fetch_issue_links", lambda slug: NO_ISSUES)
    monkeypatch.setattr(hy, "canonical_slug", lambda slug: slug)
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


@pytest.mark.parametrize(
    ("setup", "flagged"),
    [
        ("stale", True),
        ("main-moved", True),  # main rewrote its IMPL.md after the branch left
        ("not-utf8", True),
        ("rewritten", False),
        ("squash-merged", False),  # main now carries the branch's own IMPL.md
        ("clean", False),
        ("recent", False),
        ("no-impl", False),
        ("detached", False),
        ("pr-merged", False),  # a finished branch's stray edits: held after merge instead
        ("unsure", False),  # too many ignored files to tell whether it is idle
    ],
)
def test_a_dirty_idle_worktree_that_never_described_itself_is_not_resumable(
    fleet, hy, monkeypatch, setup, flagged
):
    def on_main(text: bytes) -> None:
        (fleet.path / "IMPL.md").write_bytes(text)
        sh(fleet.path, "add", "IMPL.md")
        sh(fleet.path, "commit", "-q", "-m", "impl")
        sh(fleet.path, "push", "-q", "origin", "main")

    if setup != "no-impl":
        on_main(b"caf\xe9 slice\n" if setup == "not-utf8" else b"slice A\n")
    fleet.branch("feat/a")
    if setup == "detached":
        path = fleet.path / ".claude" / "worktrees" / "a"
        sh(fleet.path, "worktree", "add", "-q", "--detach", str(path), "main")
    else:
        path = add_worktree(fleet, "a", "feat/a")
    if setup != "clean":
        (path / "work.rs").write_text("unsaved")
    if setup == "rewritten":
        (path / "IMPL.md").write_text("Current slice: work.rs")
    elif setup == "squash-merged":
        commit(path, "IMPL.md")  # the branch's own IMPL.md, content "IMPL.md"
        on_main(b"IMPL.md")
    elif setup == "main-moved":
        on_main(b"slice B\n")
    elif setup == "recent":
        monkeypatch.setattr(hy, "IDLE_SECONDS", 3600)
    elif setup == "unsure":
        monkeypatch.setattr(hy, "ACTIVITY_FILE_CAP", 0)
        (fleet.path / ".git" / "info" / "exclude").write_text("build/\n")
        (path / "build").mkdir()
        (path / "build" / "out.o").write_text("x")
    elif setup == "pr-merged":
        fleet.prs["feat/a"] = pr(1, "MERGED", sh(fleet.path, "rev-parse", "feat/a"))
    item = fleet.survey()[("worktree", ".claude/worktrees/a")]
    assert (hy.UNRESUMABLE + "origin/main" in item.reason) is flagged, item.reason


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
        (".astro/", True),
        ("test-results/", True),
        ("playwright-report/", True),
        (".lighthouseci/", True),
        # A chrome-launcher profile needs the worktree to look inside: see the test below.
        ("lighthouse.80415069/", False),
        # husky ignores its own files, so git lists each one rather than the directory.
        (".husky/_/h", True),
        (".husky/_/pre-commit", True),
        (".husky/_", True),
        (".husky/_x", False),
        (".husky/pre-commit", False),
        ("a/.husky/_/h", False),
        ("notes/_/", False),
        # Root only: deeper, the name may be a person's folder.
        ("docs/test-results/", False),
        ("docs/test-results/notes.md", False),
        ("site-src/.astro/", False),
        ("COMMITS.md", False),
        (".env", False),
        (".superpowers/", False),
        (".claude/worktrees/", False),
    ],
)
def test_only_build_output_counts_as_regenerable(hy, path, expected):
    assert hy.regenerable(path) is expected


@pytest.mark.parametrize(
    ("entry", "folder", "profile", "expected"),
    [
        ("lighthouse.80415069/", "lighthouse.80415069", True, True),
        # Under WSL, git quotes the Windows temp path chrome-launcher meant as one folder name.
        (
            '"C:\\\\Users\\\\aj\\\\AppData\\\\Local\\\\lighthouse.80415069/"',
            "C:\\Users\\aj\\AppData\\Local\\lighthouse.80415069",
            True,
            True,
        ),
        ("lighthouse.20261018/", "lighthouse.20261018", False, False),  # dated reports folder
        ("lighthouse.202610181/", "lighthouse.202610181", True, False),
        ("lighthouse.2024/", "lighthouse.2024", True, False),
        ("docs/lighthouse.80415069/", "docs/lighthouse.80415069", True, False),
        ('"my thesis\\\\lighthouse.80415069/"', "my thesis\\lighthouse.80415069", True, False),
    ],
)
def test_a_lighthouse_profile_is_build_output_only_when_chrome_made_it(
    hy, tmp_path, entry, folder, profile, expected
):
    (tmp_path / folder).mkdir(parents=True)
    if profile:
        (tmp_path / folder / "Local State").write_text("{}")
    assert hy.regenerable(entry, str(tmp_path)) is expected
    assert hy.regenerable(entry) is False  # without the worktree there is nothing to check


@pytest.mark.parametrize(
    "body, said",
    [
        (None, "not found"),
        ("workspace_root = [", "not valid TOML"),
        ('workspace_root = "~/w"\n', "has no github_user"),
    ],
)
def test_bad_config_points_at_setup(hy, monkeypatch, tmp_path, body, said):
    path = tmp_path / "techne.toml"
    if body is not None:
        path.write_text(body)
    monkeypatch.setattr(hy, "TECHNE_TOML", path)
    with pytest.raises(SystemExit) as exc:
        hy.load_sisters([])
    assert said in str(exc.value) and "/techne:setup" in str(exc.value)


GOOD = (
    'workspace_root = "~/w x"\ngithub_user = "u"\n\n'
    '[[sisters]]\nname = "a"\n\n[[sisters]]\nname = "b"\nkind = "team"\n\n'
    '[[sisters]]\nname = "c"\nstatus = "retired"\n'
)


def run_env(tmp_path, body, script=HYGIENE_SCRIPT):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    if body is not None:
        (home / ".claude" / "techne.toml").write_text(body)
    return subprocess.run(
        [sys.executable, str(script), "--env"],
        env={"HOME": str(home), "PATH": str(tmp_path)},
        capture_output=True,
        text=True,
    )


def test_env_prints_the_audit_preamble_variables(tmp_path):
    proc = run_env(tmp_path, GOOD)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        "SISTERS='a b'",
        "TEAM_SISTERS=b",
        "WORKSPACE='~/w x'",
        "GITHUB_USER=u",
    ]


def test_a_team_kind_counts_in_any_case(tmp_path):
    """The same rule repo_kind.py applies, so the two readers agree on one roster entry."""
    proc = run_env(tmp_path, GOOD.replace('kind = "team"', 'kind = " Team "'))
    assert proc.returncode == 0, proc.stderr
    assert "TEAM_SISTERS=b" in proc.stdout.splitlines()


@pytest.mark.parametrize(
    "body, said",
    [
        (None, "not found"),
        ("workspace_root = [", "not valid TOML"),
        ('workspace_root = "~/w"\ngithub_user = "u"\n[[sisters]]\nx = 1\n', "no name"),
        ('workspace_root = "~/w"\ngithub_user = "u"\nsisters = "a"\n', "list of tables"),
        (
            'workspace_root = "~/w"\ngithub_user = "u"\n[[sisters]]\nname = "a"\nstatus = "off"\n',
            "no active",
        ),
    ],
)
def test_env_failures_are_one_line_with_the_setup_pointer(tmp_path, body, said):
    proc = run_env(tmp_path, body)
    assert proc.returncode == 1 and proc.stdout == ""
    assert "Traceback" not in proc.stderr
    assert said in proc.stderr and "/techne:setup" in proc.stderr


def test_a_sisters_entry_without_a_name_is_a_message_not_a_traceback(hy, monkeypatch, tmp_path):
    path = tmp_path / "techne.toml"
    path.write_text('workspace_root = "w"\ngithub_user = "u"\n[[sisters]]\nx = 1\n')
    monkeypatch.setattr(hy, "TECHNE_TOML", path)
    with pytest.raises(SystemExit) as exc:
        hy.load_sisters([])
    assert "no name" in str(exc.value)


def test_hygiene_leaves_no_bytecode_in_the_plugin(tmp_path):
    plugin = tmp_path / "techne"
    shutil.copytree(
        ROOT / "plugins" / "techne",
        plugin,
        ignore=shutil.ignore_patterns("__pycache__", "evals", "eval-fixtures"),
    )
    proc = run_env(tmp_path, GOOD, plugin / "skills" / "sisters" / "scripts" / "hygiene.py")
    assert proc.returncode == 0, proc.stderr
    assert not list(plugin.rglob("__pycache__"))


# ------------------------------------------------------------------ pdf --

DOCUMENT = "\\documentclass{article}\n\\begin{document}x\\end{document}\n"


def test_a_pdf_beside_its_document_is_build_output_and_nothing_else_is(hy, tmp_path):
    (tmp_path / "paper").mkdir()
    (tmp_path / "paper" / "main.tex").write_text(DOCUMENT)
    (tmp_path / "paper" / "fig.tex").write_text("\\begin{tikzpicture}\\end{tikzpicture}\n")
    root = str(tmp_path)
    assert hy.regenerable("paper/main.pdf", root) is True
    assert hy.regenerable("paper/fig.pdf", root) is False  # a fragment, not a document
    assert hy.regenerable("paper/other.pdf", root) is False  # no other.tex
    assert hy.regenerable("main.pdf", root) is False  # main.tex is in paper/, not here
    assert hy.regenerable("paper/main.pdf") is False  # no root, no evidence
    assert hy.regenerable("paper/main.docx", root) is False


def write_and_commit(path: Path, name: str, text: str) -> None:
    (path / name).write_text(text)
    sh(path, "add", name)
    sh(path, "commit", "-q", "-m", name)


def test_a_worktree_is_held_by_a_lone_pdf_but_not_by_one_beside_its_document(fleet):
    ignore(fleet, "*.pdf")
    for n, name in enumerate(("a", "b", "c"), 1):
        fleet.branch(f"feat/{name}")
        path = add_worktree(fleet, name, f"feat/{name}")
        if name == "a":
            write_and_commit(path, "main.tex", DOCUMENT)
        if name == "c":
            write_and_commit(path, "fig.tex", "\\draw (0,0);\n")
        (path / ("fig.pdf" if name == "c" else "main.pdf")).write_text("pdf")
        fleet.prs[f"feat/{name}"] = pr(n, "MERGED", sh(path, "rev-parse", "HEAD"))
    items = fleet.survey()
    assert items[("worktree", ".claude/worktrees/a")].group == "remove"
    for name in ("b", "c"):
        held = items[("worktree", f".claude/worktrees/{name}")]
        assert "ignored files that are not build output" in held.reason


# --------------------------------------------------------------- issues --


def issue_payload(*issues: dict) -> dict:
    return {"data": {"repository": {"issues": {"nodes": list(issues)}}}}


def closer(
    num: int = 5,
    merged: str | None = "2026-10-09T10:00:00Z",
    repo: str = "o/r",
    author: str = ME,
) -> dict:
    """One node of closedByPullRequestsReferences, as GitHub returns it after the merge."""
    return {
        "number": num,
        "merged": bool(merged),
        "mergedAt": merged,
        "baseRefName": "main",
        "author": {"login": author},
        "baseRepository": {"nameWithOwner": repo},
    }


def issue(
    number: int, *closers: dict, comment: str | None = None, reopened: str | None = None
) -> dict:
    return {
        "number": number,
        "comments": {"nodes": [{"createdAt": comment}] if comment else []},
        "reopened": {"nodes": [{"createdAt": reopened}] if reopened else []},
        "closedByPullRequestsReferences": {"nodes": list(closers)},
    }


NOW = "2026-10-18T00:00:00Z"


def stale(hy, payload: dict, slug: str = "o/r") -> list:
    return hy.stale_issues(payload, slug, hy.parse_time(NOW), ME)


def test_an_open_issue_a_day_after_its_closing_pr_merged_is_reported(hy):
    (item,) = stale(hy, issue_payload(issue(118, closer(114))))
    assert (item.kind, item.name, item.group) == ("issue", "#118", "review")
    assert item.reason == "PR #114 merged 2026-10-09; close it, or comment what is left"


@pytest.mark.parametrize(
    "bad",
    [
        issue(7),  # only mentioned: GitHub lists no closing PR
        issue(7, closer(merged="2026-10-17T12:00:00Z")),  # merged 12 h ago
        issue(7, closer(), comment="2026-10-10T00:00:00Z"),  # someone commented since
        issue(7, closer(), reopened="2026-10-12T00:00:00Z"),  # someone reopened it since
        issue(7, closer(merged=None)),  # the PR never merged
        issue(7, closer(repo="other/r")),
        issue(7, closer(author="someone-else")),
    ],
    ids=["mention-only", "too-recent", "commented", "reopened", "unmerged", "other-repo", "others"],
)
def test_issues_that_need_no_nudge_are_not_reported(hy, bad):
    assert stale(hy, issue_payload(bad)) == []


def test_activity_before_the_merge_does_not_silence_the_issue(hy):
    both = issue(7, closer(), comment="2026-10-08T00:00:00Z", reopened="2026-10-08T12:00:00Z")
    assert len(stale(hy, issue_payload(both))) == 1


def test_the_newest_merge_decides_when_several_prs_close_an_issue(hy):
    several = issue(
        7,
        closer(5, "2026-10-01T00:00:00Z"),
        closer(6, "2026-10-09T00:00:00Z"),
        comment="2026-10-05T00:00:00Z",
    )
    (item,) = stale(hy, issue_payload(several))
    assert "PR #6" in item.reason


def test_the_slug_compares_without_regard_to_case(hy):
    assert len(stale(hy, issue_payload(issue(7, closer(repo="O/R"))))) == 1


def test_issues_reach_the_survey_and_a_graphql_failure_does_not_stop_it(fleet, hy, monkeypatch):
    payload = issue_payload(issue(7, closer(repo=f"{ME}/repo", merged="2026-01-01T00:00:00Z")))
    monkeypatch.setattr(hy, "fetch_issue_links", lambda slug: payload)
    assert fleet.survey()[("issue", "#7")].group == "review"

    def boom(slug):
        raise RuntimeError("graphql down")

    fleet.branch("feat/a")
    monkeypatch.setattr(hy, "fetch_issue_links", boom)
    survey = fleet.survey()
    assert ("issue", "#7") not in survey
    assert ("local-branch", "feat/a") in survey


def test_the_issue_query_asks_for_what_the_parser_reads(hy):
    for field in ("closedByPullRequestsReferences(includeClosedPrs: true", "REOPENED_EVENT"):
        assert field in hy.ISSUE_QUERY
    assert "willCloseTarget" not in hy.ISSUE_QUERY


# ---------------------------------------------------------- landed PRs --


def land(fleet, name: str, *files: str) -> str:
    """Branch `name` on origin; returns its tip."""
    tip = fleet.branch(name, *files)
    sh(fleet.path, "push", "-q", "origin", name)
    return tip


def test_an_open_pr_whose_changes_main_already_has_is_reported(fleet):
    fleet.prs["feat/x"] = pr(3, "OPEN", land(fleet, "feat/x", "x1"))
    assert ("pr", "#3") not in fleet.survey()  # not in main yet
    commit(fleet.path, "x1")  # the same change reaches main as a different commit
    sh(fleet.path, "push", "-q", "origin", "main")
    item = fleet.survey()[("pr", "#3")]
    assert item.group == "review"
    assert "already in main" in item.reason


def test_a_pr_with_a_change_main_lacks_is_not_reported(fleet):
    fleet.prs["feat/x"] = pr(3, "OPEN", land(fleet, "feat/x", "x1", "x2"))
    commit(fleet.path, "x1")  # main has half of it
    sh(fleet.path, "push", "-q", "origin", "main")
    assert ("pr", "#3") not in fleet.survey()


def test_a_merged_pr_is_never_reported_as_landed(fleet):
    fleet.prs["feat/x"] = pr(3, "MERGED", land(fleet, "feat/x", "x1"))
    commit(fleet.path, "x1")
    sh(fleet.path, "push", "-q", "origin", "main")
    assert ("pr", "#3") not in fleet.survey()


def test_the_landed_check_is_skipped_on_a_git_without_merge_tree_write(fleet, hy, monkeypatch):
    fleet.prs["feat/x"] = pr(3, "OPEN", land(fleet, "feat/x", "x1"))
    commit(fleet.path, "x1")
    sh(fleet.path, "push", "-q", "origin", "main")
    monkeypatch.setattr(hy, "git_version", lambda: (2, 37))
    assert ("pr", "#3") not in fleet.survey()


# ----------------------------------------------------------------- auto --


@pytest.fixture
def auto(fleet, hy, monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setattr(hy.shutil, "which", lambda name: f"/usr/bin/{name}")

    class Auto:
        cache = tmp_path / "cache" / "techne"

        def __call__(self, interval: int = 0, paths: list[str] | None = None) -> str:
            return hy.run_auto(paths or [], [], interval)

    return Auto()


def test_auto_removes_a_finished_worktree_and_branch_and_holds_a_dirty_one(fleet, auto):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    fleet.prs["feat/b"] = pr(2, "MERGED", fleet.branch("feat/b", "b1"))
    a, b = add_worktree(fleet, "a", "feat/a"), add_worktree(fleet, "b", "feat/b")
    (b / "b1").write_text("edited")
    text = auto()
    assert not a.exists()
    assert "feat/a" not in local_branches(fleet.path)
    assert b.exists()
    assert "feat/b" in local_branches(fleet.path)
    assert "Removed (1):" in text
    assert "- repo: worktree `.claude/worktrees/a`: PR #1 merged" in text
    assert "Held after merge (1):" in text
    assert "worktree `.claude/worktrees/b`" in text
    assert "1 uncommitted change(s)" in text


def test_auto_lists_what_a_merge_left_behind_that_will_not_clear(fleet, auto):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    sh(fleet.path, "checkout", "-q", "feat/a")
    commit(fleet.path, "later")
    sh(fleet.path, "checkout", "-q", "main")
    fleet.prs["feat/c"] = pr(3, "CLOSED", fleet.branch("feat/c", "c1"))
    fleet.branch("feat/wip", "w1")  # no PR: not a merge leftover
    fleet.branch("feat/fresh")  # no PR, already in main, a session's uncommitted work in it
    fresh = add_worktree(fleet, "fresh", "feat/fresh")
    (fresh / "draft.md").write_text("in progress")
    text = auto()
    assert "Held after merge (1):" in text
    assert "local-branch `feat/a`: 1 commit(s) added after PR #1 merged" in text
    assert "Closed without merging (1):" in text
    assert "local-branch `feat/c`" in text
    assert "feat/wip" not in text
    assert "fresh" not in text
    assert fresh.exists()


def test_auto_reports_issues_and_landed_prs_without_acting_on_them(fleet, auto, hy, monkeypatch):
    payload = issue_payload(issue(7, closer(5, "2026-01-01T00:00:00Z", repo=f"{ME}/repo")))
    monkeypatch.setattr(hy, "fetch_issue_links", lambda slug: payload)
    fleet.prs["feat/x"] = pr(3, "OPEN", land(fleet, "feat/x", "x1"))
    commit(fleet.path, "x1")
    sh(fleet.path, "push", "-q", "origin", "main")
    text = auto()
    assert "issue `#7`: PR #5 merged 2026-01-01" in text
    assert "pr `#3`" in text
    assert "feat/x" in local_branches(fleet.path)
    assert "Removed" not in text


def test_auto_leaves_out_holds_that_clear_by_themselves(fleet, auto, hy, monkeypatch):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    monkeypatch.setattr(hy, "busy_paths", lambda: [str(path)])  # a session inside
    assert auto() == ""
    monkeypatch.setattr(hy, "busy_paths", lambda: [])
    monkeypatch.setattr(hy, "IDLE_SECONDS", 3600)  # recently active
    assert auto() == ""
    monkeypatch.setattr(hy, "busy_paths", lambda: None)  # cannot tell
    monkeypatch.setattr(hy, "IDLE_SECONDS", 0)
    assert auto() == ""
    monkeypatch.setattr(hy, "busy_paths", lambda: [])  # nothing transient: it goes
    assert "Removed (1):" in auto()
    assert not path.exists()


def test_a_lasting_hold_is_reported_even_while_a_session_is_in_the_worktree(
    fleet, auto, hy, monkeypatch
):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    (path / "a1").write_text("edited")
    monkeypatch.setattr(hy, "busy_paths", lambda: [str(path)])
    text = auto()
    assert "Held after merge (1):" in text
    assert "1 uncommitted change(s)" in text


def test_auto_never_removes_what_merely_sits_inside_main(fleet, auto):
    """A fresh `worktree add -b x origin/main` has no PR and is inside main; it is not finished."""
    sh(fleet.path, "branch", "fresh", "main")
    fresh = add_worktree(fleet, "fresh", "fresh")
    detached = fleet.path / ".claude" / "worktrees" / "det"
    sh(fleet.path, "worktree", "add", "-q", "--detach", str(detached), "main")
    items = fleet.survey()
    assert items[("worktree", ".claude/worktrees/fresh")].group == "remove"  # for --apply
    assert items[("worktree", ".claude/worktrees/det")].group == "remove"
    fleet.branch("old-no-pr")
    assert auto() == ""
    assert fresh.exists()
    assert detached.exists()
    assert {"fresh", "old-no-pr"} <= local_branches(fleet.path)


def test_a_worktree_missing_from_disk_is_pruned_by_auto(fleet, auto):
    fleet.branch("x")
    path = add_worktree(fleet, "gone", "x")
    shutil.rmtree(path)
    assert "worktree `.claude/worktrees/gone`" not in auto()  # pruned, listed as removed
    assert not sh(fleet.path, "worktree", "prune", "--dry-run", "-v")


def test_auto_prints_nothing_when_there_is_nothing_to_say(fleet, auto):
    fleet.prs["feat/open"] = pr(9, "OPEN", fleet.branch("feat/open", "o1"))
    assert auto() == ""


def test_auto_skips_quietly_while_another_run_holds_the_lock(fleet, auto):
    import fcntl

    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    auto.cache.mkdir(parents=True)
    with open(auto.cache / "hygiene-auto.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert auto() == ""
        assert path.exists()
    assert "Removed (1):" in auto()  # the lock was the only thing in the way
    assert not path.exists()


def test_auto_runs_at_most_once_per_interval(fleet, auto):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    first = add_worktree(fleet, "a", "feat/a")
    assert "Removed (1):" in auto(1800)
    fleet.prs["feat/b"] = pr(2, "MERGED", fleet.branch("feat/b", "b1"))
    second = add_worktree(fleet, "b", "feat/b")
    assert auto(1800) == ""
    assert second.exists()
    old = time.time() - 3600
    os.utime(auto.cache / "hygiene-auto.stamp", (old, old))
    assert "Removed (1):" in auto(1800)
    assert not first.exists()
    assert not second.exists()


def test_one_broken_repo_does_not_stop_the_others(fleet, auto, hy, monkeypatch, tmp_path):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    targets = [
        ("gone", f"{ME}/gone", str(tmp_path / "nowhere")),
        ("repo", f"{ME}/repo", str(fleet.path)),
    ]
    monkeypatch.setattr(hy, "load_sisters", lambda names: (targets, ME))
    assert "Removed (1):" in auto()
    assert not path.exists()


def test_a_worktree_a_session_entered_after_the_survey_is_kept(fleet, auto, hy, monkeypatch):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    real = hy.execute

    def late(repo, item):
        (path / "scratch").write_text("work")
        return real(repo, item)

    monkeypatch.setattr(hy, "execute", late)
    assert "Removed" not in auto()
    assert path.exists()


# --------------------------------------------------------------- --path --


def make_repo(tmp_path: Path, name: str, url: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    commit(repo, "base")
    sh(repo, "remote", "add", "origin", url)
    return repo


def test_a_path_resolves_to_its_repos_main_worktree_when_the_owner_is_mine(hy, fleet, tmp_path):
    mine = make_repo(tmp_path, "mine", f"git@github.com:{ME}/mine.git")
    sh(mine, "worktree", "add", "-q", str(mine / "wt"), "-b", "feat")
    found = hy.repo_for_path(str(mine / "wt"), ME, {})
    assert found == ("mine", f"{ME}/mine", str(mine.resolve()))
    assert hy.repo_for_path(str(mine), ME, {}) == found


def test_a_path_in_someone_elses_repo_counts_only_when_it_is_in_the_roster(hy, fleet, tmp_path):
    theirs = make_repo(tmp_path, "theirs", "https://github.com/other/theirs")
    assert hy.repo_for_path(str(theirs), ME, {}) is None
    found = hy.repo_for_path(str(theirs), ME, {str(theirs.resolve()): "theirs"})
    assert found == ("theirs", "other/theirs", str(theirs.resolve()))


def test_paths_that_are_not_a_github_repo_are_skipped_silently(hy, fleet, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    local = make_repo(tmp_path, "local", "/srv/git/local.git")
    assert hy.repo_for_path(str(plain), ME, {}) is None
    assert hy.repo_for_path(str(tmp_path / "missing"), ME, {}) is None
    assert hy.repo_for_path(str(local), ME, {}) is None


def test_auto_cleans_a_path_repo_that_is_not_in_the_roster(fleet, auto, hy, monkeypatch):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    monkeypatch.setattr(hy, "load_sisters", lambda names: ([], ME))
    monkeypatch.setattr(hy, "repo_for_path", lambda *a: ("repo", f"{ME}/repo", str(fleet.path)))
    assert "Removed (1):" in auto(paths=[str(fleet.path)])
    assert not path.exists()


# ----------------------------------------------------------------- hook --


def hook_args(**kw) -> SimpleNamespace:
    return SimpleNamespace(**{"path": [], "repo": [], "min_interval": 0, "hook": True} | kw)


REPORT = "Held after merge (1):\n- repo: worktree `w`: PR #1 merged; locked"


def test_hook_prints_the_session_start_shape_and_adds_the_sessions_cwd(hy, monkeypatch, capsys):
    seen = {}

    def fake(paths, names, interval):
        seen["paths"] = paths
        return REPORT

    monkeypatch.setattr(hy, "run_auto", fake)
    monkeypatch.setattr(hy.sys, "stdin", io.StringIO('{"cwd": "/work/repo", "source": "startup"}'))
    assert hy.auto_main(hook_args(path=["/extra"])) == 0
    assert seen["paths"] == ["/extra", "/work/repo"]
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == REPORT
    context = out["hookSpecificOutput"]
    assert context["hookEventName"] == "SessionStart"
    assert context["additionalContext"].startswith(REPORT)
    note = context["additionalContext"]
    assert "Investigate each held item" in note
    assert "Report what you find to the user" in note
    assert "say why it stays" not in note  # Claude must not be told to remove things unasked


def test_the_hook_note_is_added_only_when_something_is_held(hy):
    removed_only = "Removed (1):\n- repo: worktree `w`: PR #1 merged"
    out = json.loads(hy.hook_output(removed_only))
    assert out["hookSpecificOutput"]["additionalContext"] == removed_only
    for heading in ("Held after merge (1):\n- x", "Closed without merging (1):\n- x"):
        out = json.loads(hy.hook_output(heading))
        assert hy.HOOK_NOTE in out["hookSpecificOutput"]["additionalContext"]


def test_hook_prints_nothing_without_a_report_and_survives_bad_stdin(hy, monkeypatch, capsys):
    monkeypatch.setattr(hy, "run_auto", lambda paths, names, interval: "")
    monkeypatch.setattr(hy.sys, "stdin", io.StringIO("not json"))
    assert hy.auto_main(hook_args()) == 0
    assert capsys.readouterr().out == ""


def test_a_failing_run_never_reaches_the_hook(hy, monkeypatch, capsys):
    def boom(paths, names, interval):
        raise SystemExit("techne.toml not found")

    monkeypatch.setattr(hy, "run_auto", boom)
    monkeypatch.setattr(hy.sys, "stdin", io.StringIO("{}"))
    assert hy.auto_main(hook_args()) == 0
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")


def test_plain_auto_prints_the_report_as_text(hy, monkeypatch, capsys):
    monkeypatch.setattr(hy, "run_auto", lambda paths, names, interval: REPORT)
    assert hy.auto_main(hook_args(hook=False)) == 0
    assert capsys.readouterr().out == REPORT + "\n"


@pytest.mark.parametrize("flags", [["--auto"], ["--auto", "--hook"]])
def test_auto_without_gh_exits_zero_and_says_nothing(tmp_path, flags):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "techne.toml").write_text(GOOD)
    proc = subprocess.run(
        [sys.executable, str(HYGIENE_SCRIPT), *flags, "--min-interval", "0"],
        env={"HOME": str(home), "PATH": str(tmp_path / "empty"), "XDG_CACHE_HOME": str(tmp_path)},
        input="{}",
        capture_output=True,
        text=True,
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_auto_on_a_python_too_old_for_tomllib_exits_zero_and_says_nothing():
    def run(flag: str):
        code = (
            "import sys, runpy\n"
            "sys.version_info = (3, 9, 0)\n"
            f"sys.argv = [{str(HYGIENE_SCRIPT)!r}, {flag!r}]\n"
            f"runpy.run_path({str(HYGIENE_SCRIPT)!r}, run_name='__main__')\n"
        )
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    quiet = run("--auto")
    assert (quiet.returncode, quiet.stdout, quiet.stderr) == (0, "", "")
    told = run("--env")  # a person at a terminal still gets the fix
    assert told.returncode != 0
    assert "older than 3.11" in told.stderr


# ------------------------------------------------- unattended safety --


def age(path: Path, seconds: float = 86400) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_a_process_with_a_file_open_inside_a_worktree_makes_it_busy(fleet, hy):
    fleet.branch("feat/a")
    path = add_worktree(fleet, "a", "feat/a")
    (path / "logs").mkdir()
    with open(path / "logs" / "run.log", "w"):  # cwd elsewhere; an fd is all that ties it
        held = hy.process_paths()
    assert any(p.startswith(str(path)) for p in held)
    assert str(path) not in " ".join(hy.process_paths())  # closed again


def test_an_open_file_blocks_the_removal_although_the_cwd_is_elsewhere(fleet, hy, monkeypatch):
    ignore(fleet, "logs/")
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    (path / "logs").mkdir()
    monkeypatch.setattr(hy, "busy_paths", hy.process_paths)
    with open(path / "logs" / "run.log", "w"):
        item = fleet.survey()[("worktree", ".claude/worktrees/a")]
    assert item.group == "review"
    assert "a live process is using it" in item.reason


def make_idle(path: Path) -> None:
    gitdir = Path(sh(path, "rev-parse", "--absolute-git-dir"))
    for name in ("HEAD", "index"):
        age(gitdir / name)


def test_a_recent_write_to_an_ignored_file_counts_as_activity(fleet, hy, monkeypatch):
    ignore(fleet, "logs/")
    monkeypatch.setattr(hy, "IDLE_SECONDS", 3600)
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    (path / "logs").mkdir()
    log = path / "logs" / "run.log"
    log.write_text("x")
    make_idle(path)
    age(path / "logs")
    age(log)
    assert fleet.survey()[("worktree", ".claude/worktrees/a")].group == "remove"
    log.write_text("still writing")  # a process appends from elsewhere
    item = fleet.survey()[("worktree", ".claude/worktrees/a")]
    assert item.group == "review"
    assert "active 0 min ago" in item.reason


def test_a_capped_activity_walk_cannot_tell_and_holds_the_worktree(fleet, hy, monkeypatch):
    ignore(fleet, "logs/")
    fleet.branch("feat/a")
    path = add_worktree(fleet, "a", "feat/a")
    (path / "logs").mkdir()
    for n in range(3):
        age_file = path / "logs" / f"old{n}.log"
        age_file.write_text("x")
        age(age_file)
    make_idle(path)
    age(path / "logs")
    assert hy.last_activity(str(path), ["logs/"]) is not None
    monkeypatch.setattr(hy, "ACTIVITY_FILE_CAP", 2)
    assert hy.last_activity(str(path), ["logs/"]) is None
    item = fleet.survey()[("worktree", ".claude/worktrees/a")]
    assert item.group == "review"
    assert "to tell whether it was used recently" in item.reason
    assert not hy.transient([item.reason.split("; ", 1)[1]])  # reported, not silently retried


def test_a_large_environment_does_not_hide_a_fresh_log(fleet, hy, monkeypatch):
    """`.venv/` sorts before `logs/`; walking it first used to spend the whole file budget."""
    ignore(fleet, ".venv/", "logs/")
    monkeypatch.setattr(hy, "IDLE_SECONDS", 3600)
    monkeypatch.setattr(hy, "ACTIVITY_FILE_CAP", 50)
    fleet.branch("feat/a")
    path = add_worktree(fleet, "a", "feat/a")
    venv = path / ".venv" / "lib"
    venv.mkdir(parents=True)
    for n in range(200):
        (venv / f"m{n}.py").write_text("x")
    for p in [*venv.iterdir(), venv, venv.parent]:
        age(p)
    (path / "logs").mkdir()
    log = path / "logs" / "run.log"
    log.write_text("x")
    make_idle(path)
    age(path / "logs")
    age(log)
    assert fleet.survey()[("worktree", ".claude/worktrees/a")].group == "remove"
    log.write_text("still writing")
    item = fleet.survey()[("worktree", ".claude/worktrees/a")]
    assert item.group == "review"
    assert "active 0 min ago" in item.reason


def test_a_branch_taken_by_a_worktree_since_the_survey_is_not_deleted(fleet, hy):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    (repo,) = hy.survey(hy.load_sisters([])[0], ME)
    (item,) = [i for i in repo.items if i.kind == "local-branch"]
    add_worktree(fleet, "late", "feat/a")
    with pytest.raises(RuntimeError, match="checked out"):
        hy.execute(repo, item)
    assert "feat/a" in local_branches(fleet.path)


def test_every_removal_is_logged_before_it_happens(fleet, auto, hy, monkeypatch):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    seen = {}

    def spy(repo, item):
        seen["log"] = (auto.cache / "hygiene-auto.log").read_text()
        raise RuntimeError("stop before acting")

    monkeypatch.setattr(hy, "execute", spy)
    auto()
    assert path.exists()
    when, repo, kind, name, sha = seen["log"].strip().split("\t")
    assert (repo, kind, name) == ("repo", "worktree", ".claude/worktrees/a")
    assert sha == sh(path, "rev-parse", "HEAD")
    assert when


def test_the_report_names_the_log(fleet, auto):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    add_worktree(fleet, "a", "feat/a")
    assert f"logged in {auto.cache / 'hygiene-auto.log'}" in auto()


def test_a_crash_in_one_repo_keeps_the_earlier_removals_in_the_report(
    fleet, auto, hy, monkeypatch, tmp_path
):
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    real = hy.collect
    targets = [("repo", f"{ME}/repo", str(fleet.path)), ("two", f"{ME}/two", str(tmp_path))]
    monkeypatch.setattr(hy, "load_sisters", lambda names: (targets, ME))

    def collect(name, *a):
        if name == "two":
            raise KeyError("surprise")
        return real(name, *a)

    monkeypatch.setattr(hy, "collect", collect)
    assert "Removed (1):" in auto()
    assert not path.exists()


def spy_runs(hy, monkeypatch) -> list:
    calls = []
    real = subprocess.run

    def spy(cmd, *a, **kw):
        calls.append((cmd, kw))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(hy.subprocess, "run", spy)
    return calls


def repo_git_calls(calls) -> list:
    """git calls under --auto, less batch_ssh's own core.sshCommand lookup."""
    return [
        (c, kw)
        for c, kw in calls
        if c[:1] == ["git"] and kw.get("env") is not None and "core.sshCommand" not in c
    ]


def test_git_runs_with_a_timeout_and_without_prompts_under_auto(fleet, auto, hy, monkeypatch):
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.delenv("GIT_SSH", raising=False)
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    sh(fleet.path, "push", "-q", "origin", "feat/a")
    add_worktree(fleet, "a", "feat/a")
    calls = spy_runs(hy, monkeypatch)
    auto()
    ours = [(c, kw) for c, kw in calls if kw.get("env") is not None]
    assert ours
    assert all(kw["timeout"] for _, kw in ours)
    assert all(kw["env"]["GIT_TERMINAL_PROMPT"] == "0" for _, kw in ours)
    # Every git call, not only fetch and push: a partial clone fetches objects on demand.
    repo_calls = repo_git_calls(calls)
    assert any("push" in c for c, _ in repo_calls)
    assert all("BatchMode=yes" in kw["env"]["GIT_SSH_COMMAND"] for _, kw in repo_calls)
    calls.clear()
    hy.git(str(fleet.path), "status")  # outside --auto nothing changes for a person at a terminal
    assert calls[0][1]["timeout"] is None
    assert calls[0][1]["env"] is None


@pytest.mark.parametrize("where", ["GIT_SSH_COMMAND", "GIT_SSH", "core.sshCommand"])
def test_auto_keeps_the_users_ssh_command(fleet, auto, hy, monkeypatch, where):
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.delenv("GIT_SSH", raising=False)
    if where == "core.sshCommand":
        sh(fleet.path, "config", "core.sshCommand", "ssh -i work")
    else:
        monkeypatch.setenv(where, "ssh -i work")
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    sh(fleet.path, "push", "-q", "origin", "feat/a")
    add_worktree(fleet, "a", "feat/a")
    calls = spy_runs(hy, monkeypatch)
    auto()
    repo_calls = repo_git_calls(calls)
    assert any("push" in c for c, _ in repo_calls)
    expected = "ssh -i work" if where == "GIT_SSH_COMMAND" else None
    assert all(kw["env"].get("GIT_SSH_COMMAND") == expected for _, kw in repo_calls)


def test_auto_stops_at_its_deadline_and_still_releases_the_lock(fleet, auto, hy, monkeypatch):
    import fcntl

    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    path = add_worktree(fleet, "a", "feat/a")
    monkeypatch.setattr(hy, "AUTO_DEADLINE", -1)
    assert auto() == ""
    assert path.exists()
    assert hy._deadline is None
    with open(auto.cache / "hygiene-auto.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # free: the run let go


def test_the_lock_is_released_when_a_run_raises(fleet, auto, hy, monkeypatch):
    import fcntl

    def boom(*a):
        raise ValueError("surprise")

    monkeypatch.setattr(hy, "clean_targets", boom)
    with pytest.raises(ValueError):
        auto()
    assert hy._deadline is None
    with open(auto.cache / "hygiene-auto.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_the_interval_gates_the_roster_but_not_the_sessions_own_repo(fleet, auto, hy, monkeypatch):
    assert auto(1800) == ""  # an empty sweep; the stamp is now fresh
    fleet.prs["feat/a"] = pr(1, "MERGED", fleet.branch("feat/a", "a1"))
    a = add_worktree(fleet, "a", "feat/a")
    stamp = auto.cache / "hygiene-auto.stamp"
    old = time.time() - 600
    os.utime(stamp, (old, old))
    assert auto(1800) == ""  # the roster is not swept again
    assert a.exists()
    assert abs(stamp.stat().st_mtime - old) < 1  # and the clock was not restarted
    own = ("repo", f"{ME}/repo", str(fleet.path))
    monkeypatch.setattr(hy, "load_sisters", lambda names: ([], ME))
    monkeypatch.setattr(hy, "repo_for_path", lambda *a: own)
    assert "Removed (1):" in auto(1800, paths=[str(a)])
    assert not a.exists()


def test_only_the_users_open_prs_are_reported_as_landed(fleet):
    fleet.prs["feat/x"] = pr(3, "OPEN", land(fleet, "feat/x", "x1"), author="someone-else")
    commit(fleet.path, "x1")
    sh(fleet.path, "push", "-q", "origin", "main")
    assert ("pr", "#3") not in fleet.survey()


def test_a_transferred_repo_is_known_by_its_current_name(hy, fleet, tmp_path, monkeypatch):
    moved = make_repo(tmp_path, "moved", f"https://github.com/{ME}/ldqis.git")
    monkeypatch.setattr(hy, "canonical_slug", lambda slug: "ldqis/ldqis")
    assert hy.repo_for_path(str(moved), "someone", {}) is None  # owner is not them, not roster
    found = hy.repo_for_path(str(moved), "someone", {}, frozenset({"ldqis/ldqis"}))
    assert found == ("ldqis", "ldqis/ldqis", str(moved.resolve()))


def test_canonical_slug_reads_github_and_falls_back(hy, monkeypatch):
    monkeypatch.setattr(hy, "run", lambda cmd, **kw: '{"nameWithOwner": "ldqis/ldqis"}')
    assert hy.canonical_slug("ajbarea/ldqis") == "ldqis/ldqis"

    def offline(cmd, **kw):
        raise RuntimeError("no network")

    monkeypatch.setattr(hy, "run", offline)
    assert hy.canonical_slug("ajbarea/ldqis") == "ajbarea/ldqis"
