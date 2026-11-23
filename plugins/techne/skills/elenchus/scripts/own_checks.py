#!/usr/bin/env python3
"""The files a change edits that are part of its own checks: CI, hooks, guards, tests,
tool config and review rules. A review flags each as "edits its own check" and confirms
the change weakens none of them.

    own_checks.py [--repo DIR] [BASE]

BASE is the ref the change merges into (default: the remote's default branch, origin/HEAD,
else origin/main). Files come from `git diff --no-renames BASE...HEAD`, so a renamed or
deleted check is listed by its old path too. Prints one path per line, or `none`.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import PurePosixPath

# A path is a check when any of its folders is one of these...
DIRS = {".github", ".githooks", ".husky", ".claude", "hooks", "tests", "test", "mutation"}
# ...its file name is one of these...
NAMES = {
    "Makefile",
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
    "conftest.py",
    "noxfile.py",
    ".pre-commit-config.yaml",
    ".gitleaksignore",
    ".gitguardian.yaml",
    ".gitattributes",
    "codecov.yml",
    "REVIEW.md",
    "AGENTS.md",
    "CLAUDE.md",
    "skill-context.md",
    "bug-classes.md",
    "package.json",
    "eslint.config.js",
    "vitest.config.ts",
    "playwright.config.ts",
}
# ...or its file name matches this...
NAME_RE = re.compile(r"^(test_.*\.py|.*_test\.(py|go)|.*\.(test|spec)\.[cm]?[jt]sx?|check_.*)$")
# ...or it sits under one of these (the review skill and the guard plugin themselves).
PARTS = (("skills", "elenchus"), ("plugins", "phylax"))


def is_check(path: str) -> bool:
    p = PurePosixPath(path)
    folders = p.parts[:-1]
    if DIRS.intersection(folders) or p.name in NAMES or NAME_RE.match(p.name):
        return True
    return any(folders[i : i + len(part)] == part for part in PARTS for i in range(len(folders)))


def git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=True
    ).stdout


def default_base(repo: str) -> str:
    try:
        return git(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD").strip()
    except subprocess.CalledProcessError:
        return "origin/main"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("base", nargs="?")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    base = args.base or default_base(args.repo)
    try:
        changed = git(args.repo, "diff", "--no-renames", "--name-only", f"{base}...HEAD")
    except subprocess.CalledProcessError as exc:
        print(f"own_checks: cannot diff {base}...HEAD: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    hits = sorted({p for p in changed.splitlines() if p and is_check(p)})
    print("\n".join(hits) if hits else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
