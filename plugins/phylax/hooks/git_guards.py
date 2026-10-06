#!/usr/bin/env python3
"""Guards on the Bash tool for git commit, git add and gh pr.

register.ts runs this from its tool.call hook on each Bash command that names git
or gh, passing the PreToolUse JSON on stdin and each userConfig option as
CLAUDE_PLUGIN_OPTION_<KEY>, and reads the decision from stdout. A repo turns an
enabled guard off for itself with `git config phylax.<optionInCamelCase> false`.

A crash in one subcommand's check still checks the rest and emits the denies
already found; with none found, the exit status is 1 and register.ts refuses the
command while a blocking guard is on.

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
# Exact case: a tracked docs/commits.md page is not the scratchpad.
SCRATCH_NAME = "COMMITS.md"
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
HEREDOC_RE = re.compile(r"<<(-?)\s*\\?(['\"]?)([A-Za-z_][\w.-]*)\2")
VAR_RE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
# Marker groups split_subcommands emits around a `( ... )` subshell or `$(...)`.
PUSH, POP = "\0(", "\0)"

# Global git options that take the next token as their value.
GIT_GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
# git commit options that take a value; the message-bearing ones are read below.
COMMIT_SHORT_VALUE = set("mFcCt")
# Short options whose value is optional and attached only: `-uall`, `-S<keyid>`.
COMMIT_SHORT_ATTACHED = set("uS")
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
# Long options matched by unique prefix, as git does (`--mess` is `--message`).
COMMIT_LONG_KNOWN = COMMIT_LONG_VALUE | {"--all", "--include", "--only"}
ADD_SUBCOMMANDS = {"add", "stage"}
# Words that run the next command: wrapper -> (flags taking a value, flags naming a dir).
WRAPPERS: dict[str, tuple[set[str], set[str]]] = {
    "env": ({"-u", "-S"}, {"-C", "--chdir"}),
    "command": (set(), set()),
    "builtin": (set(), set()),
    "exec": ({"-a"}, set()),
    "time": ({"-f", "-o"}, set()),
    "nice": ({"-n"}, set()),
    "nohup": (set(), set()),
    "timeout": ({"-k", "-s"}, set()),
    "sudo": ({"-u", "-g", "-h", "-p", "-C", "-r", "-t", "-U"}, {"-D", "--chdir"}),
    "xargs": ({"-I", "-d", "-L", "-P", "-a", "-E", "-s", "-n"}, set()),
}
# Shell keywords that can precede a command in a list or compound command.
RESERVED = {"{", "}", "!", "if", "then", "else", "elif", "fi", "do", "done", "while", "until"}
CD_FLAGS = {"-L", "-P", "-e", "-@"}
# `$(cat FILE)` or `$(< FILE)` inside a message value.
CAT_SUBST_RE = re.compile(r"\$\(\s*(?:cat\s+|<\s*)([^\s()<]+)\s*\)")
# Redirections and commands that create the file they name.
CREATE_REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
CREATORS = {"touch", "tee", "cp", "mv", "install"}
# Commands whose arguments become file content, for a message file the command writes.
WRITERS = {"echo", "printf"}
GH_VALUE_FLAGS = {"-R", "--repo"}
ADD_INTERACTIVE = {"-p", "--patch", "-i", "--interactive", "-e", "--edit"}
# gh pr subcommands that write a PR title/body, or (merge) the squash commit message.
GH_PR_WRITERS = {"create", "new", "edit", "merge"}
GH_TEXT = {"-t": "text", "--title": "text", "--subject": "text", "-b": "text", "--body": "text"}
GH_FILE = {"-F": "file", "--body-file": "file", "-T": "file", "--template": "file"}


def option_on(key: str) -> bool:
    return os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", "").strip().lower() == "true"


def repo_key(key: str) -> str:
    head, *rest = key.split("_")
    return "phylax." + head + "".join(part.capitalize() for part in rest)


def run_git(cwd: Path, repo_args: list[str], *args: str, check: bool = True) -> str | None:
    """Stdout of a git call, or None on failure; `check=False` keeps stdout on any exit."""
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
    return proc.stdout if proc.returncode == 0 or not check else None


def strip_heredocs(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove heredoc bodies and line continuations so the command tokenizes.

    Tracks quoting as bash does: `<<` inside quotes is literal, except inside a
    `$(...)` within double quotes, the `-m "$(cat <<'EOF' ...)"` commit idiom.
    Drops `#` comments and rewrites `$'...'` as a plain single-quoted string.
    Returns the stripped text and each heredoc as (the line that opened it, its body).
    """
    out: list[str] = []
    bodies: list[tuple[str, str]] = []
    pending: list[tuple[str, bool, str]] = []
    stack: list[str] = []  # "'", '"' or "$(" for each open quoting context
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        top = stack[-1] if stack else ""
        if ch == "\n" and pending:
            out.append(ch)
            i += 1
            for delim, dash, opener in pending:
                body: list[str] = []
                while i < n:
                    j = text.find("\n", i)
                    line = text[i:] if j < 0 else text[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if dash else line) == delim:
                        break
                    body.append(line)
                bodies.append((opener, "\n".join(body)))
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
                start = text.rfind("\n", 0, i) + 1
                while start >= 2 and text[start - 2] == "\\":  # back over continued lines
                    start = text.rfind("\n", 0, start - 1) + 1
                stop = text.find("\n", i)
                opener = text[start : n if stop < 0 else stop]
                pending.append((m.group(3), m.group(1) == "-", opener))
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
    """Split at control operators; each `(` and `)` becomes a PUSH or POP marker group."""
    commands: list[list[str]] = [[]]
    for tok in tokens:
        if SEPARATOR_RE.match(tok):
            for ch in tok:
                if ch in "()":
                    commands.append([PUSH if ch == "(" else POP])
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
    return out


