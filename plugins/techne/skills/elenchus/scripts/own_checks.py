#!/usr/bin/env python3
"""The files a change edits that are part of its own checks: CI, hooks, guards, tests,
tool config and review rules. A review flags each as "edits its own check" and confirms
the change weakens none of them.

    own_checks.py [--repo DIR] [BASE]

BASE is the ref the change merges into, resolved by `_shared/skill_context.sh --base-sha`
(default: the remote's default branch; a name that is also a local branch or tag is
refused). Files come from `git diff --no-renames <base commit>...HEAD`, so a renamed or
deleted check is listed by its old path too. Prints one path per line, or `none`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

RESOLVER = Path(__file__).resolve().parents[3] / "_shared" / "skill_context.sh"

# A path is a check when any of its folders is one of these...
DIRS = {".github", ".githooks", ".husky", ".circleci", ".claude", "tests", "test", "spec"}
DIRS |= {"mutation"}
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
}
# ...or matches one of these patterns...
NAME_RE = re.compile(
    r"^("
    r"tests?_.*\.py|.*_tests?\.(py|go|rs)|tests\.py"
    r"|.*\.(test|spec)\.[cm]?[jt]sx?"
    r"|\.pre-commit-config\.ya?ml|\.gitguardian\.ya?ml|\.?zizmor\.ya?ml"
    r"|\.?codecov\.ya?ml|\.gitlab-ci\.ya?ml|.*\.config\.[cm]?[jt]s"
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


def _env() -> dict[str, str]:
    # A git hook exports GIT_DIR and GIT_WORK_TREE, which would override --repo.
    return {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}


def resolve(repo: str, base: str | None) -> str:
    """The base commit, resolved the way skill_context.sh --base resolves it."""
    flag = "--base-sha" if base is None else f"--base-sha={base}"
    out = subprocess.run(
        ["bash", str(RESOLVER), flag, repo], capture_output=True, text=True, env=_env()
    )
    if out.returncode != 0:
        raise SystemExit(f"own_checks: {out.stderr.strip()}")
    return out.stdout.split()[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("base", nargs="?")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    sha = resolve(args.repo, args.base)
    changed = subprocess.run(
        ["git", "-C", args.repo, "diff", "--no-renames", "--name-only", f"{sha}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
        env=_env(),
    ).stdout
    hits = sorted({p for p in changed.splitlines() if p and is_check(p)})
    print("\n".join(hits) if hits else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
