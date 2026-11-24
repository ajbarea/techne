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
    "audit", "ci-audit", "deslop", "docs-site", "logging", "reslop", "theoros"
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


def test_elenchus_never_loads_the_working_trees_hints():
    # A PR can edit its working tree's hints, which would reach the reader before the base read.
    text = (PLUGINS / "techne" / "skills" / "elenchus" / "SKILL.md").read_text(encoding="utf-8")
    assert "```!" not in text
    assert 'cat "$(git rev-parse --show-toplevel' not in text
    assert '--base="$base" --head="$head"' in text


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


def _ids(clone: pathlib.Path) -> tuple[str, str]:
    return _sha(clone, "origin/main"), _sha(clone, "pr")


@pytest.mark.parametrize("setup", [{}, {"default": "master"}, {"remote": "upstream"}])
def test_base_reads_the_hints_committed_on_the_base_commit(tmp_path, setup):
    clone = _pr_clone(tmp_path, **setup)
    base = _sha(clone, f"{setup.get('remote', 'origin')}/{setup.get('default', 'main')}")
    out = _run(clone, f"--base={base}").splitlines()
    assert out == [f"<!-- skill-context: {clone} (base {base}) -->", "## BASE_RULES"]
    assert _run(clone, f"--base-sha={base}").split() == [base, _sha(clone, "HEAD")]


def test_the_pr_recipe_reads_by_commit_from_any_checkout(tmp_path):
    clone = _pr_clone(tmp_path)
    base, head = _ids(clone)
    _git(clone, "checkout", "-q", "-f", "--detach", "origin/main")
    out = _run(clone, f"--base={base}", f"--head={head}")
    assert out.splitlines()[1:] == ["## BASE_RULES"]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "origin/main",
        "refs/remotes/origin/main",
        "main",
        "HEAD",
        "HEAD~1",
        "FETCH_HEAD",
        "SHORT",
        "UPPER",
        "--all",
    ],
)
def test_anything_but_a_full_commit_id_is_refused(tmp_path, value):
    # Every ref name is refused, so no local ref, tag or symref can wear the base's name.
    clone = _pr_clone(tmp_path)
    base, _ = _ids(clone)
    value = {"SHORT": base[:12], "UPPER": base.upper()}.get(value, value)
    out = _run(clone, f"--base={value}")
    assert out.startswith(f"('{value}' is not a full commit id") and _says_no(out)
    out = _run(clone, f"--base={base}", f"--head={value}")
    assert out.startswith(f"('{value}' is not a full commit id") and _says_no(out)


def test_bare_base_and_lone_head_are_refused(tmp_path):
    clone = _pr_clone(tmp_path)
    base, _ = _ids(clone)
    assert _run(clone, "--base").startswith("(--base needs a full commit id")
    proc = subprocess.run(
        ["bash", str(RESOLVER), "--base-sha"],
        cwd=clone,
        capture_output=True,
        text=True,
        env=_fenced(clone),
    )
    assert proc.returncode == 1 and proc.stderr.startswith("--base-sha needs a full commit id")
    out = _run(clone, f"--head={base}")
    assert out.startswith("(--head works only with --base") and "SOFT" not in out


def test_an_id_that_is_not_a_commit_is_refused(tmp_path):
    clone = _pr_clone(tmp_path)
    tree = _sha(clone, "origin/main^{tree}")
    missing = "0" * 40
    for value in (tree, missing):
        out = _run(clone, f"--base={value}")
        assert out.startswith(f"({value} is not a commit in") and _says_no(out)
    base, _ = _ids(clone)
    _git(clone, "tag", "-a", "-m", "t", "annotated", "origin/main")
    tag_object = _sha(clone, "annotated")
    assert _says_no(_run(clone, f"--base={tag_object}"))  # a tag object, not the commit
    assert _says_no(_run(clone, f"--base={base}", f"--head={missing}"))


