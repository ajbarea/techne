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


@pytest.mark.parametrize(
    ("setup", "args", "ref"),
    [
        ({}, ["--base=origin/main"], "refs/remotes/origin/main"),
        ({}, ["--base"], "refs/remotes/origin/main"),
        ({}, ["--base=refs/remotes/origin/main"], "refs/remotes/origin/main"),
        ({"default": "master"}, ["--base"], "refs/remotes/origin/master"),
        ({"default": "master"}, ["--base=origin/master"], "refs/remotes/origin/master"),
        ({"remote": "upstream"}, ["--base=upstream/main"], "refs/remotes/upstream/main"),
    ],
)
def test_base_reads_the_hints_committed_on_the_base(tmp_path, setup, args, ref):
    clone = _pr_clone(tmp_path, **setup)
    out = _run(clone, *args).splitlines()
    assert out[0].startswith(f"<!-- skill-context: {clone} (base {ref} ")
    assert out[1:] == ["## BASE_RULES"]
    sha = _run(clone, args[0].replace("--base", "--base-sha")).split()
    assert sha[0] == ref and out[0].endswith(f" {sha[1][:12]}) -->")


@pytest.mark.parametrize("shadow", [["tag", "origin/main"], ["branch", "origin/main"]])
def test_a_tag_or_branch_named_like_the_base_is_refused(tmp_path, shadow):
    # A tag pushed upstream arrives with the next fetch; a PR branch can carry any name.
    clone = _pr_clone(tmp_path)
    _git(clone, *shadow)
    out = _run(clone, "--base=origin/main")
    assert out.startswith("(base origin/main is ambiguous") and "SOFT" not in out
    assert "## BASE_RULES" in _run(clone, "--base")  # the full name from origin/HEAD
    proc = subprocess.run(
        ["bash", str(RESOLVER), "--base-sha=origin/main", str(clone)],
        capture_output=True,
        text=True,
        env=_fenced(clone),
    )
    assert proc.returncode == 1 and "ambiguous" in proc.stderr


def test_a_shallow_single_branch_clone_with_a_shadowing_tag_never_reads_the_pr(tmp_path):
    clone = _pr_clone(tmp_path)
    _git(clone, "tag", "origin/main")
    shallow = tmp_path / "shallow"
    _git(
        tmp_path,
        "clone",
        "-q",
        "--depth=1",
        "--single-branch",
        "-b",
        "pr",
        f"file://{clone}",
        str(shallow),
    )
    _git(shallow, "fetch", "-q", "origin", "tag", "origin/main")
    out = _run(shallow, "--base")
    assert "SOFT" not in out and "BASE_RULES" not in out


def test_base_ignores_an_exported_git_dir(tmp_path):
    clone = _pr_clone(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    env = {**os.environ, "GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}
    assert "## BASE_RULES" in _run(clone, "--base", env=env)


def test_base_after_the_target_is_refused(tmp_path):
    clone = _pr_clone(tmp_path)
    out = _run(clone, ".", "--base=origin/main")
    assert out.startswith("(--base=origin/main must come before the target") and "SOFT" not in out


def test_base_reads_the_base_from_a_detached_head_and_another_folder(tmp_path):
    clone = _pr_clone(tmp_path)
    _git(clone, "checkout", "-q", "--detach", "HEAD")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = _run(elsewhere, "--base", str(clone / ".claude"))
    assert "## BASE_RULES" in out and "SOFT" not in out


@pytest.mark.parametrize(
    ("setup", "prepare", "args", "says"),
    [
        # The base has no file and the PR adds one: say so, never print the PR's.
        (
            {"base_file": False},
            None,
            ["--base"],
            "(no .claude/skill-context.md on base refs/remotes/origin/main",
        ),
        # A master-default remote with origin/HEAD gone and no origin/main: no HEAD~1 stand-in.
        (
            {"default": "master"},
            ["remote", "set-head", "origin", "-d"],
            ["--base"],
            "(base refs/remotes/origin/main not found",
        ),
        ({}, None, ["--base=nope"], "(base nope not found"),
    ],
)
def test_a_missing_base_is_said_and_nothing_stands_in(tmp_path, setup, prepare, args, says):
    clone = _pr_clone(tmp_path, **setup)
    if prepare:
        _git(clone, *prepare)
    out = _run(clone, *args)
    assert out.startswith(says) and "SOFT" not in out and "BASE_RULES" not in out


def test_without_base_the_working_tree_is_read_as_before(tmp_path):
    clone = _pr_clone(tmp_path)
    assert "## SOFT3" in _run(clone)


def test_a_branch_that_tracks_the_base_still_reads_it(tmp_path):
    # `git worktree add -b feat <dir> origin/main` tracks origin/main: a real base.
    clone = _pr_clone(tmp_path)
    _git(clone, "checkout", "-q", "-f", "-b", "feat", "origin/main")
    (clone / ".claude" / "skill-context.md").write_text("## SOFT4\n")
    _git(clone, "commit", "-qam", "soften on feat")
    out = _run(clone, "--base")
    assert "## BASE_RULES" in out and "SOFT" not in out


def test_a_base_that_is_the_reviewed_commit_is_refused(tmp_path):
    clone = _pr_clone(tmp_path)
    _git(clone, "checkout", "-q", "-f", "-b", "nothing-yet", "origin/main")
    out = _run(clone, "--base")
    assert out.startswith("(base refs/remotes/origin/main is the branch under review")


def test_a_base_named_like_the_reviewed_branch_is_refused(tmp_path):
    # A single-branch clone of `pr` points origin/HEAD at origin/pr; one more local commit
    # makes HEAD differ from it, so only the name tells the two apart.
    clone = _pr_clone(tmp_path)
    one = tmp_path / "one"
    _git(tmp_path, "clone", "-q", "--single-branch", "-b", "pr", f"file://{clone}", str(one))
    _git(one, "remote", "set-head", "origin", "pr")
    (one / "x").write_text("x\n")
    _git(one, "add", "x")
    _git(one, "commit", "-qm", "local")
    out = _run(one, "--base")
    assert out.startswith("(base refs/remotes/origin/pr is the branch under review")
    assert "SOFT" not in out
