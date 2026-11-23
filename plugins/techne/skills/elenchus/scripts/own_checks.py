#!/usr/bin/env python3
"""The files a change edits that are part of its own checks: CI, hooks, guards, tests,
tool config, review rules, and any file the base's Makefile, workflows or pre-commit config
names. A review flags each as "edits its own check" and confirms the change weakens none.

    own_checks.py [--repo DIR] [--head HEAD] [BASE]

BASE and HEAD resolve exactly as `_shared/skill_context.sh --base=BASE --head=HEAD` resolves
them: a full commit id (a PR's baseRefOid and headRefOid), a full ref, or a short name that
is exactly one ref; default the remote's default branch and the checkout's HEAD. Files come
from `git diff -z --no-renames BASE...HEAD`, so a renamed or deleted check is listed by its
old path too. Prints `head <commit>`, then one path per line, or `none`.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.dont_write_bytecode = True  # the plugin cache stays as installed
SHARED = Path(__file__).resolve().parents[3] / "_shared"
sys.path.insert(0, str(SHARED))
from git_env import without_repo_overrides  # noqa: E402  # ty: ignore[unresolved-import]

RESOLVER = SHARED / "skill_context.sh"
# Files whose text names the gates a repo runs; a changed file they name is a check too.
GATE_FILES = ("Makefile", "GNUmakefile", ".pre-commit-config.yaml", ".pre-commit-config.yml")

# A path is a check when any of its folders is one of these...
DIRS = {".github", ".githooks", ".husky", ".circleci", ".claude", "tests", "test", "spec"}
DIRS |= {"mutation", "__tests__", "bench"}
# ...or its file name is one of these...
NAMES = {
    "Makefile",
    "GNUmakefile",
    "makefile",
    "justfile",
    "Justfile",
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
    "conftest.py",
    "noxfile.py",
    ".coveragerc",
    "mypy.ini",
    "ty.toml",
    "ruff.toml",
    ".ruff.toml",
    "biome.json",
    "biome.jsonc",
    ".gitattributes",
    ".gitleaksignore",
    ".gitleaks.toml",
    "REVIEW.md",
    "AGENTS.md",
    "CLAUDE.md",
    "skill-context.md",
    "bug-classes.md",
    "skill_context.sh",
    "package.json",
    "Jenkinsfile",
    "CODEOWNERS",
    "plugin.json",
    ".golangci.yml",
    ".golangci.yaml",
}
# ...or matches one of these patterns...
NAME_RE = re.compile(
    r"^("
    r"tests?_.*\.py|.*_tests?\.(py|go|rs)|tests\.py"
    r"|.*\.(test|spec)\.[cm]?[jt]sx?"
    r"|\.pre-commit-config\.ya?ml|\.gitguardian\.ya?ml|\.?zizmor\.ya?ml"
    r"|\.?codecov\.ya?ml|\.gitlab-ci\.ya?ml|.*\.config\.[cm]?[jt]s|.*\.mk"
    r")$"
)
# ...or, under a scripts/ folder, matches this (the gate scripts CI and the Makefile run)...
SCRIPT_RE = re.compile(r"^(check_.*|install_.*|validate_.*|mutation\.py|.*_guard\..*)$")
# ...or it sits under one of these folder runs: a plugin's or the repo's own hooks, the
# review skill and the guard plugin themselves.
PARTS = (("skills", "elenchus"), ("plugins", "phylax"))


def is_check(path: str) -> bool:
    p = PurePosixPath(path)
    folders = p.parts[:-1]
    if DIRS.intersection(folders) or p.name in NAMES or NAME_RE.match(p.name):
        return True
    if "scripts" in folders and SCRIPT_RE.match(p.name):
        return True
    # hooks/ counts at the repo root and in a plugin, not as an app's folder (src/hooks/).
    if folders[:1] == ("hooks",) or (folders[2:3] == ("hooks",) and folders[:1] == ("plugins",)):
        return True
    return any(folders[i : i + len(part)] == part for part in PARTS for i in range(len(folders)))


def git(repo: str, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, env=without_repo_overrides()
    )
    if out.returncode != 0:
        first = (out.stderr.strip().splitlines() or ["no output"])[0]
        raise SystemExit(f"own_checks: git {args[0]} failed: {first}")
    return out.stdout


def resolve(repo: str, base: str | None, head: str | None) -> tuple[str, str]:
    """(base commit, head commit), resolved the way skill_context.sh --base resolves them."""
    argv = ["bash", str(RESOLVER), "--base-sha" if base is None else f"--base-sha={base}"]
    if head is not None:
        argv.append(f"--head={head}")
    out = subprocess.run(
        [*argv, repo], capture_output=True, text=True, env=without_repo_overrides()
    )
    if out.returncode != 0:
        raise SystemExit(f"own_checks: {out.stderr.strip()}")
    _, base_sha, head_sha = out.stdout.split()
    return base_sha, head_sha


def gate_text(repo: str, base: str) -> str:
    """The base's Makefile, pre-commit config and workflows, as one text."""
    names = list(GATE_FILES)
    listed = git(repo, "ls-tree", "-r", "-z", "--name-only", base, "--", ".github/workflows")
    names += [n for n in listed.split("\0") if n.endswith((".yml", ".yaml"))]
    texts = []
    for name in names:
        out = subprocess.run(
            ["git", "-C", repo, "show", f"{base}:{name}"],
            capture_output=True,
            text=True,
            env=without_repo_overrides(),
        )
        texts.append(out.stdout if out.returncode == 0 else "")
    return "\n".join(texts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("base", nargs="?")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--head")
    args = ap.parse_args(argv)
    base, head = resolve(args.repo, args.base, args.head)
    changed = git(args.repo, "diff", "-z", "--no-renames", "--name-only", f"{base}...{head}")
    gates = gate_text(args.repo, base)
    paths = {p for p in changed.split("\0") if p}

    def named(path: str) -> bool:  # the whole path as a token, not part of a longer one
        return re.search(rf"(?<![\w./-]){re.escape(path)}(?![\w/-])", gates) is not None

    hits = sorted(p for p in paths if is_check(p) or named(p))
    print(f"head {head}")
    print("\n".join(hits) if hits else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
