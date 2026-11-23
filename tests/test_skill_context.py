"""Tests for _shared/skill_context.sh, which every skill uses to load the target repo's context."""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESOLVER = ROOT / "plugins" / "techne" / "_shared" / "skill_context.sh"


def _repo(path: pathlib.Path, marker: str | None) -> pathlib.Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if marker is not None:
        (path / ".claude").mkdir()
        (path / ".claude" / "skill-context.md").write_text(f"## {marker}\n")
    (path / "docs").mkdir()
    (path / "docs" / "README.md").write_text("x\n")
    return path


@pytest.fixture
def repos(tmp_path):
    return _repo(tmp_path / "here", "HERE"), _repo(tmp_path / "there", "THERE")


def _fenced(cwd: pathlib.Path, env: dict[str, str] | None = None) -> dict[str, str]:
    """Stop git discovery at the test's tmp root, whatever repo encloses it."""
    root = next(p for p in [cwd, *cwd.parents] if p.name.startswith("test_"))
    return {**(env or os.environ), "GIT_CEILING_DIRECTORIES": str(root.parent)}


def _run(cwd: pathlib.Path, *args: str, env: dict[str, str] | None = None) -> str:
    env = _fenced(cwd, env)
    return subprocess.run(
        ["bash", str(RESOLVER), *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout


def test_no_argument_reads_the_cwd_repo(repos):
    here, _ = repos
    out = _run(here)
    assert "## HERE" in out
    assert out.splitlines()[0] == f"<!-- skill-context: {here} -->"


def test_subdirectory_cwd_still_finds_the_repo_root(repos):
    here, _ = repos
    assert "## HERE" in _run(here / "docs")


@pytest.mark.parametrize("target", ["docs/README.md", "docs", "."])
def test_path_in_another_repo_reads_that_repo(repos, target):
    here, there = repos
    out = _run(here, str(there / target))
    assert "## THERE" in out
    assert "## HERE" not in out


def test_relative_path_into_another_repo(repos):
    here, _ = repos
    assert "## THERE" in _run(here, "../there/docs/README.md")


@pytest.mark.parametrize("missing", ["docs/READM.md", "docs/new/dir/file.md", "notyet.md"])
def test_missing_path_in_another_repo_resolves_its_nearest_parent(repos, missing):
    here, there = repos
    out = _run(here, str(there / missing))
    assert "## THERE" in out


def test_cdpath_does_not_corrupt_the_fallback_root(tmp_path):
    loose = tmp_path / "loose"
    (loose / "docs").mkdir(parents=True)
    env = {**os.environ, "CDPATH": f".:{tmp_path}"}
    out = _run(loose, "docs", env=env)
    assert out == f"(no .claude/skill-context.md in {loose / 'docs'})\n"


@pytest.mark.parametrize("arg", ["42", "high"])
def test_bare_word_falls_back_to_cwd_silently(repos, arg):
    here, _ = repos
    out = _run(here, arg)
    assert out.startswith(f"<!-- skill-context: {here} -->")
    assert "## HERE" in out


@pytest.mark.parametrize(
    "arg", ["~/velocity-fl/README.md", "velocty-fl/README.md", "fix/some-branch"]
)
def test_unresolvable_path_warns_before_falling_back(repos, arg):
    here, _ = repos
    out = _run(here, arg)
    assert out.splitlines()[0] == f"(target {arg} not found; showing the current directory's repo)"
    assert "## HERE" in out


@pytest.mark.parametrize("inside", [".git", ".git/hooks"])
def test_path_inside_git_dir_resolves_its_work_tree(repos, inside):
    here, there = repos
    assert "## THERE" in _run(here, str(there / inside))


def test_repo_without_context_names_the_root(repos, tmp_path):
    here, _ = repos
    bare = _repo(tmp_path / "bare", None)
    out = _run(here, str(bare))
    assert out.startswith("(no .claude/skill-context.md in ")
    assert str(bare) in out


def test_directory_outside_any_repo(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    out = _run(loose)
    assert out.startswith("(no .claude/skill-context.md in ")
    assert str(loose) in out


def test_exported_git_dir_does_not_redirect_resolution(repos):
    """A git hook exports GIT_DIR; the resolver must still follow the target path."""
    here, there = repos
    env = {**os.environ, "GIT_DIR": str(here / ".git"), "GIT_WORK_TREE": str(here)}
    assert "## THERE" in _run(here, str(there / "docs"), env=env)


# The load-time line is inlined in each skill because a `bash <script>` injection fails
# the permission check outside bypass mode, while a read-only cat passes. It must stay
# identical everywhere and keep resolving the git root. It cannot carry the resolver's
# `env -u GIT_DIR` guard or a variable assignment: both fail that check too.
LOAD_LINE = (
    'echo "<!-- skill-context: $(git rev-parse --show-toplevel 2>/dev/null || pwd) -->"; '
    'cat "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.claude/skill-context.md" '
    '2>/dev/null || echo "(no .claude/skill-context.md in this repo)"'
)
PLUGINS = ROOT / "plugins"
LOADING_SKILLS = {
    "audit", "ci-audit", "deslop", "docs-site", "elenchus", "logging", "reslop", "theoros"
}  # fmt: skip


def _injection_lines() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for skill in sorted(PLUGINS.glob("*/skills/*/SKILL.md")):
        blocks = skill.read_text(encoding="utf-8").split("```!\n")[1:]
        lines = [b.split("\n```", 1)[0] for b in blocks]
        hits = [ln for ln in lines if "skill-context.md" in ln]
        if hits:
            found[skill.parent.name] = hits
    return found


def test_every_skill_uses_the_canonical_load_line():
    found = _injection_lines()
    assert set(found) == LOADING_SKILLS
    for name, lines in found.items():
        assert lines == [LOAD_LINE], name


FALLBACK = (
    "If the block above appears as a command rather than its output, run it and use what it prints."
)


def test_every_inline_block_tells_other_agents_to_run_it():
    for skill in sorted(PLUGINS.glob("*/skills/*/SKILL.md")):
        for after in skill.read_text(encoding="utf-8").split("```!\n")[1:]:
            tail = after.split("\n```\n", 1)[1]
            assert tail.lstrip("\n").startswith(FALLBACK), skill


def _load(cwd: pathlib.Path) -> str:
    return subprocess.run(
        ["bash", "-c", LOAD_LINE],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=_fenced(cwd),
    ).stdout


def test_load_line_reads_the_root_from_a_subdirectory(repos):
    here, _ = repos
    out = _load(here / "docs")
    assert out.splitlines()[0] == f"<!-- skill-context: {here} -->"
    assert "## HERE" in out


def test_load_line_outside_a_repo(tmp_path):
    out = _load(tmp_path)
    assert out.splitlines() == [
        f"<!-- skill-context: {tmp_path} -->",
        "(no .claude/skill-context.md in this repo)",
    ]


def test_suite_runs_without_an_inherited_git_repo():
    """A hook-exported GIT_DIR would make a test's `git init` hit the real repo."""
    from conftest import GIT_REPO_VARS

    assert not [var for var in GIT_REPO_VARS if var in os.environ]


def test_no_skill_reads_context_relative_to_the_working_directory():
    for skill in PLUGINS.glob("*/skills/*/SKILL.md"):
        assert "cat .claude/skill-context.md" not in skill.read_text(encoding="utf-8"), skill


def _git(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=a@example.com", "-c", "user.name=A", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=_fenced(cwd),
    )


def _pr_clone(
    tmp_path: pathlib.Path, default: str = "main", base_file: bool = True, remote: str = "origin"
) -> pathlib.Path:
    """A clone of a repo whose DEFAULT branch holds BASE_RULES (or no file), on a PR branch
    whose two commits soften the hints, with a third softening left in the working tree."""
    up = tmp_path / "up"
    up.mkdir()
    _git(up, "init", "-q", "-b", default)
    (up / ".claude").mkdir()
    if base_file:
        (up / ".claude" / "skill-context.md").write_text("## BASE_RULES\n")
    (up / "README").write_text("x\n")
    _git(up, "add", ".")
    _git(up, "commit", "-qm", "base")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", "-o", remote, str(up), str(clone))
    _git(clone, "checkout", "-q", "-b", "pr")
    for n in (1, 2):
        (clone / ".claude").mkdir(exist_ok=True)
        (clone / ".claude" / "skill-context.md").write_text(f"## SOFT{n}\n")
        _git(clone, "add", ".")
        _git(clone, "commit", "-qm", f"soften {n}")
    (clone / ".claude" / "skill-context.md").write_text("## SOFT3\n")
    return clone


def _sha(repo: pathlib.Path, rev: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", rev],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_fenced(repo),
    ).stdout.strip()


def _says_no(out: str) -> bool:
    return out.startswith("(") and "SOFT" not in out and "BASE_RULES" not in out


@pytest.mark.parametrize(
    ("setup", "args", "ref"),
    [
        ({}, ["--base=origin/main"], "refs/remotes/origin/main"),
        ({}, ["--base"], "refs/remotes/origin/main"),
        ({}, ["--base=refs/remotes/origin/main"], "refs/remotes/origin/main"),
        ({"default": "master"}, ["--base"], "refs/remotes/origin/master"),
        ({"remote": "upstream"}, ["--base=upstream/main"], "refs/remotes/upstream/main"),
    ],
)
def test_base_reads_the_hints_committed_on_the_base(tmp_path, setup, args, ref):
    clone = _pr_clone(tmp_path, **setup)
    out = _run(clone, *args).splitlines()
    assert out[0].startswith(f"<!-- skill-context: {clone} (base {ref} ")
    assert out[1:] == ["## BASE_RULES"]
    full, base, head = _run(clone, args[0].replace("--base", "--base-sha")).split()
    assert full == ref and out[0].endswith(f" {base[:12]}) -->") and head == _sha(clone, "HEAD")


def test_the_pr_recipe_reads_by_commit_from_any_checkout(tmp_path):
    # gh's baseRefOid and headRefOid: no ref name is read, and the checkout may stand
    # anywhere, the base itself included.
    clone = _pr_clone(tmp_path)
    base, head = _sha(clone, "origin/main"), _sha(clone, "pr")
    _git(clone, "checkout", "-q", "-f", "--detach", "origin/main")
    out = _run(clone, f"--base={base}", f"--head={head}")
    assert out.splitlines()[1:] == ["## BASE_RULES"]


@pytest.mark.parametrize(
    "shadow",
    [
        ["tag", "origin/main"],
        ["branch", "origin/main"],
    ],
)
def test_a_short_name_that_is_also_a_tag_or_branch_is_refused(tmp_path, shadow):
    clone = _pr_clone(tmp_path)
    _git(clone, *shadow, "pr~1")
    out = _run(clone, "--base=origin/main")
    assert out.startswith("(origin/main is ambiguous") and _says_no(out)
    assert "## BASE_RULES" in _run(clone, "--base")  # the full name from origin/HEAD


@pytest.mark.parametrize("kind", ["tag", "branch"])
def test_a_full_ref_is_read_exactly_even_when_shadowed(tmp_path, kind):
    # A tag or branch literally named refs/remotes/origin/main, with the remote ref absent
    # (a single-branch clone of the PR), must not stand in for it.
    clone = _pr_clone(tmp_path)
    _git(clone, kind, "refs/remotes/origin/main", "pr~1")
    one = tmp_path / "one"
    _git(tmp_path, "clone", "-q", "--single-branch", "-b", "pr", f"file://{clone}", str(one))
    if kind == "branch":
        _git(one, "branch", "refs/remotes/origin/main", "HEAD~1")
    for args in (["--base=refs/remotes/origin/main"], ["--base"]):
        out = _run(one, *args)
        assert _says_no(out), (args, out)


def test_a_base_that_moved_past_a_detached_review_is_refused(tmp_path):
    # Single-branch clone of the PR, detached at the reviewed commit; the author pushes and
    # the reviewer fetches: origin/HEAD (origin/pr) now holds the reviewed commit.
    clone = _pr_clone(tmp_path)
    one = tmp_path / "one"
    _git(tmp_path, "clone", "-q", "--single-branch", "-b", "pr", f"file://{clone}", str(one))
    _git(one, "remote", "set-head", "origin", "pr")
    _git(one, "checkout", "-q", "--detach")
    _git(clone, "checkout", "-q", "-f", "pr")
    (clone / ".claude" / "skill-context.md").write_text("## SOFT9\n")
    _git(clone, "commit", "-qam", "soften again")
    _git(one, "fetch", "-q")
    out = _run(one, "--base")
    assert out.startswith("(base refs/remotes/origin/pr holds the commit under review")
    assert _says_no(out)


@pytest.mark.parametrize(
    "case",
    [
        "main-checkout",
        "fork-main-tracks-upstream",
        "same-name-under-a-folder",
        "worktree-from-base",
    ],
)
def test_legitimate_setups_read_the_base(tmp_path, case):
    clone = _pr_clone(tmp_path, remote="upstream" if case.startswith("fork") else "origin")
    remote = "upstream" if case.startswith("fork") else "origin"
    head = _sha(clone, "pr")
    args = [f"--base=refs/remotes/{remote}/main", f"--head={head}"]
    if case == "main-checkout":
        _git(clone, "checkout", "-q", "-f", "--detach", f"{remote}/main")
    elif case == "fork-main-tracks-upstream":
        _git(clone, "checkout", "-q", "-f", "-B", "main", "upstream/main")
    elif case == "same-name-under-a-folder":
        _git(clone, "update-ref", "refs/remotes/origin/team/pr", "origin/main")
        args = ["--base=refs/remotes/origin/team/pr"]
    else:
        _git(clone, "checkout", "-q", "-f", "-b", "feat", "origin/main")
        (clone / ".claude" / "skill-context.md").write_text("## SOFT4\n")
        _git(clone, "commit", "-qam", "soften on feat")
        args = ["--base"]
    out = _run(clone, *args)
    assert "## BASE_RULES" in out and "SOFT" not in out, out


@pytest.mark.parametrize("rev", ["HEAD~1", "pr~1", "HEAD@{1}", "FETCH_HEAD", "origin/main~0"])
def test_a_revision_expression_is_not_a_base(tmp_path, rev):
    clone = _pr_clone(tmp_path)
    _git(clone, "fetch", "-q", "origin")
    assert _says_no(_run(clone, f"--base={rev}"))


def test_a_short_commit_id_is_not_a_base(tmp_path):
    clone = _pr_clone(tmp_path)
    assert _says_no(_run(clone, f"--base={_sha(clone, 'origin/main')[:12]}"))


def test_base_ignores_an_exported_git_dir(tmp_path):
    clone = _pr_clone(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    env = {**os.environ, "GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}
    assert "## BASE_RULES" in _run(clone, "--base", env=env)


def test_base_after_the_target_is_refused(tmp_path):
    clone = _pr_clone(tmp_path)
    for flag in ("--base=origin/main", "--head=HEAD"):
        out = _run(clone, ".", flag)
        assert out.startswith(f"({flag} must come before the target") and "SOFT" not in out


def test_base_reads_the_base_from_another_folder(tmp_path):
    clone = _pr_clone(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = _run(elsewhere, "--base", str(clone / ".claude"))
    assert "## BASE_RULES" in out and "SOFT" not in out


@pytest.mark.parametrize(
    ("setup", "prepare", "args", "says"),
    [
        (
            {"base_file": False},
            None,
            ["--base"],
            "(no .claude/skill-context.md on base refs/remotes/origin/main",
        ),
        (
            {"default": "master"},
            ["remote", "set-head", "origin", "-d"],
            ["--base"],
            "(refs/remotes/origin/main not found",
        ),
        ({}, None, ["--base=nope"], "(nope is not a ref"),
    ],
)
def test_a_missing_base_is_said_and_nothing_stands_in(tmp_path, setup, prepare, args, says):
    clone = _pr_clone(tmp_path, **setup)
    if prepare:
        _git(clone, *prepare)
    out = _run(clone, *args)
    assert out.startswith(says) and _says_no(out)


def test_without_base_the_working_tree_is_read_as_before(tmp_path):
    clone = _pr_clone(tmp_path)
    assert "## SOFT3" in _run(clone)
