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
import posixpath
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


# A folder holding one of these is a package root: its config-shaped files are tool config the
# way the repo root's files are (web/tsconfig.json, src-tauri/clippy.toml), so no name list has
# to know them. setup.py is left out: a flat-layout package's folder is its source.
MANIFESTS = {
    "package.json",
    "deno.json",
    "deno.jsonc",
    "Cargo.toml",
    "pyproject.toml",
    "setup.cfg",
    "go.mod",
    "composer.json",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Package.swift",
    "mix.exs",
}
REPO_ROOT = frozenset({""})
# A package root's file counts only in a config format; its source counts when a gate names it.
CONFIG_SHAPED = re.compile(
    r"(?i)^.*\.(toml|json|jsonc|json5|ya?ml|ini|cfg|conf|properties|txt|lock|xml|kts)$"
)
# Files that hold no rule.
NOISE = {".gitkeep", ".keep", ".DS_Store"}


def folder_of(path: str) -> str:
    """PATH's folder relative to the repo root; "" for a file at the root."""
    return "/".join(PurePosixPath(path).parts[:-1])


def package_roots(paths) -> frozenset[str]:
    """The repo root and the folder of every manifest among PATHS."""
    return REPO_ROOT | {folder_of(p) for p in paths if PurePosixPath(p).name in MANIFESTS}


def is_check(path: str, roots: frozenset[str] = REPO_ROOT) -> bool:
    p = PurePosixPath(path)
    folders = p.parts[:-1]
    if p.name in NOISE:
        return False
    if DIRS.intersection(folders) or p.name in NAMES or NAME_RE.match(p.name):
        return True
    # Tool config lives in dot-folders and dotfiles at any depth (.cargo/config.toml,
    # .config/nextest.toml, .devcontainer/, web/.storybook/main.ts, .prettierrc).
    if any(f.startswith(".") for f in folders):
        return True
    prose = ROOT_PROSE.match(p.name)
    if not prose and (p.name.startswith(".") or not folders):
        return True  # a dotfile, or any file at the repo root
    if folder_of(path) in roots and (p.name in MANIFESTS or CONFIG_SHAPED.match(p.name)):
        return True  # a package's own config
    if "scripts" in folders and SCRIPT_RE.match(p.name):
        return True
    # hooks/ counts at the repo root and in a plugin, not as an app's folder (src/hooks/).
    if folders[:1] == ("hooks",) or (folders[2:3] == ("hooks",) and folders[:1] == ("plugins",)):
        return True
    return any(folders[i : i + len(part)] == part for part in PARTS for i in range(len(folders)))


def decode(raw: bytes) -> str | None:
    """A gate file's text (UTF-16 by its byte-order mark, else UTF-8); None for a binary."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    return None if b"\0" in raw[:8000] else raw.decode("utf-8", "replace")


def read_base(repo: str, base: str, names: list[str]) -> dict[str, bytes]:
    """Each of NAMES as committed on BASE, through one `git cat-file --batch`; a name the
    base lacks is left out."""
    names = [n for n in names if "\n" not in n]
    if not names:
        return {}
    out = subprocess.run(
        ["git", "-C", repo, "cat-file", "--batch"],
        input=b"".join(f"{base}:{n}\n".encode() for n in names),
        capture_output=True,
        env=_env(),
    )
    if out.returncode != 0:
        raise SystemExit(f"own_checks: git cat-file failed: {out.stderr.decode(errors='replace')}")
    found, at, data = {}, 0, out.stdout
    for name in names:
        end = data.index(b"\n", at)
        header = data[at:end].split()
        if header[-1] == b"missing" or len(header) != 3:
            at = end + 1
            continue
        size = int(header[2])
        if header[1] == b"blob":
            found[name] = data[end + 1 : end + 1 + size]
        at = end + 2 + size
    return found


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


def gate_names(repo: str, base: str, listed: list[str], roots: frozenset[str]):
    """The path tokens and the glob tokens in the base's gate files, comments left out: its
    workflows, its git hooks and every tool-config file of the repo root or a package root
    (Makefile, pre-commit, package.json, vitest.config.ts, pyproject.toml, .gitlab-ci.yml, ...),
    so a file a check names is listed too, one hop deep. A package's tokens also count from its
    folder (web/package.json's `scripts/lint.js` names web/scripts/lint.js)."""
    names = [
        n
        for n in listed
        if (n.startswith(".github/workflows/") and n.endswith((".yml", ".yaml")))
        or n.startswith((".githooks/", ".husky/"))
        or (folder_of(n) in roots and is_check(n, roots))
    ]
    paths: set[str] = set()
    globs: list[str] = []
    for name, raw in read_base(repo, base, names).items():
        text = decode(raw)
        if text is None:
            continue  # a binary names nothing
        package = folder_of(name)
        yaml = name.endswith((".yml", ".yaml"))
        filter_indent = -1  # inside a YAML filter key's block list while >= 0
        for line in text.splitlines():
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
                tokens = [token]
                if package:  # a package's paths are relative to its folder: ../x leaves it
                    tokens.append(posixpath.normpath(f"{package}/{token}"))
                tokens = [t for t in tokens if t != ".." and not t.startswith("../")]
                if any(c in token for c in "*?["):
                    if GLOB_WITH_FOLDER.match(token):
                        globs += tokens
                else:
                    paths.update(tokens)
    return paths, globs


def path_glob(glob: str) -> re.Pattern[str]:
    """GLOB as a path pattern: `**` crosses folders while `*` and `?` stay within one, as in
    .gitignore, Codecov and GitHub's path filters (fnmatch's `*` would cross them, so a
    workspace's `agents/*` would name every file under it)."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        elif glob[i] == "[" and (end := glob.find("]", i + 2)) > 0:
            inner = glob[i + 1 : end]
            out.append(
                "[" + ("^" + inner[1:] if inner[0] in "!^" else inner).replace("\\", "\\\\") + "]"
            )
            i = end + 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


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
    files = {p for p in changed.split("\0") if p}
    if args.head is None:  # a local review: uncommitted edits are part of the change
        status = git(args.repo, "status", "--porcelain", "-z", "--no-renames", "--untracked-files")
        files |= {entry[3:] for entry in status.split("\0") if len(entry) > 3}
    listed = [
        n
        for n in git(args.repo, "ls-tree", "-r", "-z", "--name-only", "--full-tree", base).split(
            "\0"
        )
        if n
    ]
    # A manifest the change adds makes its folder a package root too (listing more is safe).
    roots = package_roots([*listed, *files])
    paths, globs = gate_names(args.repo, base, listed, roots)
    strong = sorted(p for p in files if is_check(p, roots))
    patterns = [path_glob(g) for g in dict.fromkeys(globs)]
    named = sorted(
        p for p in files - set(strong) if p in paths or any(g.match(p) for g in patterns)
    )
    print(f"head {head}")
    lines = strong + [f"{p}  (named by a gate: read, written or run)" for p in named]
    print("\n".join(lines) if lines else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
