#!/usr/bin/env python3
"""PreToolUse guards on the Bash tool for git commit, git add and gh pr.

Each guard is off until its userConfig option is switched on in /config, which
Claude Code exports to this process as CLAUDE_PLUGIN_OPTION_<KEY>. A repo turns
an enabled guard off for itself with `git config techne.<optionInCamelCase> false`.

Invoked as `git_guards.py git` or `git_guards.py gh`, one per hooks.json handler,
so a compound command that runs both is checked once per tool. A crash in one
check still emits the denies already found.

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
    r"Claude-Session|claude\.ai/code/session|Co-Authored-By\s*[:=]\s*Claude"
    r"|Generated with \[?Claude Code",
    re.IGNORECASE,
)
SCRATCH_NAME = "commits.md"
TRUE_VALUES = {"1", "true", "yes", "on"}
MAX_MESSAGE_FILE = 1 << 20
# Per git call. A commit runs at most six, inside the 60s hooks.json timeout.
GIT_TIMEOUT = 5
FALSE_VALUES = {"false", "no", "off", "0"}
# Never run a repo's fsmonitor, and print paths raw so a basename check sees them.
GIT_BASE = ("git", "-c", "core.fsmonitor=false", "-c", "core.quotePath=false")

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
            [*GIT_BASE, "-C", str(cwd), *repo_args, *args],
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
    Drops `#` comments and rewrites `$'...'` as a plain single-quoted string.
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
        if top == "$'":
            if ch == "\\" and i + 1 < n:
                nxt = text[i + 1]
                out.append({"n": "\n", "t": "\t", "'": "'\\''"}.get(nxt, nxt))
                i += 2
                continue
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
        if ch == "#" and (i == 0 or text[i - 1] in " \t\n;&|()"):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("$'", i):
            stack.append("$'")
            out.append("'")
            i += 2
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
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return None


def rough_tokenize(text: str) -> list[str]:
    """Whitespace split for a command shlex rejects; quotes are dropped, not honored."""
    words = re.findall(r"&&|\|\||[;|&\n()]|[^\s;|&()]+", text)
    return [w.replace("'", "").replace('"', "") for w in words]


def split_subcommands(tokens: list[str]) -> list[list[str]]:
    commands: list[list[str]] = [[]]
    for tok in tokens:
        if SEPARATOR_RE.match(tok):
            commands.append([])
        else:
            commands[-1].append(tok)
    return [c for c in commands if c]


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
    return [p for p in lines.split("\0") if Path(p).name.lower() == SCRATCH_NAME]


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
                    "permissionDecisionReason": "\n".join(dict.fromkeys(self.denies)),
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
        self.side_text = ""
        self.verdict = Verdict()
        self._repo_off: dict[tuple[str, tuple[str, ...]], set[str]] = {}

    def enabled(self, key: str, cmd: Command) -> bool:
        if not option_on(key):
            return False
        cache_key = (str(cmd.cwd), tuple(cmd.repo_args))
        if cache_key not in self._repo_off:
            listing = run_git(cmd.cwd, cmd.repo_args, "config", "--get-regexp", r"^techne\.") or ""
            off = set()
            for line in listing.splitlines():
                name, _, value = line.partition(" ")
                if value.strip().lower() in FALSE_VALUES:
                    off.add(name.lower())
            self._repo_off[cache_key] = off
        return repo_key(key).lower() not in self._repo_off[cache_key]

    def check_attribution(self, what: str, texts: list[str], files: list[str], cwd: Path) -> None:
        """Scan the message text, any message file, and text this command may write into it.

        A heredoc counts only when the message comes from a file, stdin or `$(...)`. A
        file read from stdin, missing, or named elsewhere in the command (a redirect,
        `tee`, `sed -i`) may be written by the command itself, so the other commands'
        words are scanned as well.
        """
        scan = list(texts)
        if files or any("<<" in t for t in texts):
            scan += self.bodies
        for path in files:
            content = None if path == "-" else read_message_file(path, cwd)
            if content is not None:
                scan.append(content)
            if content is None or path in self.side_text:
                scan.append(self.side_text)
        for text in scan:
            for line in text.splitlines():
                if ATTRIBUTION_RE.search(line):
                    self.verdict.denies.append(
                        f"techne: {what} carries an attribution line: {line.strip()!r}. "
                        "Remove it and retry; if another command in this call already removes "
                        "it, run that command on its own first. To allow attribution lines in "
                        f"this repo, run `git config {repo_key(ATTRIBUTION)} false`."
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
                    cmd.cwd,
                    cmd.repo_args,
                    "diff",
                    "-z",
                    "--name-only",
                    "HEAD",
                    "--",
                    *commit.pathspecs,
                )
            )
        if not commit.pathspecs or commit.include:
            hits += names_scratch(
                run_git(cmd.cwd, cmd.repo_args, "diff", "-z", "--cached", "--name-only")
            )
        if commit.all:
            hits += names_scratch(run_git(cmd.cwd, cmd.repo_args, "diff", "-z", "--name-only"))
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
        if not dirs or len(set(dirs.splitlines())) != 1:
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

    def run(self, family: str, groups: list[list[str]], cwd: Path) -> None:
        """Check each subcommand; `groups` keep their redirections for the side text."""
        commands = [drop_redirections(g) for g in groups]
        self.side_text = "\n".join(
            " ".join(groups[k])
            for k, argv in enumerate(commands)
            if not argv or Path(argv[0]).name not in {"git", "gh"}
        )
        for argv in commands:
            if not argv:
                continue
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
            elif family == "gh" and name == "gh":
                i = 1
                while i < len(argv) and argv[i].startswith("-"):
                    i += 2 if argv[i] in {"-R", "--repo"} else 1
                if (
                    argv[i : i + 1] == ["pr"]
                    and len(argv) > i + 1
                    and argv[i + 1] in GH_PR_WRITERS
                    and self.enabled(ATTRIBUTION, Command(argv, cwd))
                ):
                    texts, files = parse_gh_pr(argv[i + 2 :])
                    self.check_attribution(f"`gh pr {argv[i + 1]}`", texts, files, cwd)


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
    failed = False
    try:
        if tokens is None:
            # shlex rejected it: scan the whole command for attribution lines, and run
            # the other checks on a rough split.
            if guards.enabled(ATTRIBUTION, Command([], cwd)) and re.search(r"\b(git|gh)\b", raw):
                guards.check_attribution("this command", [raw], [], cwd)
            tokens = rough_tokenize(stripped)
        guards.run(family, split_subcommands(tokens), cwd)
    except Exception as exc:
        print(f"techne git guard error: {exc}", file=sys.stderr)
        failed = True
    guards.verdict.emit()
    return 1 if failed and not guards.verdict.denies else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"techne git guard error: {exc}", file=sys.stderr)
        sys.exit(1)
