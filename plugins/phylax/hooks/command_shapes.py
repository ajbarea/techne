"""Refuse Bash command shapes known to fail, naming the form that works.

git_guards.py calls check() on a Bash call that may hold one of these shapes while its option is
on, before its git checks. Two shapes are refused:

- `block_background_loops`: a `run_in_background` command whose `while` or `until` loop is
  bounded neither by a `timeout` around the shell that runs it nor by `$SECONDS` in its
  condition. Such a wait can run for hours (a network error reads as "pending").
- `block_pkill_full`: `pkill -f` and `pgrep -f`. The pattern also matches the shell running the
  call, whose command line holds it, so pkill kills its own shell (exit 144).

The command is read as bash reads it: text in quotes, a heredoc body or a comment is not a
command. The code bash would run is read too: `$(...)`, backticks, `<(...)`, the string of
`bash -c` and `flock -c`, the words of `eval`, and a heredoc or here-string fed to a shell. A
script file a command runs is not read. These checks catch an honest agent's slip, not a
hostile one: a command spelled to hide the word (`p''kill`) is not seen.

Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import re
from pathlib import Path

from git_checks import SENTINEL_RE, strip_heredocs, unwrap
from git_options import BACKGROUND_LOOPS, PKILL_FULL

# Deeper nesting than this is not read; a real command nests two or three levels.
MAX_DEPTH = 8
SHELLS = {"bash", "sh", "dash", "zsh", "ksh", "ash"}
# Shell options that take the next word as their value.
SHELL_VALUE = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
# Words that may come before a loop keyword at the start of a command.
LEAD = {"!", "{", "if", "then", "elif", "else", "do", "time"}
OPERATORS = (
    "<<<", "&>>", "<<", ">>", "&&", "||", ";;", ";&", "|&", "&>", ">&", "<&", ">|", "<>",
    "<", ">", "&", "|", ";", "(", ")", "\n",
)  # fmt: skip
# pkill and pgrep (procps-ng) short options that take a value, and long ones.
PROC_SHORT_VALUE = set("dgGPstuUFrOq")
PROC_LONG_VALUE = {
    "--delimiter",
    "--pgroup",
    "--group",
    "--parent",
    "--session",
    "--terminal",
    "--euid",
    "--uid",
    "--pidfile",
    "--runstates",
    "--older",
    "--queue",
    "--signal",
    "--cgroup",
    "--ns",
    "--nslist",
}
SIGNALS = set(
    "HUP INT QUIT ILL TRAP ABRT IOT BUS FPE KILL USR1 SEGV USR2 PIPE ALRM TERM STKFLT CHLD CLD "
    "CONT STOP TSTP TTIN TTOU URG XCPU XFSZ VTALRM PROF WINCH IO POLL PWR SYS".split()
)
SIGNAL_RE = re.compile(r"-(?:\d+|(?:SIG)?[A-Z]+[0-9]*|(?:RTMIN|RTMAX)[+-]\d+)$", re.IGNORECASE)
FLOCK_VALUE = {"-w", "--timeout", "-E", "--conflict-exit-code"}
WRAPPED = {"setsid", "stdbuf"}
# bash's clock in a loop condition: `$SECONDS`, `${SECONDS}`, or `SECONDS` inside `(( ))`.
SECONDS_RE = re.compile(r"^SECONDS$|\$\{?SECONDS\b")

LOOP_DENY = (
    "phylax: this background command runs a `while` or `until` loop that no `timeout` bounds, "
    "so it can wait for hours: a network error reads as pending, and a removed worktree leaves "
    "it running. Bound the wait: `timeout 1800 bash -c 'until CHECK; do sleep 30; done'`, or "
    "for CI `gh pr checks N --watch --fail-fast`, or end the loop on a clock: "
    "`until CHECK || [ $SECONDS -gt 1800 ]; do sleep 30; done`."
)
FULL_DENY = {
    "pkill": (
        "phylax: `pkill -f` matches the pattern against every full command line, this call's "
        "own shell included, so it kills that shell (exit 144), and any other session's "
        "matching process. Kill the PID you started (`$!` after starting the job) with "
        "`kill PID`, or, when no other session runs NAME, `pkill -x NAME`."
    ),
    "pgrep": (
        "phylax: `pgrep -f` matches the pattern against every full command line, this call's "
        "own shell included, so it lists that shell too. Use `pgrep -x NAME`, or "
        "`ps -eo pid,args | grep '[n]ame'` (the brackets keep grep from matching itself)."
    ),
}


class Op(str):
    """A shell operator: a separator or a redirection."""


class Word(str):
    """A shell word with its quotes removed; `quoted` when any part of it was quoted."""

    quoted = False


def _word(parts: list[str], quoted: bool) -> Word:
    w = Word("".join(parts))
    w.quoted = quoted
    return w


class Lexer:
    """Split stripped shell text (strip_heredocs's output) into words and operators, as bash
    does, collecting the source of each command substitution in `subs`."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.subs: list[str] = []
        self.nest = 0  # inside a substitution: its own substitutions are read with it

    def tokens(self, closer: bool = False) -> list[str]:
        """Words and operators up to the end, or (CLOSER) the `)` closing a `$(`."""
        t, n = self.text, len(self.text)
        out: list[str] = []
        parts: list[str] = []
        inword = quoted = False
        depth = 0

        def end() -> None:
            nonlocal parts, inword, quoted
            if inword:
                out.append(_word(parts, quoted))
            parts, inword, quoted = [], False, False

        while self.i < n:
            i = self.i
            c = t[i]
            if c in " \t\r":
                end()
                self.i += 1
            elif c == "\\":
                parts.append(t[i + 1 : i + 2])
                inword = True
                self.i += 2
            elif c == "'":
                j = t.find("'", i + 1)
                j = n if j < 0 else j
                parts.append(t[i + 1 : j])
                inword = quoted = True
                self.i = j + 1
            elif c == '"':
                self.i += 1
                parts.append(self.dquote())
                inword = quoted = True
            elif c == "`" or t.startswith("$(", i) or (c in "<>" and t.startswith("(", i + 1)):
                parts.append(self.substitution())
                inword = True
            elif t.startswith("${", i):
                parts.append(self.braces())
                inword = True
            elif closer and c == ")" and depth == 0:
                end()
                self.i += 1
                return out
            else:
                op = next((o for o in OPERATORS if t.startswith(o, i)), None)
                if op is None:
                    parts.append(c)
                    inword = True
                    self.i += 1
                    continue
                depth += (op == "(") - (op == ")")
                if ("<" in op or ">" in op) and inword and not quoted and "".join(parts).isdigit():
                    op = "".join(parts) + op  # `2>`: the fd is part of the redirection
                    parts, inword = [], False
                end()
                out.append(Op(op))
                self.i += len(op)
        end()
        return out

    def dquote(self) -> str:
        """The text of a double-quoted string from after its `"`; a substitution in it runs."""
        t, n = self.text, len(self.text)
        parts: list[str] = []
        while self.i < n:
            i = self.i
            c = t[i]
            if c == '"':
                self.i += 1
                break
            if c == "\\" and t[i + 1 : i + 2] in ('"', "\\", "$", "`"):
                parts.append(t[i + 1])
                self.i += 2
            elif c == "`" or t.startswith("$(", i):
                parts.append(self.substitution())
            elif t.startswith("${", i):
                parts.append(self.braces())
            else:
                parts.append(c)
                self.i += 1
        return "".join(parts)

    def substitution(self) -> str:
        """Read `$(...)`, `<(...)`, `>(...)` or a backtick string from self.i; record the code
        it runs (an arithmetic `$((...))` runs none) and return its text as written."""
        t, start = self.text, self.i
        if t[start] == "`":
            body: list[str] = []
            i = start + 1
            while i < len(t) and t[i] != "`":
                if t[i] == "\\" and t[i + 1 : i + 2] in ("`", "\\", "$"):
                    i += 1
                body.append(t[i])
                i += 1
            self.i = i + 1
            code = "".join(body)
        else:
            arithmetic = t.startswith("$((", start)
            self.i = start + 2
            self.nest += 1
            try:
                self.tokens(closer=True)
            finally:
                self.nest -= 1
            # `$((` is arithmetic only when it closes with `))`; `$( (a)\n)` is a subshell.
            if arithmetic and t[self.i - 2 : self.i] == "))":
                return t[start : self.i]
            code = t[start + 2 : self.i - 1]
        if self.nest == 0:
            self.subs.append(code)
        return t[start : self.i]

    def expansions(self) -> None:
        """Read the whole text as an unquoted heredoc's body, where only `$(...)`, backticks
        and `${...}` are special, recording the code each substitution runs."""
        t, n = self.text, len(self.text)
        while self.i < n:
            i = self.i
            if t[i] == "\\" and t[i + 1 : i + 2] in ("$", "`", "\\"):
                self.i += 2
            elif t[i] == "`" or t.startswith("$(", i):
                self.substitution()
            elif t.startswith("${", i):
                self.braces()
            else:
                self.i += 1

    def braces(self) -> str:
        """Read a `${...}` expansion from self.i, nested braces included, as written."""
        t, start, depth = self.text, self.i, 0
        i = start + 1
        while i < len(t):
            if t[i] == "\\":
                i += 1
            elif t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        self.i = i + 1
        return t[start : self.i]


def commands(tokens: list[str]) -> list[list[str]]:
    """Split at separators; each simple command keeps its redirections."""
    out: list[list[str]] = [[]]
    for tok in tokens:
        if isinstance(tok, Op) and "<" not in tok and ">" not in tok:
            out.append([])
        else:
            out[-1].append(tok)
    return [c for c in out if c]


def loops(command: list[str]) -> bool:
    """Whether COMMAND opens a `while` or `until` loop: the keyword unquoted in command
    position, after any `!`, `{`, `if`, `do` and the like."""
    for tok in command:
        if isinstance(tok, Op) or getattr(tok, "quoted", False):
            return False
        if tok in ("while", "until"):
            return True
        if tok not in LEAD:
            return False
    return False


def on_clock(commands: list[list[str]], k: int) -> bool:
    """Whether the condition of the loop that COMMANDS[K] opens reads `$SECONDS`, bash's clock:
    the words up to the command that starts with `do`."""
    for j in range(k, len(commands)):
        if j > k and commands[j][0] == "do" and not getattr(commands[j][0], "quoted", False):
            return False
        if any(not isinstance(w, Op) and SECONDS_RE.search(w) for w in commands[j]):
            return True
    return False


def split_redirects(command: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """COMMAND's words without its redirections, and each redirection with its target."""
    words: list[str] = []
    redirects: list[tuple[str, str]] = []
    k = 0
    while k < len(command):
        tok = command[k]
        if isinstance(tok, Op):
            redirects.append((tok, command[k + 1] if k + 1 < len(command) else ""))
            k += 2
            continue
        words.append(tok)
        k += 1
    return words, redirects


def peel(argv: list[str]) -> tuple[list[str], bool, str | None]:
    """The command ARGV runs once its wrappers are stripped; whether a `timeout` among them
    bounds it; and the code of a `flock -c` string, when that is what runs."""
    bounded = False
    while argv:
        out, _ = unwrap(argv)
        if any(Path(w).name == "timeout" for w in argv[: len(argv) - len(out)]):
            bounded = True
        argv = out
        name = Path(argv[0]).name if argv else ""
        if name == "flock":
            rest = argv[1:]
            while rest and rest[0].startswith("-") and rest[0] != "--":
                flag = rest.pop(0)
                if flag in ("-c", "--command"):
                    return [], bounded, rest[0] if rest else ""
                if flag in FLOCK_VALUE and rest:
                    rest.pop(0)
            if rest[:1] == ["--"]:
                rest.pop(0)
            rest = rest[1:]  # the lock file or descriptor
            if rest[:1] in (["-c"], ["--command"]):
                return [], bounded, rest[1] if len(rest) > 1 else ""
            argv = rest
        elif name in WRAPPED:
            rest = argv[1:]
            while rest and rest[0].startswith("-") and rest[0] != "-":
                flag = rest.pop(0)
                if flag == "--":
                    break
                if name == "stdbuf" and flag in ("-i", "-o", "-e") and rest:
                    rest.pop(0)
            argv = rest
        else:
            break
    return argv, bounded, None


def full_match(name: str, args: list[str]) -> bool:
    """Whether `pkill`/`pgrep` ARGS select by the full command line (`-f`, `--full`), read as
    procps-ng reads them: grouped short options, values, a `-SIGNAL` for pkill, `--`."""
    i = 0
    while i < len(args):
        tok = args[i]
        i += 1
        if tok == "--":
            return False
        if tok.startswith("--"):
            flag, eq, _ = tok.partition("=")
            if len(flag) > 2 and "--full".startswith(flag):
                return True
            if flag in PROC_LONG_VALUE and not eq:
                i += 1
            continue
        if not tok.startswith("-") or tok == "-":
            continue
        if name == "pkill" and SIGNAL_RE.match(tok) and _signal(tok):
            continue
        for k in range(1, len(tok)):
            if tok[k] == "f":
                return True
            if tok[k] in PROC_SHORT_VALUE:
                if k == len(tok) - 1:
                    i += 1  # its value is the next word
                break
    return False


def _signal(tok: str) -> bool:
    """Whether `-TOK` names a signal (`-9`, `-KILL`, `-sigterm`, `-RTMIN+1`)."""
    word = tok[1:].upper()
    if word.isdigit() or word.startswith(("RTMIN", "RTMAX")):
        return True
    return (word[3:] if word.startswith("SIG") else word) in SIGNALS


def shell_code(args: list[str]) -> tuple[str | None, bool]:
    """The `-c` string a shell given ARGS runs, and whether it reads its commands from stdin
    (no `-c` and no script file)."""
    has_c = False
    i = 0
    while i < len(args):
        tok = args[i]
        i += 1
        if tok == "--":
            break
        if tok in SHELL_VALUE:
            i += 1
            continue
        if tok[:1] in ("-", "+") and len(tok) > 1:
            if not tok.startswith("--") and "c" in tok[1:]:
                has_c = True
            continue
        return (tok if has_c else None), False
    rest = args[i:]
    if has_c:
        return (rest[0] if rest else None), False
    return None, not rest


class Scan:
    """What a command runs that these guards refuse, read through the nesting bash runs."""

    def __init__(self) -> None:
        self.loops: list[bool] = []  # one per loop: whether a `timeout` bounds it
        self.full: list[str] = []  # each `pkill -f` or `pgrep -f`: its name

    def text(
        self,
        text: str,
        bounded: bool = False,
        bodies: list[tuple[str, str, bool]] | None = None,
        depth: int = 0,
    ) -> None:
        if depth > MAX_DEPTH:
            return
        if bodies is None:
            text, bodies = strip_heredocs(text)
            # bash runs the substitutions in a heredoc whose delimiter is unquoted.
            for _, body, quoted in bodies:
                if not quoted:
                    expanded = Lexer(body)
                    expanded.expansions()
                    for code in expanded.subs:
                        self.text(code, bounded, None, depth + 1)
        lexer = Lexer(text)
        tokens = lexer.tokens()
        for code in lexer.subs:
            self.text(code, bounded, bodies, depth + 1)
        found = commands(tokens)
        for k, command in enumerate(found):
            if loops(command):
                self.loops.append(bounded or on_clock(found, k))
            self.command(command, bounded, bodies, depth)

    def command(
        self, command: list[str], bounded: bool, bodies: list[tuple[str, str, bool]], depth: int
    ) -> None:
        words, redirects = split_redirects(command)
        argv, wrapped, flock_code = peel(list(words))
        bounded = bounded or wrapped
        if flock_code is not None:
            self.text(flock_code, bounded, None, depth + 1)
            return
        name = Path(argv[0]).name if argv else ""
        if name in ("pkill", "pgrep") and full_match(name, argv[1:]):
            self.full.append(name)
        elif name == "eval":
            self.text(" ".join(argv[1:]), bounded, None, depth + 1)
        elif name in SHELLS:
            code, reads_stdin = shell_code(argv[1:])
            if code is not None:
                self.text(code, bounded, None, depth + 1)
            elif reads_stdin:
                for op, target in redirects:
                    if op == "<<<":
                        self.text(target, bounded, None, depth + 1)
                    elif op == "<<" and (m := SENTINEL_RE.fullmatch(target.lstrip("-"))):
                        index = int(m.group(1))
                        if index < len(bodies):
                            self.text(bodies[index][1], bounded, None, depth + 1)


def check(command: str, background: bool, on: set[str]) -> list[str]:
    """The refusals for COMMAND under the options in ON; BACKGROUND is its run_in_background."""
    scan = Scan()
    scan.text(command)
    denies: list[str] = []
    if BACKGROUND_LOOPS in on and background and not all(scan.loops):
        denies.append(LOOP_DENY)
    if PKILL_FULL in on:
        denies.extend(FULL_DENY[name] for name in dict.fromkeys(scan.full))
    return denies
