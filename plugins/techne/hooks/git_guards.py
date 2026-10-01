#!/usr/bin/env python3
"""PreToolUse guards on the Bash tool for git commit, git add and gh pr.

Each guard is off until its userConfig option is switched on in /config, which
Claude Code exports to this process as CLAUDE_PLUGIN_OPTION_<KEY>. A repo turns
an enabled guard off for itself with `git config techne.<optionInCamelCase> false`.

Invoked as `git_guards.py git` or `git_guards.py gh`, one per hooks.json handler,
so a compound command that runs both is checked once per tool.

Parsing is best effort: subcommands inside `$(...)` or `bash -c` are not seen.
Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ATTRIBUTION = "block_attribution_trailers"
COMMITS_MD = "block_commits_md"
MAIN_CHECKOUT = "warn_main_checkout_commit"
OPTIONS = (ATTRIBUTION, COMMITS_MD, MAIN_CHECKOUT)

ATTRIBUTION_RE = re.compile(
    r"Claude-Session|claude\.ai/code/session|Co-Authored-By:\s*Claude"
    r"|Generated with \[?Claude Code",
    re.IGNORECASE,
)
SCRATCH_NAME = "commits.md"
TRUE_VALUES = {"1", "true", "yes", "on"}
MAX_MESSAGE_FILE = 1 << 20
GIT_TIMEOUT = 10

# shlex joins adjacent punctuation, so a separator is any run of these, such as "&&\n".
SEPARATOR_RE = re.compile(r"^[;&|()\n]+$")
REDIRECT_RE = re.compile(r"^[<>&]*[<>][<>&]*$")
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC_RE = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][\w.-]*)\2")

# Global git options that take the next token as their value.
GIT_GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
# git commit options that take a value; the message-bearing ones are read below.
COMMIT_SHORT_VALUE = set("mFcCt")
COMMIT_LONG_VALUE = {
    "--message",
    "--file",
    "--reuse-message",
    "--reedit-message",
    "--template",
    "--author",
    "--date",
    "--cleanup",
    "--fixup",
    "--squash",
    "--trailer",
    "--pathspec-from-file",
}
ADD_LONG_VALUE = {"--pathspec-from-file", "--chmod"}
ADD_INTERACTIVE = {"-p", "--patch", "-i", "--interactive", "-e", "--edit"}
# gh pr subcommands that write a PR title/body, or (merge) the squash commit message.
GH_PR_WRITERS = {"create", "edit", "merge"}
GH_TEXT = {"-t": "text", "--title": "text", "--subject": "text", "-b": "text", "--body": "text"}
GH_FILE = {"-F": "file", "--body-file": "file", "-T": "file", "--template": "file"}


def option_on(key: str) -> bool:
    return os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", "").strip().lower() in TRUE_VALUES


def repo_key(key: str) -> str:
    head, *rest = key.split("_")
    return "techne." + head + "".join(part.capitalize() for part in rest)


def run_git(cwd: Path, repo_args: list[str], *args: str) -> str | None:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        proc = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(cwd), *repo_args, *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def strip_heredocs(text: str) -> tuple[str, list[str]]:
    """Remove heredoc bodies and line continuations so the command tokenizes.

    Tracks quoting as bash does: `<<` inside quotes is literal, except inside a
    `$(...)` within double quotes, the `-m "$(cat <<'EOF' ...)"` commit idiom.
    Returns the stripped text and the heredoc bodies.
    """
    out: list[str] = []
    bodies: list[str] = []
    pending: list[tuple[str, bool]] = []
    stack: list[str] = []  # "'", '"' or "$(" for each open quoting context
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        top = stack[-1] if stack else ""
        if ch == "\n" and pending:
            out.append(ch)
            i += 1
            for delim, dash in pending:
                body: list[str] = []
                while i < n:
                    j = text.find("\n", i)
                    line = text[i:] if j < 0 else text[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if dash else line) == delim:
                        break
                    body.append(line)
                bodies.append("\n".join(body))
            pending = []
            continue
        if top == "'":
            if ch == "'":
                stack.pop()
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if text[i + 1] != "\n":
                out.append(text[i : i + 2])
            i += 2
            continue
        if top == '"':
            if ch == '"':
                stack.pop()
            elif text.startswith("$(", i):
                stack.append("$(")
                out.append("$(")
                i += 2
                continue
            out.append(ch)
            i += 1
            continue
        if ch in "'\"":
            stack.append(ch)
        elif text.startswith("$(", i):
            stack.append("$(")
            out.append("$(")
            i += 2
            continue
        elif ch == ")" and top == "$(":
            stack.pop()
        elif ch == "<":
            m = HEREDOC_RE.match(text, i)
            if m and not text.startswith("<<<", i) and not text.endswith("<", 0, i):
                pending.append((m.group(3), m.group(1) == "-"))
                out.append(m.group(0))
                i = m.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out), bodies


def tokenize(text: str) -> list[str] | None:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def split_subcommands(tokens: list[str]) -> list[list[str]]:
    commands: list[list[str]] = [[]]
    for tok in tokens:
        if SEPARATOR_RE.match(tok):
            commands.append([])
        else:
            commands[-1].append(tok)
    return [drop_redirections(c) for c in commands if c]


def drop_redirections(argv: list[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for tok in argv:
        if skip:
            skip = False
            continue
        if REDIRECT_RE.match(tok):
            if out and out[-1].isdigit():
                out.pop()
            skip = True
            continue
        out.append(tok)
    while out and ASSIGNMENT_RE.match(out[0]):
        out.pop(0)
    if out and out[0] in {"env", "command"}:
        out.pop(0)
        while out and ASSIGNMENT_RE.match(out[0]):
            out.pop(0)
    return out


def read_message_file(path: str, cwd: Path) -> str | None:
    target = Path(os.path.expanduser(path))
    if not target.is_absolute():
        target = cwd / target
    try:
        with open(target, encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_MESSAGE_FILE)
    except OSError:
        return None


def is_scratch_path(spec: str) -> bool:
    """True for a pathspec naming COMMITS.md; exclusion pathspecs never count."""
    if spec.startswith(":"):
        magic = re.match(r"^:(\([^)]*\)|[/!^]*)", spec)
        prefix = magic.group(0) if magic else ":"
        if "!" in prefix or "^" in prefix or "exclude" in prefix:
            return False
        spec = spec[len(prefix) :]
    return Path(spec).name.lower() == SCRATCH_NAME


def names_scratch(lines: str | None) -> list[str]:
    if not lines:
        return []
    return [
        p for p in lines.replace("\0", "\n").split("\n") if Path(p).name.lower() == SCRATCH_NAME
    ]


class Command:
    """One git or gh invocation with the directory it runs in."""

    def __init__(self, argv: list[str], cwd: Path):
        self.argv = argv
        self.cwd = cwd
        self.repo_args: list[str] = []
        self.sub = ""
        self.args: list[str] = []


def parse_git(argv: list[str], cwd: Path) -> Command | None:
    cmd = Command(argv, cwd)
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in GIT_GLOBAL_VALUE and i + 1 < len(argv):
            value = argv[i + 1]
            if tok == "-C":
                cmd.cwd = cmd.cwd / os.path.expanduser(value)
            elif tok in {"--git-dir", "--work-tree"}:
                cmd.repo_args += [tok, str(cmd.cwd / os.path.expanduser(value))]
            i += 2
            continue
        if tok.startswith(("--git-dir=", "--work-tree=")):
            name, _, value = tok.partition("=")
            cmd.repo_args += [name, str(cmd.cwd / os.path.expanduser(value))]
        elif not tok.startswith("-"):
            cmd.sub = tok
            cmd.args = argv[i + 1 :]
            return cmd
        i += 1
    return None


class Commit:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.files: list[str] = []
        self.pathspecs: list[str] = []
        self.all = False
        self.include = False


def parse_commit(args: list[str]) -> Commit:
    c = Commit()
    i = 0
    while i < len(args):
        tok = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else None
        if tok == "--":
            c.pathspecs += args[i + 1 :]
            break
        if tok.startswith("--"):
            name, eq, value = tok.partition("=")
            if name in COMMIT_LONG_VALUE:
                if not eq:
                    value = nxt or ""
                    i += 1
                if name in {"--message", "--trailer"}:
                    c.texts.append(value)
                elif name == "--file":
                    c.files.append(value)
            elif name == "--all":
                c.all = True
            elif name == "--include":
                c.include = True
        elif tok.startswith("-") and len(tok) > 1:
            for j, flag in enumerate(tok[1:], start=1):
                if flag in COMMIT_SHORT_VALUE:
                    value = tok[j + 1 :]
                    if not value:
                        value = nxt or ""
                        i += 1
                    if flag == "m":
                        c.texts.append(value)
                    elif flag == "F":
                        c.files.append(value)
                    break
                if flag == "a":
                    c.all = True
                elif flag == "i":
                    c.include = True
        else:
            c.pathspecs.append(tok)
        i += 1
    return c


def parse_gh_pr(args: list[str]) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    files: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        name, eq, value = tok.partition("=")
        if not tok.startswith("--") and len(tok) > 2 and tok[:2] in GH_TEXT | GH_FILE:
            name, eq, value = tok[:2], "=", tok[2:]
        kind = GH_TEXT.get(name) or GH_FILE.get(name)
        if kind:
            if not eq:
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            (texts if kind == "text" else files).append(value)
        i += 1
    return texts, files


class Verdict:
    def __init__(self) -> None:
        self.denies: list[str] = []
        self.warnings: list[str] = []

    def emit(self) -> None:
        if self.denies:
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "\n".join(self.denies),
                }
            }
        elif self.warnings:
            text = "\n".join(self.warnings)
            out = {
                "systemMessage": text,
                "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text},
            }
        else:
            return
        json.dump(out, sys.stdout)


class Guards:
    def __init__(self, raw: str, bodies: list[str]):
        self.raw = raw
        self.bodies = bodies
        self.verdict = Verdict()
        self._repo_cache: dict[tuple[str, tuple[str, ...], str], bool] = {}

    def enabled(self, key: str, cmd: Command | None = None) -> bool:
        if not option_on(key):
            return False
        if cmd is None:
            return True
        cache_key = (str(cmd.cwd), tuple(cmd.repo_args), key)
        if cache_key not in self._repo_cache:
            value = run_git(cmd.cwd, cmd.repo_args, "config", "--type=bool", "--get", repo_key(key))
            self._repo_cache[cache_key] = (value or "").strip() != "false"
        return self._repo_cache[cache_key]

    def check_attribution(self, what: str, texts: list[str], files: list[str], cwd: Path) -> None:
        scan = list(texts) + self.bodies
        for path in files:
            content = None if path == "-" else read_message_file(path, cwd)
            if content is None:
                scan.append(self.raw)
            else:
                scan.append(content)
        for text in scan:
            for line in text.splitlines():
                if ATTRIBUTION_RE.search(line):
                    self.verdict.denies.append(
                        f"techne: {what} carries an attribution line: {line.strip()!r}. "
                        "Remove it and retry. To allow attribution lines in this repo, run "
                        f"`git config {repo_key(ATTRIBUTION)} false`."
                    )
                    return

    def deny_scratch(self, how: str, cmd: Command) -> None:
        self.verdict.denies.append(
            f"techne: {how}. COMMITS.md is a local scratchpad and never goes in a commit. "
            "Unstage it with `git restore --staged COMMITS.md` if needed, and retry without it. "
            f"To allow it in this repo, run `git config {repo_key(COMMITS_MD)} false`."
        )

    def check_add(self, cmd: Command) -> None:
        if not self.enabled(COMMITS_MD, cmd):
            return
        named = [a for a in cmd.args if not a.startswith("-") and is_scratch_path(a)]
        if named:
            self.deny_scratch(f"`git add` names {named[0]}", cmd)
            return
        if any(a in ADD_INTERACTIVE for a in cmd.args):
            return
        dry = run_git(cmd.cwd, cmd.repo_args, "add", "--dry-run", *cmd.args)
        hits = [m.group(1) for m in re.finditer(r"^add '(.*)'$", dry or "", re.MULTILINE)]
        hits = [h for h in hits if Path(h).name.lower() == SCRATCH_NAME]
        if hits:
            self.deny_scratch(f"`git add` would stage {hits[0]}", cmd)

    def check_commit_scratch(self, cmd: Command, commit: Commit) -> None:
        if not self.enabled(COMMITS_MD, cmd):
            return
        named = [p for p in commit.pathspecs if is_scratch_path(p)]
        if named:
            self.deny_scratch(f"`git commit` names {named[0]}", cmd)
            return
        hits: list[str] = []
        if commit.pathspecs:
            hits += names_scratch(
                run_git(
                    cmd.cwd, cmd.repo_args, "diff", "--name-only", "HEAD", "--", *commit.pathspecs
                )
            )
        if not commit.pathspecs or commit.include:
            hits += names_scratch(
                run_git(cmd.cwd, cmd.repo_args, "diff", "--cached", "--name-only")
            )
        if commit.all:
            hits += names_scratch(run_git(cmd.cwd, cmd.repo_args, "diff", "--name-only"))
        if hits:
            self.deny_scratch(f"this commit would include {hits[0]}", cmd)

    def check_main_checkout(self, cmd: Command) -> None:
        if not self.enabled(MAIN_CHECKOUT, cmd):
            return
        dirs = run_git(
            cmd.cwd,
            cmd.repo_args,
            "rev-parse",
            "--path-format=absolute",
            "--git-dir",
            "--git-common-dir",
        )
        if not dirs or len(set(dirs.split())) != 1:
            return
        listing = run_git(cmd.cwd, cmd.repo_args, "worktree", "list", "--porcelain") or ""
        entries = [e for e in listing.split("\n\n") if e.startswith("worktree ")]
        paths = [e.split("\n", 1)[0][len("worktree ") :] for e in entries]
        linked = [paths[k] for k in range(1, len(entries)) if "\nprunable" not in entries[k]]
        if linked:
            self.verdict.warnings.append(
                f"techne: committing in the main checkout of {paths[0]} "
                f"while {len(linked)} linked worktree(s) exist, e.g. {linked[0]}. Sessions sharing "
                "this checkout share one index, so another session's staged work can land in this "
                "commit. Prefer a worktree per session."
            )

    def run(self, family: str, commands: list[list[str]], cwd: Path) -> None:
        for argv in commands:
            name = Path(argv[0]).name
            if name == "cd":
                target = argv[1] if len(argv) > 1 else "~"
                cwd = cwd / os.path.expanduser(target)
                continue
            if family == "git" and name == "git":
                cmd = parse_git(argv, cwd)
                if cmd is None:
                    continue
                if cmd.sub == "add":
                    self.check_add(cmd)
                elif cmd.sub == "commit":
                    commit = parse_commit(cmd.args)
                    if self.enabled(ATTRIBUTION, cmd):
                        self.check_attribution(
                            "this commit message", commit.texts, commit.files, cmd.cwd
                        )
                    self.check_commit_scratch(cmd, commit)
                    self.check_main_checkout(cmd)
            elif family == "gh" and name == "gh" and argv[1:2] == ["pr"]:
                if (
                    len(argv) > 2
                    and argv[2] in GH_PR_WRITERS
                    and self.enabled(ATTRIBUTION, Command(argv, cwd))
                ):
                    texts, files = parse_gh_pr(argv[3:])
                    self.check_attribution(f"`gh pr {argv[2]}`", texts, files, cwd)


def main() -> int:
    family = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = sys.stdin.read()
    if family not in {"git", "gh"} or not any(option_on(k) for k in OPTIONS):
        return 0
    data = json.loads(payload or "{}")
    raw = (data.get("tool_input") or {}).get("command") or ""
    cwd = Path(data.get("cwd") or os.getcwd())
    stripped, bodies = strip_heredocs(raw)
    tokens = tokenize(stripped)
    guards = Guards(raw, bodies)
    if tokens is None:
        # Unparseable: fall back to scanning the whole command for attribution lines.
        if guards.enabled(ATTRIBUTION, Command([], cwd)) and re.search(r"\b(git|gh)\b", raw):
            guards.check_attribution("this command", [raw], [], cwd)
    else:
        guards.run(family, split_subcommands(tokens), cwd)
    guards.verdict.emit()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"techne git guard error: {exc}", file=sys.stderr)
        sys.exit(1)