def unwrap(argv: list[str]) -> tuple[list[str], list[str]]:
    """Strip leading assignments and wrappers; return the command and any chdir targets."""
    out = list(argv)
    chdirs: list[str] = []
    while out and (ASSIGNMENT_RE.match(out[0]) or out[0] in WRAPPERS or out[0] in RESERVED):
        word = out.pop(0)
        if word not in WRAPPERS:
            continue
        value_flags, chdir_flags = WRAPPERS[word]
        while out and out[0].startswith("-") and out[0] != "-":
            flag, eq, value = out.pop(0).partition("=")
            if flag == "--":
                break
            if flag in chdir_flags and (eq or out):
                chdirs.append(value if eq else out.pop(0))
            elif flag in value_flags and not eq and out:
                out.pop(0)
        if word == "timeout" and out:
            out.pop(0)
    return out, chdirs


def expand(text: str, env: dict[str, str], unknown: str | None = "") -> str:
    """Expand `$VAR` and `${VAR}` from `env`; `unknown=None` leaves unset ones as written."""
    return VAR_RE.sub(
        lambda m: env.get(m.group(1) or m.group(2), m.group(0) if unknown is None else unknown),
        text,
    )


def resolve_dir(cwd: Path, target: str, env: dict[str, str]) -> Path:
    """Join a `cd` or `-C` target, expanding variables from `env`.

    A target that still holds `$` or a backtick (an unknown variable, `$(...)`)
    stays in cwd: the same repo is the likeliest guess.
    """
    expanded = os.path.expanduser(expand(target, env, unknown=None))
    if "$" in expanded or "`" in expanded:
        return cwd
    return cwd / expanded


def read_message_file(path: str, cwd: Path) -> str | None:
    target = Path(os.path.expanduser(path))
    if not target.is_absolute():
        target = cwd / target
    try:
        with open(target, encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_MESSAGE_FILE)
    except OSError:
        return None


def is_scratch_name(path: str) -> bool:
    return Path(path).name == SCRATCH_NAME


def is_scratch_path(spec: str) -> bool:
    """True for a pathspec naming COMMITS.md; exclusion pathspecs never count."""
    if spec.startswith(":"):
        magic = re.match(r"^:(\([^)]*\)|[/!^]*)", spec)
        prefix = magic.group(0) if magic else ":"
        if "!" in prefix or "^" in prefix or "exclude" in prefix:
            return False
        spec = spec[len(prefix) :]
    return is_scratch_name(spec)


def names_scratch(lines: str | None) -> list[str]:
    if not lines:
        return []
    return [p for p in lines.split("\0") if is_scratch_name(p)]


def status_entries(cmd: Command, pathspecs: list[str] | None = None) -> list[tuple[str, str, str]]:
    """Tracked entries of `git status` as (path, X, Y)."""
    args = ["status", "--porcelain=v1", "-z", "--untracked-files=no"]
    if pathspecs:
        args += ["--", *pathspecs]
    out = run_git(cmd.cwd, cmd.repo_args, *args) or ""
    fields = out.split("\0")
    entries: list[tuple[str, str, str]] = []
    i = 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if len(field) < 4:
            continue
        x, y, path = field[0], field[1], field[3:]
        if x in "RC":
            i += 1  # the rename source follows as its own field
        entries.append((path, x, y))
    return entries


