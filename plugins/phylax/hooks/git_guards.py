#!/usr/bin/env python3
"""Guards on the Bash tool for git commit, git add, git push and gh pr/issue/api writes.

register.ts runs this from its tool.call hook on each main-thread Bash command
that names git or gh, passing the PreToolUse JSON on stdin and each userConfig
option as CLAUDE_PLUGIN_OPTION_<KEY>, and reads the decision from stdout. The
hooks.json PreToolUse hook runs it too, for subagents' commands and for every
command when the module did not load; mod_checks() stands it down for a command
the module already checked. A repo turns an enabled guard off for itself with
`git config phylax.<optionInCamelCase> false`.

A crash in one subcommand's check, or a git call that cannot run or times out,
still checks the rest and emits the denies already found; with none found, the
check fails closed while a blocking guard is on (exit 2, which both callers
treat as a refusal).

Parsing is best effort: subcommands inside `$(...)` or `bash -c` are not seen.
Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import body_gate
import secret_scan

ATTRIBUTION = "block_attribution_trailers"
COMMITS_MD = "block_commits_md"
MAIN_CHECKOUT = "warn_main_checkout_commit"
SECRETS = "block_secrets"
BODIES = "block_long_bodies"
OPTIONS = (ATTRIBUTION, COMMITS_MD, MAIN_CHECKOUT, SECRETS, BODIES)
# The guards that refuse a command; MAIN_CHECKOUT only warns.
BLOCKING = (ATTRIBUTION, COMMITS_MD, SECRETS, BODIES)

ATTRIBUTION_RE = re.compile(
    r"Claude-Session|claude\.ai/code/session|Co-Authored-By\s*[:=]\s*Claude"
    r"|Generated with \[?Claude Code",
    re.IGNORECASE,
)
# Exact case: a tracked docs/commits.md page is not the scratchpad.
SCRATCH_NAME = "COMMITS.md"
MAX_MESSAGE_FILE = 1 << 20
# Per git call. A commit runs at most six, inside register.ts's 40 s and hooks.json's 60 s.
GIT_TIMEOUT = 5
FALSE_VALUES = {"false", "no", "off", "0"}
# Never run a repo's fsmonitor, and print paths raw so a basename check sees them.
GIT_BASE = ("git", "-c", "core.fsmonitor=false", "-c", "core.quotePath=false")

# shlex joins adjacent punctuation, so a separator is any run of these, such as "&&\n".
SEPARATOR_RE = re.compile(r"^[;&|()\n]+$")
REDIRECT_RE = re.compile(r"^[<>&]*[<>][<>&]*$")
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
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
GH_GLOBAL_VALUE_FLAGS = {"-R", "--repo"}
ADD_INTERACTIVE = {"-p", "--patch", "-i", "--interactive", "-e", "--edit"}
# gh pr subcommands that write a PR title/body, or (merge) the squash commit message.
GH_PR_WRITERS = {"create", "new", "edit", "merge"}
GH_TEXT = {"-t": "text", "--title": "text", "--subject": "text", "-b": "text", "--body": "text"}
GH_FILE = {"-F": "file", "--body-file": "file", "-T": "file", "--template": "file"}
# gh subcommands that write an issue, PR or comment body, and that body's kind (body_gate).
GH_BODY_KINDS = {
    ("pr", "create"): "PR",
    ("pr", "new"): "PR",
    ("pr", "edit"): "PR",
    ("issue", "create"): "issue",
    ("issue", "new"): "issue",
    ("issue", "edit"): "issue",
    ("pr", "comment"): "comment",
    ("issue", "comment"): "comment",
    ("pr", "review"): "comment",
}
GH_BODY_TEXT = {"-b", "--body"}
# The options each body-writing gh subcommand takes a value for, besides the body's own
# (`-b`, `-F`) and `-R`: the rest are on/off (`gh pr review -a` approves, `-r` requests
# changes). `gh_body` reads short ones grouped as gh's flag parser does.
_EDIT_VALUES = {
    "-t",
    "--title",
    "-B",
    "--base",
    "-m",
    "--milestone",
    "--add-label",
    "--remove-label",
    "--add-assignee",
    "--remove-assignee",
    "--add-reviewer",
    "--remove-reviewer",
    "--add-project",
    "--remove-project",
}
GH_VALUE_FLAGS = {
    ("pr", "create"): {
        "-t",
        "--title",
        "-a",
        "--assignee",
        "-B",
        "--base",
        "-H",
        "--head",
        "-l",
        "--label",
        "-m",
        "--milestone",
        "-p",
        "--project",
        "-r",
        "--reviewer",
        "-T",
        "--template",
        "--recover",
    },
    ("issue", "create"): {
        "-t",
        "--title",
        "-a",
        "--assignee",
        "-l",
        "--label",
        "-m",
        "--milestone",
        "-p",
        "--project",
        "-T",
        "--template",
        "--recover",
    },
    ("pr", "edit"): _EDIT_VALUES,
    ("issue", "edit"): _EDIT_VALUES - {"-B", "--base", "--add-reviewer", "--remove-reviewer"},
}
GH_VALUE_FLAGS[("pr", "new")] = GH_VALUE_FLAGS[("pr", "create")]
GH_VALUE_FLAGS[("issue", "new")] = GH_VALUE_FLAGS[("issue", "create")]
# `gh pr create` options that build the body from commit messages.
GH_FILL = {"-f", "--fill", "--fill-first", "--fill-verbose"}
# A heredoc's opener (`<<EOF`, `<<-'EOF'`), not a here-string (`<<<`).
# strip_heredocs writes each heredoc's delimiter as this sentinel, numbered as `bodies`.
SENTINEL_RE = re.compile("\x00H(\\d+)\x00")
# A command substitution reading a heredoc, `$(cat <<EOF ...)`, after strip_heredocs.
HEREDOC_SUBST_RE = re.compile("\\$\\(([^()]*\x00H\\d+\x00[^()]*)\\)")
# A word of a heredoc redirection after strip_heredocs: `<<`, `<<-`, the sentinel or both.
HEREDOC_WORD_RE = re.compile("(?:<<-?)?(?:-?\x00H\\d+\x00)?")
# Paths gh reads as stdin, as it reads `-`.
STDIN_PATHS = {"/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}
# The place `resolve` tags an unknown command's output with, ` #3)`, never shown.
TAG_RE = re.compile(r" #\d+\)")
# A command substitution with no other inside it, `$(...)`.
SUBST_RE = re.compile(r"\$\(([^()]*)\)")
# strip_heredocs's sentinel for a file read `$(cat FILE)` captured by `capture`.
READ_RE = re.compile("\x00R(\\d+)\x00")
# A variable left in a body once the known ones are expanded: set some other way.
UNSET_VAR_RE = re.compile(r"\$(?:\{[^}]{0,200}\}|[A-Za-z_]\w*)")
# Commands that print one short line, and the words a body counts for it.
SHORT_OUTPUT = {
    ("git", "rev-parse"): 1,
    ("git", "branch", "--show-current"): 1,
    ("date",): 6,
    ("pwd",): 1,
    ("basename",): 1,
}
# Commands that read the files they name and write none.
READERS = {
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "rg",
    "less",
    "more",
    "ls",
    "stat",
    "file",
    "diff",
    "cmp",
    "test",
    "[",
    "echo",
    "printf",
    "true",
    "false",
    "jq",
    "realpath",
    "readlink",
    "basename",
    "dirname",
    "cut",
    "tr",
    "chmod",
    "chown",
    "awk",
}
# Readers that write the files they name given one of these options, short ones
# also inside a cluster (`sed -Ei`, `sort -uo x`).
IN_PLACE = {"sed": ("i", "--in-place"), "sort": ("o", "--output"), "awk": ("i", "--include")}
# Builtins that assign their `NAME=VALUE` words, as a bare assignment does.
DECLARERS = {"export", "declare", "local", "typeset", "readonly"}
# An expansion this check cannot know, in a `gh api` path.
UNKNOWN_PART_RE = re.compile(r"\$\([^()]*\)|\$\{[^}]*\}|\$\w+|\$$|`")
GH_BODY_FILE = {"-F", "--body-file"}
# gh api flags that take a value, and the REST paths whose `body` field is an issue, PR or comment.
GH_API_VALUE = {
    "-X",
    "--method",
    "-H",
    "--header",
    "-q",
    "--jq",
    "-t",
    "--template",
    "--hostname",
    "-p",
    "--preview",
    "--cache",
    "-f",
    "--raw-field",
    "-F",
    "--field",
    "--input",
}
GH_API_KINDS = (
    (
        re.compile(r"repos/[^/\s]+/[^/\s]+/(?:issues|pulls)/(?:\d+/comments|comments/\d+)/?$"),
        "comment",
    ),
    (re.compile(r"repos/[^/\s]+/[^/\s]+/pulls/\d+/reviews(?:/\d+)?/?$"), "comment"),
    (re.compile(r"repos/[^/\s]+/[^/\s]+/pulls/(?:\d+/)?comments/\d+/replies/?$"), "comment"),
    (re.compile(r"repos/[^/\s]+/[^/\s]+/pulls(?:/\d+)?/?$"), "PR"),
    (re.compile(r"repos/[^/\s]+/[^/\s]+/issues(?:/\d+)?/?$"), "issue"),
)
# git add flags that pick hunks or only report; the temporary index takes whole paths instead.
ADD_REPLAY_DROP = ADD_INTERACTIVE | {"-n", "--dry-run", "--ignore-missing"}
PUSH_VALUE = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}
PUSH_ALL = {"--all", "--branches"}
# A replayed add runs the repo's clean filters (git-lfs, git-crypt) on whole files.
ADD_TIMEOUT = 20
PUSH_DELETE = {"-d", "--delete"}
# Subcommands the guards act on or track; anything else may be an alias.
KNOWN_SUBS = {"add", "stage", "commit", "push", "status", "diff", "log", "show"}
# git subcommands that can create or move a ref before a later `git push` in the same command
# line runs; the push scan then cannot know its range at hook time and widens.
REF_MOVERS = {
    "checkout",
    "switch",
    "merge",
    "rebase",
    "reset",
    "pull",
    "cherry-pick",
    "am",
    "branch",
    "commit",
    "tag",
    "revert",
    "stash",
    "update-ref",
    "symbolic-ref",
    "worktree",
}


def option_on(key: str) -> bool:
    return os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}") == "true"


def repo_key(key: str) -> str:
    head, *rest = key.split("_")
    return "phylax." + head + "".join(part.capitalize() for part in rest)


class GitUnavailable(Exception):
    """git did not run or did not finish, so a check cannot tell what it would stage."""


# Set by the first git call that fails to run; later calls fail at once, so one hung git costs
# one GIT_TIMEOUT rather than one per call, well inside the hook's own timeout.
_git_down: str | None = None


def run_git(
    cwd: Path,
    repo_args: list[str],
    *args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
    timeout: float = GIT_TIMEOUT,
) -> str | None:
    """Stdout of a git call, or None when git exits non-zero; `check=False` keeps stdout on any
    exit; `env` adds variables such as GIT_INDEX_FILE. Raises GitUnavailable when git cannot
    start or times out, so the check fails closed. A call given its own `timeout` (a replayed
    add, whose clean filters may be slow) does not mark git down for the calls after it."""
    global _git_down
    if _git_down is not None:
        raise GitUnavailable(_git_down)
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", **(env or {})}
    try:
        proc = subprocess.run(
            [*GIT_BASE, "-C", str(cwd), *repo_args, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        why = f"git {args[0] if args else ''} timed out after {timeout:g}s"
        if timeout == GIT_TIMEOUT:
            _git_down = why
        raise GitUnavailable(why) from exc
    except OSError as exc:
        _git_down = f"git could not run: {exc}"
        raise GitUnavailable(_git_down) from exc
    return proc.stdout if proc.returncode == 0 or not check else None


def strip_heredocs(text: str) -> tuple[str, list[tuple[str, str, bool]]]:
    """Remove heredoc bodies and line continuations so the command tokenizes.

    Tracks quoting as bash does: `<<` inside quotes is literal, except inside a
    `$(...)` within double quotes, the `-m "$(cat <<'EOF' ...)"` commit idiom.
    Drops `#` comments and rewrites `$'...'` as a plain single-quoted string.
    Each heredoc's delimiter becomes a NUL-wrapped sentinel naming its index, so
    the value or redirection that opened it says which body is its own.
    Returns the stripped text and each heredoc as (the line that opened it, its body,
    whether its delimiter was quoted).
    """
    out: list[str] = []
    bodies: list[tuple[str, str, bool]] = []
    pending: list[tuple[str, bool, str, bool]] = []
    stack: list[str] = []  # "'", '"' or "$(" for each open quoting context
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        top = stack[-1] if stack else ""
        if ch == "\n" and pending:
            out.append(ch)
            i += 1
            for delim, dash, opener, quoted in pending:
                body: list[str] = []
                while i < n:
                    j = text.find("\n", i)
                    line = text[i:] if j < 0 else text[i:j]
                    i = n if j < 0 else j + 1
                    # Unquoted, bash joins a line ending in an odd run of backslashes to
                    # the next before it compares the line with the delimiter.
                    while not quoted and j >= 0 and (len(line) - len(line.rstrip("\\"))) % 2:
                        j = text.find("\n", i)
                        more = text[i:] if j < 0 else text[i:j]
                        i = n if j < 0 else j + 1
                        # `<<-` strips the joined line's leading tabs, not the continuation's.
                        line = line[:-1] + more
                    if (line.lstrip("\t") if dash else line) == delim:
                        break
                    body.append(line)
                bodies.append((opener, "\n".join(body), quoted))
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
                # A quoted delimiter (`'EOF'`, `"EOF"`, `\EOF`) keeps the body literal;
                # bash expands an unquoted one's `$VAR` and `$(...)`.
                quoted = bool(m.group(2)) or "\\" in m.group(0)
                # A CRLF opener's delimiter is `EOF\r`, as bash reads it.
                delim = m.group(3) + ("\r" if text[m.end() : m.end() + 2] == "\r\n" else "")
                pending.append((delim, m.group(1) == "-", opener, quoted))
                out.append(f"<<{m.group(1)}\x00H{len(bodies) + len(pending) - 1}\x00")
                i = m.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out), bodies


def stdin_heredoc(group: list[str]) -> int | None:
    """The heredoc a subcommand reads on stdin (`<<` followed by its sentinel), not one
    inside a value; the last, as bash feeds the last of several."""
    found = None
    for j in range(len(group) - 1):
        if group[j] == "<<":
            m = SENTINEL_RE.fullmatch(group[j + 1].lstrip("-"))
            if m:
                found = int(m.group(1))
    return found


def unescape(text: str, keep: bool = False) -> str:
    r"""An unquoted heredoc's backslashes as bash reads them, left to right: `\\` is one
    backslash, `\$` and `\`` their character, a backslash-newline joins the lines, and
    any other backslash stays. KEEP marks the escaped `$` and backtick so a later
    expansion leaves them alone (`heredoc_text` puts them back)."""
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1 : i + 2]
        if ch == "\\" and nxt in ("\\", "$", "`", "\n"):
            if nxt == "$":
                out.append("\x00D\x00" if keep else "$")
            elif nxt == "`":
                out.append("\x00B\x00" if keep else "`")
            elif nxt == "\\":
                out.append("\\")
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def last_redirect(group: list[str], ops: set[str]) -> int:
    """The place of the last of OPS in GROUP, -1 when there is none."""
    return max((j for j, t in enumerate(group) if t in ops), default=-1)


def stdin_redirect(group: list[str]) -> tuple[str, str] | None:
    """A subcommand's last stdin redirect that is no heredoc: `< FILE` or `<<< WORD`. A
    digit before `<` reads as an argument (`comment 12 < b.md`): the tokens lost the
    space that would tell it from a file descriptor."""
    found = None
    for j in range(len(group) - 1):
        if group[j] in {"<", "<<<"}:
            found = (group[j], group[j + 1])
    return found


def tokenize(text: str) -> list[str] | None:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    # shlex joins a run of punctuation: `$(< f)` gives `(<`, which must open a subshell
    # as `(` does, then redirect; a separator run (`);`) is split at its parens later.
    out: list[str] = []
    for tok in tokens:
        if len(tok) > 1 and set(tok) <= set("()<>") and set(tok) & set("()"):
            out.extend(re.findall(r"[()]|[<>]+", tok))
        else:
            out.append(tok)
    return out


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
    # Logical, as bash's cd: `cd ..` out of a removed folder still lands in its parent.
    return Path(os.path.normpath(cwd / expanded))


def read_message_file(path: str, cwd: Path) -> str | None:
    target = Path(os.path.expanduser(path))
    if not target.is_absolute():
        target = cwd / target
    if not os.path.isfile(target):  # a FIFO or a device would hang the hook
        return None
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


_builtins: set[str] | None = None


# Options git accepts at the start of an alias and still runs it; the bool says one value follows.
ALIAS_OPTIONS = {
    "-p": False,
    "--paginate": False,
    "-P": False,
    "--no-pager": False,
    "-c": True,
    "--config-env": True,
}
ALIAS_OPTION_PREFIXES = ("--config-env=", "--exec-path=")


def resolve_alias(cmd: Command) -> None:
    """Expand `git <alias>` to the command it stands for (`alias.ci = commit` makes `git ci`
    a commit), following an alias of an alias as git does, until a loop. git ignores an alias
    that shadows one of its own commands, and a shell alias (`!...`) is left as it is. A git
    call that fails here raises GitUnavailable, so the check fails closed."""
    global _builtins
    seen: set[str] = set()
    while cmd.sub and cmd.sub not in KNOWN_SUBS and cmd.sub not in seen:
        seen.add(cmd.sub)
        alias = run_git(cmd.cwd, cmd.repo_args, "config", "--get", f"alias.{cmd.sub}")
        if not alias or alias.lstrip().startswith("!"):
            return
        if _builtins is None:
            listed = run_git(cmd.cwd, [], "--list-cmds=builtins,main,others")
            if listed is not None:
                _builtins = set(listed.split())
        if cmd.sub in (_builtins or ()):
            return
        words = shlex.split(alias)
        while words and (words[0] in ALIAS_OPTIONS or words[0].startswith(ALIAS_OPTION_PREFIXES)):
            words = words[1 + ALIAS_OPTIONS.get(words[0], False) :]
        if not words or words[0].startswith("-"):
            return  # an option git refuses before an alias's command
        cmd.sub, cmd.args = words[0], words[1:] + cmd.args


def repo_env(cmd: Command) -> dict[str, str]:
    """`--git-dir`/`--work-tree` as the environment a scanner's own git calls read."""
    env: dict[str, str] = {}
    args = cmd.repo_args
    for k in range(0, len(args) - 1, 2):
        env["GIT_DIR" if args[k] == "--git-dir" else "GIT_WORK_TREE"] = args[k + 1]
    return env


