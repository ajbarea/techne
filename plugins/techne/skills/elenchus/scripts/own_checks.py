#!/usr/bin/env python3
"""The files a change edits that are part of its own checks: CI, hooks, guards, tests,
tool config, review rules, and any file the base's Makefile, workflows or pre-commit config
names. A review flags each as "edits its own check" and confirms the change weakens none.

    own_checks.py [--repo DIR] [--head HEAD] BASE

BASE and HEAD are full commit ids (the default branch's commit from the host, and the PR's
headRefOid), checked by `_shared/skill_context.sh --base-sha`. Without --head it reviews the
checkout: HEAD plus its uncommitted and untracked files. Files come from
`git diff -z --no-renames BASE...HEAD`, so a renamed or deleted check is listed by its old
path too. Prints `head <commit>`, then one path per line (a file only named in a gate file
is marked, the weaker signal), or `none`.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.dont_write_bytecode = True  # the plugin cache stays as installed
SHARED = Path(__file__).resolve().parents[3] / "_shared"
sys.path.insert(0, str(SHARED))
from git_env import without_repo_overrides  # noqa: E402  # ty: ignore[unresolved-import]

RESOLVER = SHARED / "skill_context.sh"

# A path is a check when any of its folders is one of these...
DIRS = {".github", ".githooks", ".husky", ".circleci", ".claude", "tests", "test", "spec"}
DIRS |= {"mutation", "__tests__", "bench"}
# ...or its file name is one of these (anywhere, so a root-level prose name like
# AGENTS.md still counts)...
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


# A file at the repo root is tool config (.lighthouserc.json, vitest.setup.ts, Cargo.toml,
# requirements.txt) unless it is prose, an image, content or a known non-config name:
# listing too much is the safe direction.
ROOT_PROSE = re.compile(
    r"(?i)^(.*\.(md|rst|adoc|png|jpe?g|gif|svg|ico|webp|pdf|tex|bib|log)|readme(\..*)?"
    r"|licen[cs]e(\..*)?|copying(\..*)?|notice(\..*)?|authors(\..*)?|changelog(\..*)?"
    r"|citation\.cff|cname|\.env\.example)$"
)


def is_check(path: str) -> bool:
    p = PurePosixPath(path)
    folders = p.parts[:-1]
    if DIRS.intersection(folders) or p.name in NAMES or NAME_RE.match(p.name):
        return True
    if not folders and not ROOT_PROSE.match(p.name):
        return True
    if "scripts" in folders and SCRIPT_RE.match(p.name):
        return True
    # hooks/ counts at the repo root and in a plugin, not as an app's folder (src/hooks/).
    if folders[:1] == ("hooks",) or (folders[2:3] == ("hooks",) and folders[:1] == ("plugins",)):
        return True
    return any(folders[i : i + len(part)] == part for part in PARTS for i in range(len(folders)))


def _env() -> dict[str, str]:
    """No variable pointing git elsewhere, and no replacement objects or grafts, which would
    let a local ref swap the base's content under its own id (as in skill_context.sh)."""
    return {
        **without_repo_overrides(),
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_GRAFT_FILE": "/nonexistent-elenchus-graft",
    }


def git(repo: str, *args: str) -> str:
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=_env())
    if out.returncode != 0:
        first = (out.stderr.strip().splitlines() or ["no output"])[0]
        raise SystemExit(f"own_checks: git {args[0]} failed: {first}")
    return out.stdout


def resolve(repo: str, base: str, head: str | None) -> tuple[str, str]:
    """(base commit, head commit), checked the way skill_context.sh --base checks them."""
    argv = ["bash", str(RESOLVER), f"--base-sha={base}"]
    if head is not None:
        argv.append(f"--head={head}")
    out = subprocess.run(
        [*argv, repo], capture_output=True, text=True, env=without_repo_overrides()
    )
    if out.returncode != 0:
        raise SystemExit(f"own_checks: {out.stderr.strip()}")
    base_sha, head_sha = out.stdout.split()
    return base_sha, head_sha