def test_a_sha256_repo_wants_64_hex(tmp_path):
    repo = tmp_path / "sha256"
    repo.mkdir()
    _git(repo, "init", "-q", "--object-format=sha256", "-b", "main")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "skill-context.md").write_text("## BASE_RULES\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _sha(repo, "HEAD")
    (repo / "x").write_text("x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "change")
    assert len(base) == 64 and "## BASE_RULES" in _run(repo, f"--base={base}")
    assert _run(repo, f"--base={base[:40]}").startswith(f"('{base[:40]}' is not a full commit id")


@pytest.mark.parametrize("where", ["at", "past"])
def test_a_base_that_holds_the_reviewed_commit_is_refused(tmp_path, where):
    clone = _pr_clone(tmp_path)
    _, head = _ids(clone)
    if where == "at":
        args = [f"--base={head}", f"--head={head}"]
    else:
        _git(clone, "checkout", "-q", "-f", "pr")
        (clone / "more").write_text("m\n")
        _git(clone, "add", "more")
        _git(clone, "commit", "-qm", "more")
        args = [f"--base={_sha(clone, 'HEAD')}", f"--head={head}"]
    out = _run(clone, *args)
    assert "holds the commit under review" in out and _says_no(out)


@pytest.mark.parametrize(
    "var", ["GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_INDEX_FILE"]
)
def test_base_ignores_variables_that_point_git_elsewhere(tmp_path, var):
    clone = _pr_clone(tmp_path)
    base, _ = _ids(clone)
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    value = {"GIT_WORK_TREE": str(other)}.get(var, str(other / ".git" / "objects"))
    if var in ("GIT_DIR", "GIT_COMMON_DIR"):
        value = str(other / ".git")
    env = {**os.environ, var: value}
    assert "## BASE_RULES" in _run(clone, f"--base={base}", env=env)


def test_base_after_the_target_is_refused(tmp_path):
    clone = _pr_clone(tmp_path)
    base, _ = _ids(clone)
    for flag in (f"--base={base}", f"--head={base}"):
        out = _run(clone, ".", flag)
        assert out.startswith(f"({flag} must come before the target") and "SOFT" not in out


def test_base_reads_the_base_from_another_folder_and_says_when_there_is_no_repo(tmp_path):
    clone = _pr_clone(tmp_path)
    base, _ = _ids(clone)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = _run(elsewhere, f"--base={base}", str(clone / ".claude"))
    assert "## BASE_RULES" in out and "SOFT" not in out
    assert "is not a git repository git can read" in _run(elsewhere, f"--base={base}")


def test_a_base_without_the_file_is_said(tmp_path):
    clone = _pr_clone(tmp_path, base_file=False)
    base, _ = _ids(clone)
    out = _run(clone, f"--base={base}")
    assert out.startswith(f"(no .claude/skill-context.md on base {base}") and _says_no(out)


def test_without_base_the_working_tree_is_read_as_before(tmp_path):
    clone = _pr_clone(tmp_path)
    assert "## SOFT3" in _run(clone)


def test_a_replacement_object_cannot_swap_the_base(tmp_path):
    clone = _pr_clone(tmp_path)
    base, head = _ids(clone)
    _git(clone, "replace", base, f"{head}~1")
    for env in (None, {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}):
        out = _run(clone, f"--base={base}", f"--head={head}", env=env)
        assert out.splitlines()[1:] == ["## BASE_RULES"], out


def test_unproven_history_in_a_shallow_clone_is_refused(tmp_path):
    # main already merged the PR, but a depth-1 clone cannot show that the base holds it.
    clone = _pr_clone(tmp_path)
    _, head = _ids(clone)
    up = tmp_path / "up"
    _git(up, "fetch", "-q", str(clone), "pr")
    _git(up, "merge", "-q", "--no-ff", "-m", "merge pr", "FETCH_HEAD")
    shallow = tmp_path / "shallow"
    _git(tmp_path, "clone", "-q", "--depth=1", f"file://{up}", str(shallow))
    _git(shallow, "fetch", "-q", "--depth=1", "origin", head)
    base = _sha(shallow, "HEAD")
    out = _run(shallow, f"--base={base}", f"--head={head}")
    assert "share no history here" in out and _says_no(out)


def test_injected_git_config_reaches_every_read(tmp_path):
    # GIT_CONFIG_COUNT carries a container's safe.directory: it must survive the strip.
    clone = _pr_clone(tmp_path)
    base, _ = _ids(clone)
    shim = tmp_path / "shim"
    shim.mkdir()
    log = tmp_path / "seen"
    real = subprocess.run(
        ["bash", "-c", "command -v git"], capture_output=True, text=True
    ).stdout.strip()
    (shim / "git").write_text(
        f'#!/bin/sh\necho "${{GIT_CONFIG_COUNT:-none}}" >> {log}\nexec {real} "$@"\n'
    )
    (shim / "git").chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{shim}:{os.environ['PATH']}",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": "*",
    }
    assert "## BASE_RULES" in _run(clone, f"--base={base}", env=env)
    seen = log.read_text().split()
    assert seen and set(seen) == {"1"}, seen


def test_file_reads_another_path_from_the_base_even_past_a_replaced_blob(tmp_path):
    clone = _pr_clone(tmp_path)
    base, head = _ids(clone)
    for name, text in (("base.md", "BASE CATALOG\n"), ("pr.md", "PR CATALOG\n")):
        (clone / name).write_text(text)
    up = tmp_path / "up"
    (up / "catalog.md").write_text("BASE CATALOG\n")
    _git(up, "add", "catalog.md")
    _git(up, "commit", "-qm", "catalog")
    _git(clone, "fetch", "-q")
    base = _sha(clone, "origin/main")
    blob = _sha(clone, f"{base}:catalog.md")
    pr_blob = subprocess.run(
        ["git", "hash-object", "-w", str(clone / "pr.md")],
        cwd=clone,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    _git(clone, "replace", blob, pr_blob)
    out = _run(clone, f"--base={base}", f"--head={head}", "--file=catalog.md")
    assert out.splitlines() == [f"<!-- catalog.md at base {base} in {clone} -->", "BASE CATALOG"]
    assert _run(clone, f"--base={base}", f"--head={head}", "--file=nope.md").startswith(
        f"(no nope.md on base {base}"
    )
    assert _run(clone, "--file=catalog.md").startswith("(--file works only with --base")


def test_refusals_point_at_the_default_branch_recipe(tmp_path):
    clone = _pr_clone(tmp_path)
    out = _run(clone, "--base=main")
    assert "commits/HEAD" in out and "baseRefOid" not in out


def test_standing_on_the_base_says_to_check_out_the_change(tmp_path):
    clone = _pr_clone(tmp_path)
    base, _ = _ids(clone)
    _git(clone, "checkout", "-q", "-f", "--detach", base)
    out = _run(clone, f"--base={base}")
    assert "holds this checkout's HEAD" in out and "--head=<headRefOid>" in out