def parse_push(args: list[str]) -> tuple[str | None, list[str], set[str]]:
    """(remote, refspecs, flags) of `git push` arguments; `tag <name>` gives the tag."""
    flags: set[str] = set()
    positional: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            positional += args[i + 1 :]
            break
        if tok.startswith("--"):
            name, eq, _ = tok.partition("=")
            flags.add(name)
            if name in PUSH_VALUE and not eq:
                i += 1
        elif tok.startswith("-") and len(tok) > 1:
            if tok == "-o":
                i += 1
            flags.update(f"-{c}" for c in tok[1:])
        else:
            positional.append(tok)
        i += 1
    remote = positional[0] if positional else None
    refspecs = [p for p in positional[1:] if p != "tag"]
    return remote, refspecs, flags


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
    def __init__(self, bodies: list[tuple[str, str, bool]], who: str = ""):
        self.bodies = bodies
        # Files the subcommands so far write: the heredoc each was written from, or None
        # when that text cannot be known here.
        self.written: dict[str, int | None] = {}
        # The stdin heredoc of the subcommand being checked.
        self.stdin_heredoc: int | None = None
        # Its other stdin redirect, `< FILE` or `<<< WORD`, and whether one cannot be followed.
        self.stdin_other: tuple[str, str] | None = None
        self.stdin_odd = False
        self.stdin_redirects = 0
        # The variables as written, before heredocs and files (`run`'s `raw`).
        self.raw: dict[str, str] = {}
        # Each file's text as `resolve` read it, which READ_RE sentinels name.
        self.captured: list[str] = []
        # The agent the call came from ("" for the main thread), for the catch log.
        self.who = who
        # `git add` calls seen so far in this command, which a later commit would include.
        self.pending_adds: list[Command] = []
        # Repos where an earlier git subcommand in this command may move refs before a push runs,
        # and whether any git subcommand ran before (a push alone with a missing ref sends nothing).
        self.moved_in: set[Path] = set()
        self.git_before = False
        self.side_words: set[str] = set()
        self.created_scratch: list[str] = []
        self.writer_text = ""
        self.errors: list[str] = []
        self.verdict = Verdict()
        self._repo_off: dict[tuple[str, tuple[str, ...]], set[str]] = {}

    def enabled(self, key: str, cmd: Command, local: bool = True) -> bool:
        """Whether guard `key` checks this command. A folder that is not there (a removed
        worktree) leaves every lookup in it empty: a blocking guard refuses, the warning
        reports. `gh` (local=False) scans its own text, so it reads no repo there."""
        if not option_on(key):
            return False
        if "\0" in str(cmd.cwd):
            raise ValueError(f"a NUL byte in the folder {cmd.cwd!r}")
        if not cmd.cwd.is_dir():
            if not local:
                return True
            why = (
                f"phylax: this command runs in {cmd.cwd}, which is not an existing folder (a "
                "removed worktree?), so the git guard cannot check it. Run cd to an existing "
                "folder first."
            )
            if key in BLOCKING:
                self.verdict.denies.append(why)
            elif why not in self.errors:
                self.errors.append(why)
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
        for opener, body, _ in self.bodies:
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

    def toplevel(self, cmd: Command) -> Path | None:
        top = run_git(cmd.cwd, cmd.repo_args, "rev-parse", "--show-toplevel")
        return Path(top.strip()) if top and top.strip() else None

    def check_commit_secrets(self, cmd: Command, commit: Commit) -> None:
        """Scan what this commit would add, including the paths an earlier `git add` in this
        command, `-a`, or the commit's own pathspecs stage. Those are staged into a copy of the
        index (GIT_INDEX_FILE), so the real index is untouched and the scan sees only added lines.
        Hunk-picking adds (`-p`) are taken as whole paths: a wider scan, never a narrower one.
        The replayed adds write blobs to the object store even when the commit is refused; they
        stay local and `git gc` removes them."""
        if not self.enabled(SECRETS, cmd):
            return
        top = self.toplevel(cmd)
        if top is None:
            return  # not a work tree: the commit itself will fail
        replay = [
            (a, [x for x in a.args if x not in ADD_REPLAY_DROP])
            for a in self.pending_adds
            if self.toplevel(a) == top
        ]
        if commit.all:
            replay.append((cmd, ["-u"]))
        if commit.pathspec_file:
            replay.append((cmd, ["-A"]))  # an unknown path list: everything it could name
        elif commit.pathspecs:
            replay.append((cmd, ["--", *commit.pathspecs]))
        with tempfile.TemporaryDirectory(prefix="phylax-secrets-") as tmp:
            git_env = repo_env(cmd)
            if replay:
                real = run_git(
                    cmd.cwd,
                    cmd.repo_args,
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "index",
                )
                index = Path(tmp) / "index"
                if real and Path(real.strip()).is_file():
                    shutil.copyfile(real.strip(), index)
                git_env["GIT_INDEX_FILE"] = str(index)
                for add, args in replay:
                    # A path the real add would refuse fails it too; the rest still stage here.
                    run_git(
                        add.cwd,
                        add.repo_args,
                        "add",
                        *args,
                        check=False,
                        env=git_env,
                        timeout=ADD_TIMEOUT,
                    )
            self.scan_secrets("this commit", "commit", top, git_env, None, Path(tmp))

    def check_push_secrets(self, cmd: Command) -> None:
        """Scan the commits this push would send that the remote's tracking refs do not hold yet.
        Stale tracking refs only widen the scan. Catches commits the commit guard never saw."""
        if not self.enabled(SECRETS, cmd):
            return
        top = self.toplevel(cmd)
        if top is None:
            return
        remote, refspecs, flags = parse_push(cmd.args)
        if flags & PUSH_DELETE or flags & {"-n", "--dry-run"}:
            return
        known = (run_git(cmd.cwd, cmd.repo_args, "remote") or "").split()
        if remote is None:
            remote = self.default_remote(cmd)

        def config(key: str) -> str:
            return (run_git(cmd.cwd, cmd.repo_args, "config", "--get-all", key) or "").strip()

        srcs: list[str] = []
        if "--mirror" in flags or (remote in known and config(f"remote.{remote}.mirror") == "true"):
            srcs.append("--all")
        if flags & PUSH_ALL:
            srcs.append("--branches")
        if "--tags" in flags:
            srcs.append("--tags")
        for spec in refspecs:
            src = spec.lstrip("+").split(":", 1)[0]
            if not src or src.startswith("^"):
                continue  # a deletion, or a negative refspec (it only narrows the push)
            if "*" in src:
                srcs.append(f"--glob={src}" if src.startswith("refs/") else "--branches")
            else:
                srcs.append(src)
        if not srcs and not refspecs:
            # A configured push refspec or push.default=matching sends more than HEAD.
            wide = remote in known and bool(config(f"remote.{remote}.push"))
            wide = wide or config("push.default") == "matching"
            srcs = ["--branches"] if wide else ["HEAD"]
        if not srcs:
            return  # only deletions (`:branch`)
        named = [x for x in srcs if not x.startswith("--")]
        unresolved = [
            x
            for x in named
            if run_git(cmd.cwd, cmd.repo_args, "rev-parse", "-q", "--verify", f"{x}^{{commit}}")
            is None
        ]
        if unresolved and not self.git_before:
            return  # git refuses the whole push, so it sends nothing
        widened = top in self.moved_in or bool(unresolved)
        if widened:
            # Run in one line after a checkout, commit or merge, the push sends refs that do not
            # exist or point elsewhere at hook time: scan HEAD, what resolves, and every local
            # branch and tag. Commits made in the same line are the commit scan's.
            srcs = [x for x in srcs if x not in unresolved] + ["HEAD", "--branches", "--tags"]
        # Commits any remote holds are already on a server (a fork's upstream included), so the
        # scan is what no remote has yet; a first push never rescans the whole history.
        # `--` ends the revisions, so a branch named like a folder is never read as a path.
        log_opts = " ".join([*dict.fromkeys(srcs), "--not", "--remotes", "--"])
        what = (
            "this push (scanned wide: every local branch and tag no remote holds, since an "
            "earlier command in this line may move them; run the push as a command of its own "
            "to scan only what it sends)"
            if widened
            else "this push"
        )
        with tempfile.TemporaryDirectory(prefix="phylax-secrets-") as tmp:
            self.scan_secrets(what, "push", top, repo_env(cmd), log_opts, Path(tmp))

    def default_remote(self, cmd: Command) -> str:
        """The remote a bare `git push` uses: pushRemote, pushDefault, the branch's remote,
        else origin."""
        branch = (
            run_git(cmd.cwd, cmd.repo_args, "symbolic-ref", "--short", "-q", "HEAD") or ""
        ).strip()
        keys = [f"branch.{branch}.pushRemote", "remote.pushDefault", f"branch.{branch}.remote"]
        for key in keys if branch else keys[1:2]:
            value = (run_git(cmd.cwd, cmd.repo_args, "config", "--get", key) or "").strip()
            if value:
                return value
        return "origin"

    def scan_secrets(
        self,
        what: str,
        kind: str,
        top: Path,
        git_env: dict[str, str],
        log_opts: str | None,
        tmp: Path,
    ) -> None:
        event = {"kind": kind, "repo": str(top), "agent": self.who}
        try:
            name, findings = secret_scan.scan(kind, top, git_env, log_opts, tmp)
        except secret_scan.ScanError as exc:
            secret_scan.log_event({**event, "outcome": "no_verdict", "reason": str(exc)})
            self.verdict.denies.append(
                f"phylax: {what} was not run because the secret scan gave no verdict: {exc}. "
                "Retry it as a command of its own; if it fails again, stop and ask the user. "
                f"Switching the guard off (`git config {repo_key(SECRETS)} false`) is the user's "
                "call, not yours."
            )
            return
        if not findings:
            return
        secret_scan.log_event(
            {
                **event,
                "outcome": "blocked",
                "engine": name,
                "findings": [f.as_dict() for f in findings],
            }
        )
        shown = "; ".join(f.where() for f in findings[:5])
        more = f" and {len(findings) - 5} more" if len(findings) > 5 else ""
        self.verdict.denies.append(
            f"phylax: {what} would add a secret ({name}): {shown}{more}. Remove it and use a "
            "placeholder the scanner accepts or a value made at runtime (a test fixture included); "
            "unstage with `git restore --staged <file>`, and for a pushed-to-be commit rewrite it "
            "before pushing. Do not silence the scanner: GitHub's own scan would still flag it. "
            "If you believe it is a false positive, stop and ask the user."
        )

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
        # Each variable as written before its heredocs are filled in and its files read,
        # for the body check alone (`raw_value`); `env` holds what bash would.
        raw: dict[str, str] = {}
        stack: list[tuple[Path, dict[str, str], dict[str, str]]] = []
        dirstack: list[Path] = []
        for k, (argv, chdirs) in enumerate(unwrapped):
            group = groups[k]
            if group == [PUSH]:
                stack.append((cwd, dict(env), dict(raw)))
                continue
            if group == [POP]:
                if stack:
                    cwd, env, raw = stack.pop()
                continue
            words = group[group[0] in DECLARERS :] if group else []
            if words and all(ASSIGNMENT_RE.match(t) for t in words):
                for tok in words:
                    name, _, value = tok.partition("=")
                    # `NAME+=value` appends to what NAME held.
                    held = ""
                    if name.endswith("+"):
                        name = name[:-1]
                        held = raw.get(name, env.get(name, ""))
                    if value == "$" and groups[k + 1 : k + 2] == [[PUSH]]:
                        written = self.substitution(groups, k, cwd, env)
                    else:
                        written = self.resolve(expand(value, {**env, **raw}), cwd, env, k)
                    written = held + written
                    raw[name] = written
                    env[name] = self.fill(written)
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
            self.stdin_heredoc = stdin_heredoc(group)
            self.stdin_other = stdin_redirect(group)
            self.stdin_redirects = sum(t in {"<", "<<", "<<-", "<<<"} for t in group)
            # Bash reads the last stdin redirect: a heredoc or a `<`/`<<<`, not both.
            if self.stdin_heredoc is not None and self.stdin_other is not None:
                if last_redirect(group, {"<<", "<<-"}) > last_redirect(group, {"<", "<<<"}):
                    self.stdin_other = None
                else:
                    self.stdin_heredoc = None
            # A stdin redirect `stdin_body` cannot follow: `<&3`, `< <(...)`. Only a bare
            # punctuation token counts: a quoted `<draft>` title is a word.
            self.stdin_odd = any(
                t[:1] == "<" and set(t) <= set("<>&|();") and t not in {"<", "<<", "<<-", "<<<"}
                for t in group
            ) or (
                self.stdin_other is not None
                and self.stdin_other[0] == "<"
                and self.stdin_other[1][:1] in {"<", "&", "("}
            )
            self.raw = raw
            try:
                if name == "git":
                    self.check_git(argv, run_cwd, env)
                elif name == "gh":
                    self.check_gh(argv, run_cwd, env)
            except Exception as exc:  # one broken check must not skip the next subcommand
                self.errors.append(f"{' '.join(argv)[:80]}: {exc}")
            self.note_written(group, argv, run_cwd, env)
            if name not in {"git", "gh"}:
                self.note_touched(argv, run_cwd, env)

    def note_written(
        self, group: list[str], argv: list[str], cwd: Path, env: dict[str, str]
    ) -> None:
        """Record the files this subcommand writes, and the heredoc each holds after it:
        the stdin heredoc of a `cat` or `tee` that writes it whole, else unknown (an
        append, `tee -a`, a `cat` of other files, any other writer)."""
        redirects = [
            (group[j], group[j + 1]) for j in range(len(group) - 1) if group[j] in CREATE_REDIRECTS
        ]
        prog = Path(argv[0]).name if argv else ""
        args = [a for a in argv[1:] if not a.startswith("-") or a == "-"]
        flags = [a for a in argv[1:] if a.startswith("-") and a != "-"]
        writes = [(op, t) for op, t in redirects]
        if prog in {"touch", "tee"}:
            writes += [(">", a) for a in args if a != "-"]
        elif prog in CREATORS and args:
            writes.append((">", args[-1]))  # cp, mv, install: the last name is the target
        whole_cat = prog == "cat" and all(a == "-" for a in args)
        whole_tee = prog == "tee" and not any(
            f in {"-a", "--append"} or (f[1:2] != "-" and "a" in f) for f in flags
        )
        for op, target in writes:
            appends = op in {">>", "&>>"}
            source = self.stdin_heredoc if (whole_cat or whole_tee) and not appends else None
            path = os.path.expanduser(expand(target, env, unknown=None))
            self.written[os.path.normpath(cwd / path)] = source

    def note_touched(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        """A command that may change the files it names (`sed -i`, `ln`, `dd of=`), other
        than a plain reader or a writer `note_written` follows: each of those files'
        text is unknown from here on."""
        prog = Path(argv[0]).name if argv else ""
        short, long = IN_PLACE.get(prog, ("", ""))
        in_place = bool(short) and any(
            a.startswith(long) or (a[:1] == "-" and a[1:2] != "-" and short in a[1:])
            for a in argv[1:]
        )
        if (prog in READERS or prog in IN_PLACE) and not in_place:
            return
        if prog in CREATORS or prog in {"cd", "pushd", "popd"}:
            return
        for arg in argv[1:]:
            if arg.startswith("-") and "=" not in arg:
                continue
            value = (
                arg.partition("=")[2] if "=" in arg and "/" not in arg.partition("=")[0] else arg
            )
            path = os.path.expanduser(expand(value, env, unknown=None))
            self.written[os.path.normpath(cwd / path)] = None

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
        resolve_alias(cmd)
        if cmd.sub in ADD_SUBCOMMANDS:
            self.pending_adds.append(cmd)
            self.check_add(cmd)
        elif cmd.sub == "push":
            self.check_push_secrets(cmd)
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
            self.check_commit_secrets(cmd, commit)
            self.check_main_checkout(cmd)
        if cmd.sub in REF_MOVERS and option_on(SECRETS):
            top = self.toplevel(cmd)
            if top is not None:
                self.moved_in.add(top)
        self.git_before = True

    def check_gh(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        words: list[str] = []
        i = 1
        while i < len(argv) and len(words) < 2:
            tok = argv[i]
            if tok in GH_GLOBAL_VALUE_FLAGS:
                i += 2
                continue
            if not tok.startswith("-"):
                words.append(tok)
            i += 1
        writer = len(words) == 2 and words[0] == "pr" and words[1] in GH_PR_WRITERS
        if writer and self.enabled(ATTRIBUTION, Command(cwd), local=False):
            texts, files = parse_gh_pr(argv[1:])
            self.check_attribution(f"`gh pr {words[1]}`", texts, files, cwd, "pr", argv, env)
        kind = GH_BODY_KINDS.get(tuple(words)) if len(words) == 2 else None
        api = bool(words) and words[0] == "api"
        if (kind or api) and self.enabled(BODIES, Command(cwd), local=False):
            if api:
                kind, body = self.api_body(argv[argv.index("api") + 1 :], cwd, env)
            else:
                body = self.gh_body(argv[1:], cwd, env, tuple(words))
            if kind and body is not None:
                denies, warnings = body_gate.check(kind, body)
                self.verdict.denies.extend(denies)
                self.verdict.warnings.extend(warnings)

    def substitution(self, groups: list[list[str]], k: int, cwd: Path, env: dict[str, str]) -> str:
        """What an unquoted `NAME=$(...)` assigns, as `resolve` leaves it: the tokenizer
        splits it into the assignment `NAME=$`, then a subshell of one command."""
        inner = groups[k + 2] if len(groups) > k + 2 else []
        if groups[k + 3 : k + 4] != [[POP]]:
            return f"$(command #{k})"  # a pipe or a list: its output cannot be known here
        return self.resolve(f"$({shlex.join(inner)})", cwd, env, k)

    def resolve(self, text: str, cwd: Path, env: dict[str, str], tag: int | None) -> str:
        """TEXT with each `$(cat FILE)` or `$(< FILE)` in it read now, as bash runs it,
        into a sentinel `fill` replaces; a heredoc's `$(cat <<EOF)` stays for `fill`.
        Any other command stays as written: its output cannot be known here (with TAG,
        the assignment's place, so two of them name two files)."""

        def one(m: re.Match[str]) -> str:
            inner = m.group(1)
            try:
                argv = shlex.split(inner)
            except ValueError:
                argv = []
            if SENTINEL_RE.search(inner):
                # Only a bare `cat <<EOF` is its heredoc; anything more in it is unknown.
                rest = [a for a in argv[1:] if not HEREDOC_WORD_RE.fullmatch(a)]
                if argv[:1] == ["cat"] and not rest:
                    return m.group(0)
                inner = SENTINEL_RE.sub("", inner)
                return f"$({inner})" if tag is None else f"$({inner} #{tag})"
            # Only in a body: an assignment keeps such output unknown, as a folder.
            words = next(
                (n for short, n in SHORT_OUTPUT.items() if tuple(argv[: len(short)]) == short), 0
            )
            if words and tag is None:
                self.captured.append(" ".join(["x"] * words))
                return f"\x00R{len(self.captured) - 1}\x00"
            path = None
            if argv[:1] == ["cat"]:
                files = [a for a in argv[1:] if a != "--"]
                if len(files) == 1 and not files[0].startswith("-"):
                    path = files[0]
            elif len(argv) == 2 and argv[0] == "<":
                path = argv[1]
            elif len(argv) == 1 and argv[0].startswith("<") and len(argv[0]) > 1:
                path = argv[0][1:]
            read = self.capture(path, cwd, env) if path else None
            if read is not None:
                return read
            return m.group(0) if tag is None else f"$({inner} #{tag})"

        return SUBST_RE.sub(one, text)

    def capture(self, path: str, cwd: Path, env: dict[str, str]) -> str | None:
        """A sentinel for PATH's text as `cat` reads it now: a heredoc an earlier
        subcommand wrote it from, else the file on disk; None when it cannot be known."""
        path = expand(path, env, unknown=None)
        if "$" in path or "`" in path or "\x00" in path:
            return None
        key = os.path.normpath(cwd / os.path.expanduser(path))
        if key in self.written:
            text = self.written_text(self.written[key])
            if text is None:
                return None
        else:
            text = read_message_file(path, cwd) or ""
        # As bash's `$(...)`, which drops the trailing newlines.
        self.captured.append(text.rstrip("\n"))
        return f"\x00R{len(self.captured) - 1}\x00"

    def fill(self, text: str) -> str:
        """TEXT with each `$(cat <<EOF ...)` and each bare heredoc in it replaced by
        that heredoc's body, as bash substitutes it; no sentinel is left."""
        # Of several heredocs on one command, bash feeds the last.
        last = lambda m: self.heredoc(int(SENTINEL_RE.findall(m.group(1))[-1])) or ""  # noqa: E731
        text = HEREDOC_SUBST_RE.sub(last, text)
        text = SENTINEL_RE.sub(lambda m: self.heredoc(int(m.group(1))) or "", text)
        return READ_RE.sub(lambda m: self.captured[int(m.group(1))], text)

    def written_text(self, index: int | None) -> str | None:
        """The text of a file an earlier subcommand wrote from heredoc INDEX: as written
        when its delimiter was quoted or it holds no `$` or backtick, else unknown, since
        bash expanded it there, with that place's folder and variables."""
        if index is None or index >= len(self.bodies):
            return None
        _, text, quoted = self.bodies[index]
        if quoted:
            return text
        marked = unescape(text, keep=True)
        if "$" in marked or "`" in marked:
            return None
        return marked.replace("\x00D\x00", "$").replace("\x00B\x00", "`")

    def heredoc_text(self, index: int | None, cwd: Path, env: dict[str, str]) -> str | None:
        """Heredoc INDEX as a body gets it: a quoted one's text as written, an unquoted
        one's as bash expands it, under the same rule as a body value."""
        if index is None or index >= len(self.bodies):
            return None
        _, text, quoted = self.bodies[index]
        if quoted:
            return text
        # `\$` and `\`` are literal in an unquoted heredoc, as in double quotes.
        held = self.body_value(unescape(text, keep=True), cwd, env)
        return None if held is None else held.replace("\x00D\x00", "$").replace("\x00B\x00", "`")

    def fill_body(self, text: str, cwd: Path, env: dict[str, str]) -> str:
        """`fill` for a body: an unquoted heredoc's text expanded as bash expands it."""

        def last(m: re.Match[str]) -> str:
            return self.heredoc_text(int(SENTINEL_RE.findall(m.group(1))[-1]), cwd, env) or ""

        text = HEREDOC_SUBST_RE.sub(last, text)
        text = SENTINEL_RE.sub(lambda m: self.heredoc_text(int(m.group(1)), cwd, env) or "", text)
        return READ_RE.sub(lambda m: self.captured[int(m.group(1))], text)

    def heredoc(self, index: int | None) -> str | None:
        if index is not None and index < len(self.bodies):
            return self.bodies[index][1]
        return None

    def own_heredoc(self) -> str | None:
        """The heredoc on the stdin of the gh subcommand being checked."""
        return self.heredoc(self.stdin_heredoc)

    def stdin_body(self, cwd: Path, env: dict[str, str]) -> str | None:
        """What the gh subcommand being checked reads on stdin: its heredoc, a `< FILE`
        or a `<<< WORD` here-string (with its newline gone, as gh trims it); None for
        a pipe, which is not seen."""
        if self.stdin_heredoc is not None:
            return self.heredoc_text(self.stdin_heredoc, cwd, env)
        if self.stdin_odd:
            self.verdict.denies.append(
                "phylax: this body comes on stdin through a redirect this check cannot follow, "
                "so its length cannot be checked first. Write the body to a file in its own "
                "call, then send it with --body-file."
            )
            return None
        if self.stdin_other is None:
            return None
        kind, word = self.stdin_other
        if kind == "<" and word in STDIN_PATHS:
            if self.stdin_redirects > 1:
                # It reopens the redirect before it, which this check does not track.
                self.verdict.denies.append(
                    f"phylax: `< {word}` after another stdin redirect reopens it, so the body's "
                    "length cannot be checked first. Give the body one redirect, or a file."
                )
            return None  # the shell's own stdin, passed through: not seen
        if kind == "<":
            return self.body_file(word, cwd, env)
        return self.body_value(word, cwd, env)

    def body_file(self, path: str, cwd: Path, env: dict[str, str]) -> str | None:
        """A body file's text as gh will read it: from the heredoc an earlier subcommand
        wrote it from, refused when it was written here some other way or its name is
        not known here, else from disk."""
        path = expand(path, env, unknown=None)
        if path in STDIN_PATHS:
            return self.stdin_body(cwd, env)
        key = os.path.normpath(cwd / os.path.expanduser(path))
        target = cwd / os.path.expanduser(path)
        if path == "/dev/null":
            return ""
        if not path:
            self.verdict.denies.append(
                "phylax: the body file has an empty name, or is a process substitution "
                "(`<(...)`), whose text this check cannot read first. Write the body to a file "
                "in its own call."
            )
            return None
        if key not in self.written and ("$" in path or "`" in path):
            self.verdict.denies.append(
                f"phylax: the body file {TAG_RE.sub(')', path).replace(chr(0), '')} is named "
                "through a value this "
                "check cannot know, so its length cannot be checked first. Name the file directly."
            )
            return None
        if key not in self.written and os.path.exists(target) and not os.path.isfile(target):
            self.verdict.denies.append(
                f"phylax: the body file {path} is no regular file (a folder, pipe or device), so "
                "its length cannot be checked first. Write the body to a file in its own call."
            )
            return None
        if key in self.written:
            index = self.written[key]
            if index is None:
                self.verdict.denies.append(
                    f"phylax: this command writes or may change {TAG_RE.sub(')', path)} before it "
                    "sends it as a "
                    "body, so its length cannot be checked first. Write the body file in its "
                    "own call."
                )
                return None
            text = self.written_text(index)
            if text is None:
                self.verdict.denies.append(
                    f"phylax: {path} was written from an unquoted heredoc holding `$` or a "
                    "backtick, which bash expanded where it was written, so its length cannot "
                    "be checked first. Quote the delimiter (<<'EOF') or write it in its own call."
                )
            return text
        return read_message_file(path, cwd)

    def body_value(self, value: str, cwd: Path, env: dict[str, str]) -> str | None:
        """A body flag's value as GitHub gets it: the heredoc it opened (also through a
        variable set earlier), a `$(cat FILE)`, or the text with the variables known
        here."""
        # Files are read before heredocs are filled in: a heredoc's `$(cat FILE)` is text.
        value = expand(value, {**env, **self.raw}, unknown=None)
        while (resolved := self.resolve(value, cwd, env, None)) != value:
            value = resolved
        unset = UNSET_VAR_RE.search(value)
        if unset:
            self.verdict.denies.append(
                f"phylax: this body names {unset.group(0)}, which this command does not set "
                "with a plain NAME=value, so its length cannot be checked first. Write the "
                "body to a file in its own call, then send it with --body-file."
            )
            return None
        if "$(" in HEREDOC_SUBST_RE.sub("", value):
            self.verdict.denies.append(
                "phylax: this body holds the output of a command this check cannot run, so "
                "its length cannot be checked first. Write the body to a file in its own "
                "call, then send it with --body-file."
            )
            return None
        return self.fill_body(value, cwd, env)

    def gh_body(
        self, args: list[str], cwd: Path, env: dict[str, str], words: tuple[str, ...] = ()
    ) -> str | None:
        """The body `gh pr|issue create|edit|comment|review` writes, or None without one,
        its options read as gh's flag parser (pflag) reads them: a long option's value
        after `=` or in the next word; short options grouped in one word (`-rb TEXT`), the
        first that takes a value taking the rest of the word or the next word."""
        values = GH_VALUE_FLAGS.get(words, set()) | GH_GLOBAL_VALUE_FLAGS
        body_flags = GH_BODY_TEXT | GH_BODY_FILE
        body: str | None = None
        given = fill = False
        i = 0
        while i < len(args):
            tok = args[i]
            i += 1
            if tok == "--":
                break
            if tok.startswith("--"):
                name, eq, value = tok.partition("=")
                if name in body_flags:
                    if not eq:
                        value = args[i] if i < len(args) else ""
                        i += 1
                    body, given = self.read_body(name, value, cwd, env), True
                elif name in values and not eq:
                    i += 1
                elif name in GH_FILL:
                    fill = True
                continue
            if not tok.startswith("-") or tok == "-":
                continue
            for k in range(1, len(tok)):
                flag = "-" + tok[k]
                if flag in body_flags or flag in values:
                    value = tok[k + 1 :]
                    if len(value) > 1 and value[0] == "=":  # pflag drops it after any letter
                        value = value[1:]
                    elif not value:
                        value = args[i] if i < len(args) else ""
                        i += 1
                    if flag in body_flags:
                        body, given = self.read_body(flag, value, cwd, env), True
                    break
                if flag in GH_FILL:
                    fill = True
        if fill and not given and words in {("pr", "create"), ("pr", "new")}:
            self.verdict.denies.append(
                "phylax: --fill builds this PR body from the commit messages, whose length "
                "this check cannot see first. Pass the body with --body-file instead."
            )
        return body

    def read_body(self, flag: str, value: str, cwd: Path, env: dict[str, str]) -> str | None:
        """The body a body flag with VALUE gives: text, stdin (`-`) or a file."""
        if flag in GH_BODY_TEXT:
            return self.body_value(value, cwd, env)
        if value == "-":
            return self.stdin_body(cwd, env)
        return self.body_file(value, cwd, env)

    def api_body(
        self, args: list[str], cwd: Path, env: dict[str, str]
    ) -> tuple[str | None, str | None]:
        """The kind and `body` field of a `gh api` write to an issue, PR or comment."""
        endpoint = None
        body: str | None = None
        i = 0
        while i < len(args):
            tok = args[i]
            name, eq, value = tok.partition("=") if tok.startswith("--") else (tok, "", "")
            if not tok.startswith("--") and len(tok) > 2 and tok[:2] in GH_API_VALUE:
                name, eq, value = tok[:2], "=", tok[2:]
            if name in GH_API_VALUE:
                if not eq:
                    value = args[i + 1] if i + 1 < len(args) else ""
                    i += 1
                if name in {"-f", "--raw-field", "-F", "--field"}:
                    key, _, field = value.partition("=")
                    if key == "body":
                        if name in {"-F", "--field"} and field == "@-":
                            body = self.stdin_body(cwd, env)
                        elif name in {"-F", "--field"} and field.startswith("@"):
                            body = self.body_file(field[1:], cwd, env)
                        else:
                            body = self.body_value(field, cwd, env)
                elif name == "--input":
                    raw = (
                        self.stdin_body(cwd, env)
                        if value == "-"
                        else self.body_file(value, cwd, env)
                    )
                    try:
                        loaded = json.loads(raw or "null")
                    except ValueError:
                        loaded = None
                    if isinstance(loaded, dict) and isinstance(loaded.get("body"), str):
                        body = loaded["body"]
            elif endpoint is None and not tok.startswith("-"):
                endpoint = tok
            i += 1
        if endpoint is None or body is None:
            return None, None
        path = expand(endpoint, env, unknown=None).split("?")[0]
        for pattern, kind in GH_API_KINDS:
            if pattern.search(path):
                return kind, body
        # A part this check cannot know (`repos/$R/issues/$N/comments`) may be any
        # segments: the body is held to the strictest budget, not skipped.
        if UNKNOWN_PART_RE.search(path) and re.search(r"(?:^|/)(?:issues|pulls)(?:/|$)", path):
            return "comment", body
        return None, None


def mod_checks(data: dict) -> bool:
    """Whether register.ts already checked this call: the hooks.json fallback then stands down.

    The mod names the one call its check passed in PHYLAX_GUARD_CHECKED while that call runs,
    and clears it after. Any other call (a subagent's, which the mod leaves here because only
    this hook gets its cwd, or any call when the module did not load) is checked here.
    """
    checked = os.environ.get("PHYLAX_GUARD_CHECKED")
    return bool(checked) and checked == data.get("tool_use_id")


def main() -> int:
    payload = sys.stdin.read()
    if not any(option_on(k) for k in OPTIONS):
        return 0
    data = json.loads(payload or "{}")
    if mod_checks(data):
        return 0
    raw = (data.get("tool_input") or {}).get("command") or ""
    if not re.search(r"\b(git|gh)\b", raw):
        return 0
    if not data.get("cwd"):
        # python3 starts in the plugin's folder, so its own cwd says nothing about the repo.
        print("phylax git guard error: the hook input names no folder", file=sys.stderr)
        if any(option_on(k) for k in BLOCKING):
            print(
                "phylax: the git guard could not finish its check, so this command was not run.",
                file=sys.stderr,
            )
            return 2
        return 1
    cwd = Path(data["cwd"])
    stripped, bodies = strip_heredocs(raw)
    tokens = tokenize(stripped)
    guards = Guards(bodies, str(data.get("agent_type") or data.get("agent_id") or ""))
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
    if not failed or guards.verdict.denies:
        return 0
    # A check that failed fails closed while a blocking guard is on: exit 2 is a command hook's
    # blocking error (stderr reaches Claude), and register.ts refuses on any non-zero exit.
    if any(option_on(k) for k in BLOCKING):
        print(
            "phylax: the git guard could not finish its check, so this command was not run.",
            file=sys.stderr,
        )
        return 2
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"phylax git guard error: {exc}", file=sys.stderr)
        sys.exit(2 if any(option_on(k) for k in BLOCKING) else 1)
