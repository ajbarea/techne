"""Refuse Bash command shapes known to fail, naming the form that works.

git_guards.py calls check() on a Bash call that may hold one of these shapes while its option is
on, before its git checks. Two shapes are refused:

- `block_background_loops`: a background command (Claude Code's `run_in_background`, or any
  Antigravity `run_command`, which backgrounds every command after 10 s) whose `while` or
  `until` loop is bounded neither by a nonzero `timeout` around the shell that runs it nor by
  bash's clock, `$SECONDS`, in its condition or in a test that breaks out of its body. Such a
  wait can run for hours (a network error reads as "pending"). A `while read` loop whose input
  is a file or a here-string ends with it and passes; one fed by a pipe may never end.
- `block_pkill_full`: `pkill -f` and `pgrep -f`. The pattern also matches the shell running the
  call, whose command line holds it, so pkill kills its own shell (exit 144).

The command is read as bash reads it: text in quotes, a heredoc body or a comment is not a
command. The code bash would run is read too: `$(...)`, backticks, `<(...)`, the string of
`bash -c`, `flock -c` and `script -c`, the words of `eval`, `${...}` defaults, and a heredoc
or here-string fed to a shell. A
script file a command runs is not read. These checks catch an honest agent's slip, not a
hostile one: a command spelled to hide the word (`p''kill`) is not seen.

Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from git_checks import SENTINEL_RE, strip_heredocs, unwrap_wrappers, wrapper_name
from git_options import BACKGROUND_LOOPS, PKILL_FULL, SHAPE_WORDS

# Nesting deeper than this is refused, as it cannot be read through; a real command nests
# two or three levels.
MAX_DEPTH = 16
# `$(` nested deeper than this is refused: past it the check cannot finish reading it.
MAX_NEST = 50
SHELLS = {"bash", "sh", "dash", "zsh", "ksh", "ash"}
# Shell options that take the next word as their value.
SHELL_VALUE = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
# Words that may come before a loop keyword at the start of a command.
LEAD = {"!", "{", "if", "then", "elif", "else", "do", "time", "coproc"}
# Wrappers that run the rest of their words as a command, besides git_checks.WRAPPERS.
RUNNERS = {"coproc", "busybox"}
# `$(cat <<EOF ... EOF)`, the whole of a `bash -c` string: the heredoc's body is the code.
CAT_HEREDOC_RE = re.compile("\\$\\(\\s*cat\\s*<<-?\x00H(\\d+)\x00\\s*\\)")
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
FLOCK_VALUE = {"-w", "--timeout", "--wait", "-E", "--conflict-exit-code"}
# flock's long options (util-linux 2.39): getopt_long takes any unique prefix of one.
FLOCK_LONG = (
    "--shared", "--exclusive", "--unlock", "--nonblock", "--nb", "--timeout", "--wait",
    "--conflict-exit-code", "--close", "--no-fork", "--verbose", "--command", "--help", "--version",
)  # fmt: skip
TIMEOUT_VALUE = {"-k", "-s", "--kill-after", "--signal"}
# bash's clock in a loop condition: `$SECONDS`, `${SECONDS}`, or `SECONDS` inside `(( ))`.
SECONDS_RE = re.compile(r"^SECONDS$|\$\{?SECONDS\b")

UNCLOSED = (
    "a quote, substitution or ${...} in the command is never closed, so this check cannot tell "
    "its code from its text (bash rejects it too). Close it, or write the script to a file"
)
TOO_DEEP = (
    f"the command nests code (substitutions, bash -c, eval) more than {MAX_DEPTH} deep, past "
    "what this check reads"
)
LOOP_DENY = (
    "phylax: this background command runs a `while` or `until` loop that no `timeout` bounds, "
    "so it can wait for hours: a network error reads as pending, and a removed worktree leaves "
    "it running. Bound the wait: `timeout 1800 bash -c 'until CHECK; do sleep 30; done'`, or "
    "for CI `gh pr checks N --watch --fail-fast`, or end the loop on a clock: "
    "`until CHECK || [ $SECONDS -gt 1800 ]; do sleep 30; done`."
)
LOOP_DENY_AMP = (
    "phylax: this command backgrounds something (a `&` or `setsid -f`), so every `while` or "
    "`until` loop in it counts as a background loop, and none here is bounded. Bound the loop "
    "itself: wrap only the loop in "
    "`timeout 1800 bash -c 'until CHECK; do sleep 30; done'`, or end it on a clock "
    "(`until CHECK || [ $SECONDS -gt 1800 ]; do sleep 30; done`). Or start the background job "
    "in its own call and wait in the next."
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


class Sub:
    """A command substitution: its tokens and its own substitutions, read in the same pass as
    the text around it, or (a backtick string, whose escapes change its text) its code."""

    def __init__(self, tokens: list[str] | None, subs: list[Sub], code: str) -> None:
        self.tokens = tokens
        self.subs = subs
        self.code = code


class Lexer:
    """Split stripped shell text (strip_heredocs's output) into words and operators, as bash
    does, collecting each command substitution in `subs`."""

    def __init__(self, text: str, nest: int = 0) -> None:
        self.text = text
        self.i = 0
        self.subs: list[Sub] = []
        self.nest = nest  # how many `$(` this lexer reads inside
        # A quote, substitution or `${` the text ends inside: bash rejects such a command, and
        # what follows the opening cannot be told from code, so the check refuses it.
        self.unclosed = False

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
                if j < 0:
                    self.unclosed = True
                    j = n
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
            elif c == "#" and not inword:  # a comment runs to the end of the line
                j = t.find("\n", i)
                self.i = n if j < 0 else j
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
                width = len(op)
                if ("<" in op or ">" in op) and inword and not quoted and "".join(parts).isdigit():
                    op = "".join(parts) + op  # `2>`: the fd is part of the redirection
                    parts, inword = [], False
                end()
                out.append(Op(op))
                self.i += width
        end()
        self.unclosed = self.unclosed or closer  # the text ended before the `)`
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
                return "".join(parts)
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
        self.unclosed = True
        return "".join(parts)

    def substitution(self) -> str:
        """Read `$(...)`, `<(...)`, `>(...)` or a backtick string from self.i, record what it
        runs, and return its text as written. An arithmetic `$((...))` runs only the
        substitutions inside it."""
        t, start = self.text, self.i
        if t[start] == "`":
            body: list[str] = []
            i = start + 1
            while i < len(t) and t[i] != "`":
                if t[i] == "\\" and t[i + 1 : i + 2] in ("`", "\\", "$"):
                    i += 1
                body.append(t[i : i + 1])
                i += 1
            self.unclosed = self.unclosed or i >= len(t)
            self.i = i + 1
            self.subs.append(Sub(None, [], "".join(body)))
            return t[start : self.i]
        if self.nest >= MAX_NEST:
            raise ValueError(
                f"the command nests $(...) more than {MAX_NEST} deep, past what this check reads"
            )
        child = Lexer(t, self.nest + 1)
        child.i = start + 2
        tokens = child.tokens(closer=True)
        self.i = child.i
        self.unclosed = self.unclosed or child.unclosed
        # `$((` is arithmetic only when it closes with `))`; `$( (a)\n)` is a subshell.
        if t.startswith("$((", start) and t[self.i - 2 : self.i] == "))":
            self.subs.extend(child.subs)
        else:
            self.subs.append(Sub(tokens, child.subs, t[start + 2 : self.i - 1]))
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
        """Read a `${...}` expansion from self.i, nested braces included, as written, recording
        the substitutions in it (`${PID:-$(pgrep -x x)}` runs pgrep when PID is unset). Quotes
        in it hide braces (`${x:-'}'}`), inside double quotes too, as bash matches them."""
        t, start, depth = self.text, self.i, 0
        i = start + 1
        while i < len(t):
            if t[i] == "\\":
                i += 1
            elif t[i] == "`" or t.startswith("$(", i):
                self.i = i
                self.substitution()
                i = self.i
                continue
            elif t[i] == "'":
                j = t.find("'", i + 1)
                if j < 0:
                    break
                i = j
            elif t[i] == '"':
                self.i = i + 1
                self.dquote()
                i = self.i
                continue
            elif t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    self.i = i + 1
                    return t[start : self.i]
            i += 1
        self.unclosed = True
        self.i = len(t)
        return t[start:]


class Group(list):
    """One simple command's words and redirections, and how many `(` subshells it sits in."""

    parens = 0
    sep = ""  # the separator before it: `;`, `&&`, `|`, a newline and so on


def commands(tokens: list[str]) -> list[Group]:
    """Split at separators; each simple command keeps its redirections and the separator before
    it. A newline after `&&`, `||` or `|` continues the list."""
    out: list[Group] = [Group()]
    depth = 0
    for tok in tokens:
        if isinstance(tok, Op) and "<" not in tok and ">" not in tok:
            if tok == "\n" and not out[-1] and out[-1].sep in CONTINUES:
                continue
            # A `case` arm's `pattern)` has no `(`: it closes nothing.
            depth = max(0, depth + (tok == "(") - (tok == ")"))
            out.append(Group())
            out[-1].parens = depth
            out[-1].sep = str(tok)
        else:
            out[-1].append(tok)
    return [c for c in out if c]


def command_start(words: list[str]) -> int:
    """Where the command in WORDS starts: past `!`, `{`, `if`, `then`, `do`, `coproc` and the
    like, a `function NAME` header and `time -p`. A quoted word is never a keyword."""
    k = 0
    while k < len(words):
        tok = words[k]
        if isinstance(tok, Op) or getattr(tok, "quoted", False):
            return k
        if tok == "function":
            k += 2
        elif tok == "time":
            k += 1
            while k < len(words) and words[k] in ("-p", "--"):
                k += 1
        elif tok in LEAD:
            k += 1
        else:
            return k
    return k


def loops(command: list[str]) -> str:
    """Whether COMMAND opens a `while` or `until` loop: the keyword unquoted in command
    position, after any `!`, `{`, `if`, `do` and the like. "read" for a loop whose condition is
    `read`, which ends with its input; "wait" for any other; "" for no loop."""
    k = command_start(command)
    tok = command[k] if k < len(command) else ""
    if isinstance(tok, Op) or getattr(tok, "quoted", False) or tok not in ("while", "until"):
        return ""
    rest = [w for w in command[k + 1 :] if not isinstance(w, Op)]
    while rest and "=" in rest[0] and not rest[0].startswith("="):
        rest.pop(0)  # `while IFS= read -r line`
    # `until read` loops forever at the end of its input; only `while read` ends with it.
    return "read" if tok == "while" and rest and rest[0] == "read" else "wait"


def loop_extent(commands: Sequence[list[str]], k: int) -> tuple[int | None, int | None]:
    """Where the body of the loop COMMANDS[K] opens starts (its `do`) and ends (its `done`)."""
    body = next((j for j in range(k + 1, len(commands)) if commands[j][0] == "do"), None)
    if body is None:
        return None, None
    depth = 0
    for j in range(body, len(commands)):
        depth += (commands[j][0] == "do") - (commands[j][0] == "done")
        if depth == 0:
            return body, j
    return body, None


def reads_to_end(commands: Sequence[list[str]], k: int) -> bool:
    """Whether the `read` loop COMMANDS[K] opens takes its input from a file, a heredoc or a
    here-string on its `done`, which ends; a pipe or a process substitution may never end."""
    _, done = loop_extent(commands, k)
    if done is None:
        return False
    command = commands[done]
    for j, tok in enumerate(command):
        if isinstance(tok, Op) and tok.lstrip("0123456789") in ("<", "<<", "<<<"):
            target = command[j + 1] if j + 1 < len(command) else ""
            # A file ends; a pipe, a terminal or a device (`/dev/tty`) may not.
            return not target.startswith("<(") and (
                not target.startswith("/dev/") or target == "/dev/null"
            )
    return False


def _reads_clock(command: list[str]) -> bool:
    """Whether COMMAND is a test of bash's clock: `[ $SECONDS -gt N ]`, `test ...`, `[[ ... ]]`
    or an arithmetic `(( SECONDS > N ))`. An `echo "t=$SECONDS"` only prints it."""
    words = [w for w in command if not isinstance(w, Op)]
    start = command_start(command)
    if words[start : start + 1] in (["while"], ["until"]):
        start += 1  # the condition's own first word
    head = words[start:][:1]
    # A bare `SECONDS` word is the clock only inside `(( ... ))`; `echo SECONDS` prints a word.
    arithmetic = "SECONDS" in words and getattr(command, "parens", 0) >= 2
    if head not in (["["], ["[["], ["test"]) and not arithmetic:
        return False
    return any(SECONDS_RE.search(w) for w in words)


def on_clock(commands: Sequence[list[str]], k: int) -> bool:
    """Whether bash's clock, `$SECONDS`, bounds the loop that COMMANDS[K] opens: read in its
    condition (the commands before the one that starts with `do`), or tested in its body with
    an `exit` or a `break` that leaves this loop as that test's own consequent (`[ $SECONDS
    -gt N ] && break`, a `{ ...; exit 1; }` after `&&`, or `then echo late; exit 1` of an `if`
    on the test): the next command after a `;` or a newline is no consequent of it."""
    body, done = loop_extent(commands, k)
    if any(_reads_clock(c) for c in commands[k : body if body is not None else len(commands)]):
        return True
    if body is None:
        return False
    end = len(commands) if done is None else done
    own = getattr(commands[k], "parens", 0)
    level = 0  # how many loops deep, counting this one
    levels = []
    for j in range(body, end):
        first = commands[j][0]
        level += (first == "do") - (first == "done")
        levels.append(level)
    for j in range(body, end):
        if not _reads_clock(commands[j]):
            continue
        # The exit is the test's own consequent: what follows it up to the next test, loop or
        # the end of its `if`. A `then` follows only a test that opened with `if`.
        before = commands[j - 1][-1:] if j > body else []  # `if` of `if (( SECONDS > N ))`
        lead = commands[j][: command_start(commands[j])]  # `do if` before the test
        opens_if = before in (["if"], ["elif"]) or "if" in lead or "elif" in lead
        in_then, braces = False, 0
        for m in range(j + 1, end):
            nxt = commands[m]
            head = nxt[0]
            if head in STOPPERS or (head == "then" and not opens_if):
                break
            if head == "then":
                in_then = True
                nxt = nxt[1:]
            elif not (getattr(nxt, "sep", "") in ("&&", "||") or braces or in_then):
                break  # a `;` or a newline ends the test's own and-or list
            braces += nxt[: command_start(nxt)].count("{")
            if nxt[:1] == ["}"]:
                # `} }` closes two; a `{` on the test's own command was never counted, so
                # the count stops at zero rather than going negative (and so truthy).
                braces = max(0, braces - sum(w == "}" for w in nxt))
                continue
            if getattr(commands[m], "parens", 0) != own:
                continue
            if _reads_clock(nxt) or _is_test(nxt):
                break
            words = [w for w in nxt[command_start(nxt) :] if not isinstance(w, Op)]
            if words[:1] == ["exit"]:  # `return` outside a function only errors
                return True
            if words[:1] == ["break"]:
                reach = words[1] if len(words) > 1 and words[1].isdigit() else "1"
                if int(reach) >= levels[m - body]:
                    return True
    return False


CONTINUES = ("&&", "||", "|", "|&")
STOPPERS = {"if", "while", "until", "for", "fi", "else", "elif", "done", "do", "case", "esac"}


def _is_test(command: list[str]) -> bool:
    """Whether COMMAND is a bracket test or `test`, which a later `break` may hang on."""
    words = [w for w in command if not isinstance(w, Op)]
    return words[command_start(command) :][:1] in (["["], ["[["], ["test"])


def arithmetic_fors(tokens: list[str]) -> list[bool]:
    """For each arithmetic `for ((init; cond; step))` in TOKENS, in order, whether it has no
    condition and so never ends on its own."""
    found: list[bool] = []
    for k in range(len(tokens) - 2):
        if (
            tokens[k] == "for"
            and not isinstance(tokens[k], Op)
            and isinstance(tokens[k + 1], Op)
            and isinstance(tokens[k + 2], Op)
            and tokens[k + 1 : k + 3] == ["(", "("]
        ):
            parts: list[list[str]] = [[]]
            for tok in tokens[k + 3 :]:
                if isinstance(tok, Op) and tok == ")":
                    break
                if isinstance(tok, Op) and set(tok) == {";"}:
                    parts.extend([] for _ in tok)  # `;;` lexes as one operator
                else:
                    parts[-1].append(tok)
            found.append(len(parts) == 3 and not parts[1])
    return found


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


def _forks(took: list[str]) -> bool:
    """Whether the options TOOK of a `setsid` include -f / --fork (it forks and exits)."""
    return any(t == "--fork" or (t[:1] == "-" and t[1:2] != "-" and "f" in t[1:]) for t in took)


def peel(argv: list[str]) -> tuple[list[str], bool, str | None, bool]:
    """The command ARGV runs once its wrappers are stripped; whether a `timeout` among them
    bounds it (one before a `setsid -f` bounds only the setsid, which exits at once); the code
    of a `flock -c` string, when that is what runs; and whether a `setsid -f` forks it off."""
    bounded = forked = False
    while argv:
        argv, _, wrappers = unwrap_wrappers(argv)
        for name, took in wrappers:
            if name in ("timeout", "gtimeout") and _limits(took):
                bounded = True
            elif name == "setsid" and _forks(took):
                bounded, forked = False, True
        name = wrapper_name(argv[0]) if argv else ""
        if name in RUNNERS:
            argv = argv[1:]
        elif name in ("script", "flock"):
            # Both run a -c / --command string in a shell; flock's first operand is its lock.
            flock = name == "flock"
            code, rest = _command_option(argv[1:], "wE" if flock else "EIOBTmo", stop=flock)
            if code is not None:
                return [], bounded, code, forked
            if name == "script":
                break
            argv = rest[1:]
        else:
            break
    return argv, bounded, None, forked


def _command_option(
    args: list[str], valued: str, stop: bool = False
) -> tuple[str | None, list[str]]:
    """The string of a `-c CMD`, `-xc CMD`, `-cCMD`, `--command CMD` or `--command=CMD` option
    in ARGS (VALUED: the short options taking a value), else None and the operands. STOP reads
    as util-linux flock does: options up to the lock file, then the string only from a
    separate `-c` or `--command` word after it (before it, flock rejects them)."""
    operands: list[str] = []
    j = 0
    while j < len(args):
        tok = args[j]
        j += 1
        if tok == "--":
            operands.extend(args[j:])
            break
        if tok.startswith("--"):
            flag, eq, value = tok.partition("=")
            flag = _long(flag, FLOCK_LONG)
            if flag == "--command" and not stop:
                return (value if eq else (args[j] if j < len(args) else "")), operands
            if flag in FLOCK_VALUE and not eq:
                j += 1
            continue
        if tok[:1] != "-" or tok == "-":
            if stop:
                if args[j : j + 1] in (["-c"], ["--command"]):
                    return (args[j + 1] if j + 1 < len(args) else ""), [tok]
                return None, args[j - 1 :]
            operands.append(tok)
            continue
        for k in range(1, len(tok)):
            if tok[k] == "c" and not stop:
                value = tok[k + 1 :]
                return (value or (args[j] if j < len(args) else "")), operands
            if tok[k] in valued:
                j += not tok[k + 1 :]  # its value is the next word
                break
    return None, operands


def _long(flag: str, names: Sequence[str]) -> str:
    """The long option FLAG names among NAMES, a unique prefix included (getopt_long)."""
    if flag in names:
        return flag
    found = [n for n in names if n.startswith(flag)] if len(flag) > 2 else []
    return found[0] if len(found) == 1 else flag


def _limits(took: list[str]) -> bool:
    """Whether a `timeout` given the words TOOK sets a limit: its duration, the last word, read
    as GNU timeout reads it (0, inf and infinity set none; one this check cannot read counts)."""
    duration = took[-1] if took else ""
    try:
        limit = float(duration.rstrip("smhd") or "x")
    except ValueError:
        return True
    return not (limit == 0 or math.isinf(limit) or math.isnan(limit))


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
        # pkill reads a -SIGNAL from its first argument only; later, `-fpe` is -f -p e.
        if name == "pkill" and i == 1 and SIGNAL_RE.match(tok) and _signal(tok):
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
    has_c = from_stdin = False
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
            if not tok.startswith("--"):
                i += sum(c in "oO" for c in tok[1:])  # each `o` of `-euo pipefail` takes a word
                has_c = has_c or "c" in tok[1:]
                from_stdin = from_stdin or "s" in tok[1:]  # -s: commands from stdin
            continue
        if from_stdin and not has_c:
            return None, True  # the words are positional parameters
        if not has_c and tok in ("-", "/dev/stdin"):
            return None, True
        return (tok if has_c else None), False
    rest = args[i:]
    if has_c:
        return (rest[0] if rest else None), False
    return None, from_stdin or not rest or rest[0] in ("-", "/dev/stdin")


class Scan:
    """What a command runs that these guards refuse, read through the nesting bash runs."""

    def __init__(self) -> None:
        # One per loop: whether a `timeout` or a clock bounds it, and whether `&` detaches it.
        self.loops: list[tuple[bool, bool]] = []
        self.detached = False  # inside a command that `&` runs in the background
        self.full: list[str] = []  # each `pkill -f` or `pgrep -f`: its name

    def text(self, text: str, bounded: bool = False, depth: int = 0) -> None:
        """Read shell source: strip its heredocs, lex it once, then walk what it runs."""
        if depth > MAX_DEPTH:
            raise ValueError(TOO_DEEP)
        text, bodies = strip_heredocs(text)
        # bash runs the substitutions in a heredoc whose delimiter is unquoted.
        for _, body, quoted in bodies:
            if not quoted:
                expanded = Lexer(body)
                expanded.expansions()
                if expanded.unclosed:
                    raise ValueError(UNCLOSED)
                for sub in expanded.subs:
                    self.text(sub.code, bounded, depth + 1)
        lexer = Lexer(text)
        tokens = lexer.tokens()
        if lexer.unclosed:
            raise ValueError(UNCLOSED)
        self.walk(tokens, lexer.subs, bounded, bodies, depth)

    def code(
        self, code: str, bounded: bool, bodies: list[tuple[str, str, bool]], depth: int
    ) -> None:
        """Read CODE, a `bash -c` or `eval` string. When the whole of it is `$(cat <<EOF ...)`,
        the code is that heredoc's body."""
        whole = CAT_HEREDOC_RE.fullmatch(code.strip())
        if whole and int(whole.group(1)) < len(bodies):
            self.text(bodies[int(whole.group(1))][1], bounded, depth + 1)
        else:
            self.text(code, bounded, depth + 1)

    def walk(
        self,
        tokens: list[str],
        subs: list[Sub],
        bounded: bool,
        bodies: list[tuple[str, str, bool]],
        depth: int,
    ) -> None:
        """Walk lexed TOKENS and their substitutions SUBS, read in the same pass."""
        if depth > MAX_DEPTH:
            raise ValueError(TOO_DEEP)
        # A `&` anywhere in this text backgrounds something in it, and which command it
        # backgrounds is not worth telling (`( L ) | cat &`, `if x; then L; fi &`, `x=$(L) &`):
        # every loop in this text, and below it, counts as detached, and a timeout around an
        # enclosing shell no longer bounds them. A command that backgrounds a job and also
        # waits in a loop is refused too, and told to bound the wait.
        outer = self.detached
        amp = any(isinstance(t, Op) and t == "&" for t in tokens)
        self.detached = outer or amp
        held = bounded and not amp
        for sub in subs:
            if sub.tokens is None:
                self.text(sub.code, held, depth + 1)
            else:
                self.walk(sub.tokens, sub.subs, held, bodies, depth + 1)
        found = commands(tokens)
        endless = iter(arithmetic_fors(tokens))
        for k, command in enumerate(found):
            if command[-1:] == ["for"] and command_start(command) == len(command) - 1:
                if next(endless, False):  # an arithmetic for: its header's `;` split the group
                    self.loops.append((held or on_clock(found, k), outer or amp))
            kind = loops(command)
            if kind:
                ends = kind == "read" and reads_to_end(found, k)
                self.loops.append((held or ends or on_clock(found, k), outer or amp))
            self.detached = outer or amp
            self.command(command, held, bodies, depth)
        self.detached = outer

    def command(
        self, command: list[str], bounded: bool, bodies: list[tuple[str, str, bool]], depth: int
    ) -> None:
        words, redirects = split_redirects(command)
        words = words[command_start(words) :]
        argv, wrapped, flock_code, forked = peel(list(words))
        # A timeout around an enclosing shell does not reach what this command forks off with
        # `setsid -f`: it outlives that shell (a `&` in the text is handled by walk).
        bounded = (bounded and not forked) or wrapped
        if forked:
            self.detached = True  # what `setsid -f` runs is in the background of this call
        if flock_code is not None:
            self.text(flock_code, bounded, depth + 1)
            return
        name = wrapper_name(argv[0]) if argv else ""
        if name in ("pkill", "pgrep") and full_match(name, argv[1:]):
            self.full.append(name)
        elif name == "eval":
            self.code(" ".join(argv[1:]), bounded, bodies, depth)
        elif name == "watch":  # runs its words under `sh -c`
            rest = argv[1:]
            while rest and rest[0].startswith("-") and rest[0] != "--":
                flag = rest.pop(0)
                if flag in ("-n", "--interval") and rest:
                    rest.pop(0)
            self.text(" ".join(rest[1:] if rest[:1] == ["--"] else rest), bounded, depth + 1)
        elif name == "su":
            code, _ = _command_option(argv[1:], "gGsTw")
            if code is not None:
                self.text(code, bounded, depth + 1)
        elif name in SHELLS:
            code, reads_stdin = shell_code(argv[1:])
            if code is not None:
                self.code(code, bounded, bodies, depth)
            elif reads_stdin:
                for op, target in redirects:
                    if op == "<<<":
                        self.text(target, bounded, depth + 1)
                    elif op == "<<" and (m := SENTINEL_RE.fullmatch(target.lstrip("-"))):
                        index = int(m.group(1))
                        if index < len(bodies):
                            self.text(bodies[index][1], bounded, depth + 1)


def may_hold(command: str) -> bool:
    return any(word in command for word in SHAPE_WORDS)


def guard_of(deny: str) -> str:
    """The shape option a refusal from check() came from."""
    return BACKGROUND_LOOPS if deny in (LOOP_DENY, LOOP_DENY_AMP) else PKILL_FULL


def check(command: str, background: bool, on: set[str]) -> list[str]:
    """The refusals for COMMAND under the options in ON; BACKGROUND is whether it runs in the
    background."""
    if not may_hold(command):
        return []
    scan = Scan()
    scan.text(command)
    denies: list[str] = []
    # A loop in a background call, or one `&` detaches in a foreground call, must be bounded.
    if BACKGROUND_LOOPS in on and any(
        not bounded and (background or detached) for bounded, detached in scan.loops
    ):
        denies.append(LOOP_DENY if background else LOOP_DENY_AMP)
    if PKILL_FULL in on:
        denies.extend(FULL_DENY[name] for name in dict.fromkeys(scan.full))
    return denies