class Command:
    """One git or gh invocation with the directory it runs in."""

    def __init__(self, cwd: Path):
        self.cwd = cwd
        self.repo_args: list[str] = []
        self.sub = ""
        self.args: list[str] = []


def parse_git(argv: list[str], cwd: Path, env: dict[str, str]) -> Command | None:
    cmd = Command(cwd)
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in GIT_GLOBAL_VALUE and i + 1 < len(argv):
            value = argv[i + 1]
            if tok == "-C":
                cmd.cwd = resolve_dir(cmd.cwd, value, env)
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
        self.pathspec_file = False


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
            if name not in COMMIT_LONG_KNOWN:
                matches = [o for o in COMMIT_LONG_KNOWN if o.startswith(name)]
                name = matches[0] if len(matches) == 1 else name
            if name in COMMIT_LONG_VALUE:
                if not eq:
                    value = nxt or ""
                    i += 1
                if name in {"--message", "--trailer"}:
                    c.texts.append(value)
                elif name == "--file":
                    c.files.append(value)
                elif name == "--pathspec-from-file":
                    c.pathspec_file = True
            elif name == "--all":
                c.all = True
            elif name == "--include":
                c.include = True
        elif tok.startswith("-") and len(tok) > 1:
            for j, flag in enumerate(tok[1:], start=1):
                if flag in COMMIT_SHORT_ATTACHED:
                    break
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
    def __init__(self, bodies: list[tuple[str, str]]):
        self.bodies = bodies
        self.side_words: set[str] = set()
        self.created_scratch: list[str] = []
        self.writer_text = ""
        self.errors: list[str] = []
        self.verdict = Verdict()
        self._repo_off: dict[tuple[str, tuple[str, ...]], set[str]] = {}

    def enabled(self, key: str, cmd: Command) -> bool:
        if not option_on(key):
            return False
        cache_key = (str(cmd.cwd), tuple(cmd.repo_args))
        if cache_key not in self._repo_off:
            listing = run_git(cmd.cwd, cmd.repo_args, "config", "--get-regexp", r"^phylax\.") or ""
            off = set()
            for line in listing.splitlines():
                name, _, value = line.partition(" ")
                if value.strip().lower() in FALSE_VALUES:
                    off.add(name.lower())
            self._repo_off[cache_key] = off
        return repo_key(key).lower() not in self._repo_off[cache_key]

    def check_attribution(
        self,
        what: str,
        texts: list[str],
        files: list[str],
        cwd: Path,
        keyword: str,
        argv: list[str],
        env: dict[str, str],
    ) -> None:
        """Scan the message text, any message file, and text this command may write into it.

        Values are expanded with the variables known at this point, and the whole
        argv is scanned joined, since nested quotes inside `$(...)` split a value.
        A heredoc counts when the logical line that opens it names the guarded
        subcommand (`keyword`), a message file, or a variable a value uses.
        `$(cat FILE)` and `$(< FILE)` in a value read FILE. A file read from stdin,
        missing, or named by another command here (a redirect, `tee`) may be written
        by this command, so `echo`/`printf` arguments count too. Filters such as grep
        or sed are not scanned: they remove lines.
        """
        texts = [expand(t, env, unknown=None) for t in texts] + [" ".join(argv)]
        files = list(files) + [m.group(1) for t in texts for m in CAT_SUBST_RE.finditer(t)]
        variables = {m.group(1) or m.group(2) for t in texts for m in VAR_RE.finditer(t)}
        names = {keyword, *variables, *(os.path.normpath(f) for f in files)}
        scan = list(texts)
        for opener, body in self.bodies:
            words = {os.path.normpath(w) for w in re.split(r"[\s;&|()<>\"'=$]+", opener) if w}
            if names & words:
                scan.append(body)
        side = {os.path.normpath(w) for w in self.side_words}
        for path in files:
            content = None if path == "-" else read_message_file(path, cwd)
            if content is not None:
                scan.append(content)
            if content is None or os.path.normpath(path) in side:
                scan.append(self.writer_text)
        for text in scan:
            for line in text.splitlines():
                if ATTRIBUTION_RE.search(line):
                    self.verdict.denies.append(
                        f"phylax: {what} carries an attribution line: {line.strip()!r}. "
                        "Remove it and retry. To allow attribution lines in this repo, run "
                        f"`git config {repo_key(ATTRIBUTION)} false`."
                    )
                    return

    def deny_scratch(self, how: str) -> None:
        self.verdict.denies.append(
            f"phylax: {how}. COMMITS.md is a local scratchpad and never goes in a commit. "
            "Unstage it with `git restore --staged COMMITS.md` if needed, and retry without it. "
            f"To allow it in this repo, run `git config {repo_key(COMMITS_MD)} false`."
        )

    def check_add(self, cmd: Command) -> None:
        if not self.enabled(COMMITS_MD, cmd):
            return
        named = [a for a in cmd.args if not a.startswith("-") and is_scratch_path(a)]
        if named:
            self.deny_scratch(f"`git add` names {named[0]}")
            return
        paths = [a for a in cmd.args if not a.startswith("-")]
        broad = not paths or any(a in {".", ":/", "-A", "--all"} for a in cmd.args)
        if self.created_scratch and broad:
            self.deny_scratch(f"this command creates {self.created_scratch[0]} and then stages it")
            return
        if any(a in ADD_INTERACTIVE for a in cmd.args):
            return
        # git add exits 1 when one named path is ignored, yet still adds the rest.
        dry = run_git(cmd.cwd, cmd.repo_args, "add", "--dry-run", *cmd.args, check=False)
        hits = [m.group(1) for m in re.finditer(r"^add '(.*)'$", dry or "", re.MULTILINE)]
        hits = [h for h in hits if is_scratch_name(h)]
        if hits:
            self.deny_scratch(f"`git add` would stage {hits[0]}")

    def check_commit_scratch(self, cmd: Command, commit: Commit) -> None:
        if not self.enabled(COMMITS_MD, cmd):
            return
        named = [p for p in commit.pathspecs if is_scratch_path(p)]
        if named:
            self.deny_scratch(f"`git commit` names {named[0]}")
            return
        # `git status` works before the first commit, which `git diff HEAD` does not.
        # X is index vs HEAD, Y is worktree vs index.
        # A deletion (D) removes the scratchpad from history's next commit; that passes.
        hits: list[str] = []
        specs = bool(commit.pathspecs or commit.pathspec_file)
        entries = [e for e in status_entries(cmd) if is_scratch_name(e[0])]
        for path, x, y in entries:
            staged, changed = x not in " ?D", y not in " ?D"
            if (staged and (not specs or commit.include)) or (commit.all and changed):
                hits.append(path)
            elif commit.pathspec_file and (staged or changed):  # unknown pathspec list
                hits.append(path)
        if commit.pathspecs and not commit.pathspec_file:
            for path, x, y in status_entries(cmd, commit.pathspecs):
                if is_scratch_name(path) and (x not in " ?D" or y not in " ?D"):
                    hits.append(path)
        if hits:
            self.deny_scratch(f"this commit would include {hits[0]}")

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
                f"phylax: committing in the main checkout of {paths[0]} "
                f"while {len(linked)} linked worktree(s) exist, e.g. {linked[0]}. Sessions sharing "
                "this checkout share one index, so another session's staged work can land in this "
                "commit. Prefer a worktree per session."
            )

    def run(self, groups: list[list[str]], cwd: Path) -> None:
        """Check each subcommand; `groups` keep their redirections for the side text."""
        unwrapped = [unwrap(drop_redirections(g)) for g in groups]
        for k, (argv, _) in enumerate(unwrapped):
            name = Path(argv[0]).name if argv else ""
            if name not in {"git", "gh"}:
                self.side_words.update(groups[k])
            for j, tok in enumerate(groups[k]):
                if Path(tok).name in WRITERS:  # also inside `<(printf ...)`
                    self.writer_text += "\n" + "\n".join(groups[k][j + 1 :])
                    break
        env = {**os.environ, "PWD": str(cwd)}
        stack: list[tuple[Path, dict[str, str]]] = []
        dirstack: list[Path] = []
        for k, (argv, chdirs) in enumerate(unwrapped):
            group = groups[k]
            if group == [PUSH]:
                stack.append((cwd, dict(env)))
                continue
            if group == [POP]:
                if stack:
                    cwd, env = stack.pop()
                continue
            if group and all(ASSIGNMENT_RE.match(t) for t in group[group[0] == "export" :]):
                for tok in group[group[0] == "export" :]:
                    name, _, value = tok.partition("=")
                    env[name] = expand(value, env)
                continue
            if not argv:
                continue
            name = Path(argv[0]).name
            if name not in {"git", "gh"}:
                self.note_created(group, argv, cwd)
            run_cwd = cwd
            for target in chdirs:
                run_cwd = resolve_dir(run_cwd, target, env)
            if name in {"cd", "pushd", "popd"}:
                args = [a for a in argv[1:] if a not in CD_FLAGS]
                args = args[1:] if args[:1] == ["--"] else args
                old = cwd
                if name == "popd":
                    cwd = dirstack.pop() if dirstack else cwd
                elif args[:1] == ["-"]:
                    cwd = Path(env.get("OLDPWD", str(cwd)))
                elif name == "pushd" and not args:
                    continue
                else:
                    cwd = resolve_dir(cwd, args[0] if args else "~", env)
                if name == "pushd":
                    dirstack.append(old)
                env["OLDPWD"], env["PWD"] = str(old), str(cwd)
                continue
            try:
                if name == "git":
                    self.check_git(argv, run_cwd, env)
                elif name == "gh":
                    self.check_gh(argv, run_cwd, env)
            except Exception as exc:  # one broken check must not skip the next subcommand
                self.errors.append(f"{' '.join(argv)[:80]}: {exc}")

    def note_created(self, group: list[str], argv: list[str], cwd: Path) -> None:
        """Record a COMMITS.md this subcommand creates; a dry run cannot see it yet."""
        targets = [group[j + 1] for j in range(len(group) - 1) if group[j] in CREATE_REDIRECTS]
        if Path(argv[0]).name in CREATORS:
            targets += [a for a in argv[1:] if not a.startswith("-")]
        for target in targets:
            if is_scratch_name(target) and not (cwd / os.path.expanduser(target)).exists():
                self.created_scratch.append(target)

    def check_git(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        cmd = parse_git(argv, cwd, env)
        if cmd is None:
            return
        if cmd.sub in ADD_SUBCOMMANDS:
            self.check_add(cmd)
        elif cmd.sub == "commit":
            commit = parse_commit(cmd.args)
            if self.enabled(ATTRIBUTION, cmd):
                self.check_attribution(
                    "this commit message",
                    commit.texts,
                    commit.files,
                    cmd.cwd,
                    "commit",
                    argv,
                    env,
                )
            self.check_commit_scratch(cmd, commit)
            self.check_main_checkout(cmd)

    def check_gh(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        words: list[str] = []
        i = 1
        while i < len(argv) and len(words) < 2:
            tok = argv[i]
            if tok in GH_VALUE_FLAGS:
                i += 2
                continue
            if not tok.startswith("-"):
                words.append(tok)
            i += 1
        if (
            len(words) == 2
            and words[0] == "pr"
            and words[1] in GH_PR_WRITERS
            and self.enabled(ATTRIBUTION, Command(cwd))
        ):
            texts, files = parse_gh_pr(argv[1:])
            self.check_attribution(f"`gh pr {words[1]}`", texts, files, cwd, "pr", argv, env)


def main() -> int:
    payload = sys.stdin.read()
    if not any(option_on(k) for k in OPTIONS):
        return 0
    data = json.loads(payload or "{}")
    raw = (data.get("tool_input") or {}).get("command") or ""
    if not re.search(r"\b(git|gh)\b", raw):
        return 0
    cwd = Path(data.get("cwd") or os.getcwd())
    stripped, bodies = strip_heredocs(raw)
    tokens = tokenize(stripped)
    guards = Guards(bodies)
    failed = False
    try:
        if tokens is None:
            # shlex rejected it: scan the whole command for attribution lines, and run
            # the other checks on a rough split.
            if guards.enabled(ATTRIBUTION, Command(cwd)):
                guards.check_attribution("this command", [raw], [], cwd, "", [], {})
            tokens = rough_tokenize(stripped)
        guards.run(split_subcommands(tokens), cwd)
    except Exception as exc:
        guards.errors.append(str(exc))
    for error in guards.errors:
        print(f"phylax git guard error: {error}", file=sys.stderr)
        failed = True
    guards.verdict.emit()
    # Claude Code reads the JSON only on exit 0, so any decision or warning wins.
    return 1 if failed and not (guards.verdict.denies or guards.verdict.warnings) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"phylax git guard error: {exc}", file=sys.stderr)
        sys.exit(1)