# A gate file's text splits into tokens at whitespace, quotes and shell or YAML punctuation,
# so $(CURDIR)/x and ${{ github.workspace }}/x leave /x behind; ./ and / are then stripped.
TOKEN_SPLIT = re.compile(r"[\s\"'`=,;:()\[\]{}|&<>\\$]+")
COMMENT = re.compile(r"(^|\s)#.*$")
# $NAME and ${NAME} go, so $GITHUB_WORKSPACE/tools/x.py leaves /tools/x.py.
SHELL_VAR = re.compile(r"\$\{?[A-Za-z_]\w*\}?")
# A YAML filter list (on.push.paths, branches, a bare list scalar) says when CI runs, not
# what it runs; a glob counts only with a literal leading folder (tools/*.py, not * or **).
FILTER_KEY = re.compile(r"^(\s*)(paths|paths-ignore|branches|branches-ignore|tags)\s*:(.*)$")
GLOB_WITH_FOLDER = re.compile(r"^[\w.-]+/")


def gate_names(repo: str, base: str) -> tuple[set[str], list[str]]:
    """The path tokens and the glob tokens in the base's gate files, comments left out: its
    workflows and every root tool-config file (Makefile, pre-commit, package.json,
    vitest.config.ts, pyproject.toml, .gitlab-ci.yml, ...), so a file a check names is
    listed too, one hop deep."""
    listed = git(repo, "ls-tree", "-r", "-z", "--name-only", "--full-tree", base)
    names = [
        n
        for n in listed.split("\0")
        if (n.startswith(".github/workflows/") and n.endswith((".yml", ".yaml")))
        or (n and "/" not in n and is_check(n))
    ]
    paths: set[str] = set()
    globs: list[str] = []
    for name in names:
        out = subprocess.run(
            ["git", "-C", repo, "show", f"{base}:{name}"],
            capture_output=True,
            text=True,
            env=_env(),
        )
        if out.returncode != 0:
            continue  # this gate file is not on the base
        yaml = name.endswith((".yml", ".yaml"))
        filter_indent = -1  # inside a YAML filter key's block list while >= 0
        for line in out.stdout.splitlines():
            if yaml:
                indent = len(line) - len(line.lstrip())
                if filter_indent >= 0 and (indent > filter_indent or not line.strip()):
                    continue
                filter_indent = -1
                key = FILTER_KEY.match(line)
                if key:
                    if not key.group(3).strip():
                        filter_indent = len(key.group(1))
                    continue
            for token in TOKEN_SPLIT.split(SHELL_VAR.sub(" ", COMMENT.sub("", line))):
                while token.startswith(("./", "/")):
                    token = token[2:] if token.startswith("./") else token[1:]
                if token in ("", ".", ".."):
                    continue
                if any(c in token for c in "*?["):
                    if GLOB_WITH_FOLDER.match(token):
                        globs.append(token)
                else:
                    paths.add(token)
    return paths, globs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("base", help="the default branch's full commit id")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--head", help="the reviewed full commit id (headRefOid); default HEAD")
    args = ap.parse_args(argv)
    base, head = resolve(args.repo, args.base, args.head)
    changed = git(
        args.repo, "diff", "-z", "--no-renames", "--no-relative", "--name-only", f"{base}...{head}"
    )
    paths, globs = gate_names(args.repo, base)
    files = {p for p in changed.split("\0") if p}
    if args.head is None:  # a local review: uncommitted edits are part of the change
        status = git(args.repo, "status", "--porcelain", "-z", "--no-renames", "--untracked-files")
        files |= {entry[3:] for entry in status.split("\0") if len(entry) > 3}
    strong = sorted(p for p in files if is_check(p))
    named = sorted(
        p
        for p in files - set(strong)
        if p in paths or any(fnmatch.fnmatchcase(p, g) for g in globs)
    )
    print(f"head {head}")
    lines = strong + [f"{p}  (named by a gate: read, written or run)" for p in named]
    print("\n".join(lines) if lines else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
