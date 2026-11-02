"""Run the budget-mode quality trial's tasks in one mode, as PREREGISTRATION.md fixes them.

Each task run: build a history-free workspace at the fix PR's parent, implement with the
mode's model, review with Opus (up to three reviews, a fix session between them), then score
outside any agent session: the hidden tests, the cheat audit and the blind judge. Agent
sessions are `claude -p --restricted` with Bash sandboxed (quality/sandbox.json): no network,
no reads of the source clones or Claude's config.

    uv run python quality/run.py --mode normal --repeats 3 --out quality/results/<name>

Transcripts and workspaces stay under /var/tmp/techne-quality-<uid>; the results folder gets one
`run.json` per task run (scores, usage, flags, judge verdict, diff) that analyze.py reads.
"""

from __future__ import annotations

import argparse
import ast
import fcntl
import fnmatch
import functools
import hashlib
import itertools
import json
import os
import pathlib
import random
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Sequence, Set
from typing import Any
from xml.etree import ElementTree

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SANDBOX = HERE / "sandbox.json"
# Outside /home: the sandbox denies all of /home, where other tools keep clones of these
# repos (and so their fixes). Private to this user.
WORK = pathlib.Path(f"/var/tmp/techne-quality-{os.getuid()}")
# Only the run in progress lives in LIVE; finished runs, score copies and task checks sit in
# folders quality/sandbox.json denies to every agent's shell, so no run reads another's
# answer or a restored hidden test.
LIVE, DONE, SCORE, CHECK = (WORK / d for d in ("live", "done", "score", "check"))
# What a session's shell may read under WORK: its own run, the tools, and the elenchus copy.
TOOLS = WORK / "tools"  # uv and uv's Pythons: tasks' environments live here
# One seed uv cache per task, holding only what that task's setup builds from its parent
# tree. Sessions cannot read the seeds; each session and each scoring gets its own copy,
# since `uv run` caches the tree it syncs: a shared cache would carry one run's change, a
# gold fix, or a later task's parent (which can hold an earlier task's fix) to a session.
SEEDS = WORK / "seeds"
SEEDS_VERSION = "3"
HOMES = pathlib.Path("/home")  # file tools may read none of it but this run's saved outputs
HIDDEN = ("done", "score", "check", "judge", "seeds")
JUDGE_CWD = WORK / "judge-cwd"  # one neutral folder: Claude Code shows the judge its cwd


def clean_env() -> dict[str, str]:
    """The harness's environment without the caller's virtualenv, which would point a task's
    commands at the wrong interpreter."""
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")}
    return {**env, "DISABLE_AUTOUPDATER": "1"}  # one Claude Code version for the whole set


def prepare_seeds() -> None:
    """Drop seeds an older harness wrote (a shared cache that may hold a scored tree)."""
    marker = WORK / "seeds-version"
    with lock():
        if marker.exists() and marker.read_text() == SEEDS_VERSION:
            return
        shutil.rmtree(TOOLS / "uv-cache", ignore_errors=True)
        shutil.rmtree(SEEDS, ignore_errors=True)
        WORK.mkdir(parents=True, exist_ok=True)
        tmp = marker.with_suffix(".tmp")
        tmp.write_text(SEEDS_VERSION)
        os.replace(tmp, marker)


def seed_of(task: dict) -> pathlib.Path:
    return SEEDS / task["id"]


def tool_env(cache: pathlib.Path) -> dict[str, str]:
    """uv and its Pythons inside WORK, so environments built at setup still run when a
    session's shell cannot read /home. Environments copy files out of CACHE rather than
    link to it, so editing an installed package never changes the cache."""
    (TOOLS / "bin").mkdir(parents=True, exist_ok=True)
    uv = TOOLS / "bin" / "uv"
    if not uv.exists():
        found = shutil.which("uv")
        if not found:
            raise RuntimeError("uv is not on PATH")
        shutil.copy2(found, uv)
    return {
        "UV_CACHE_DIR": str(cache),
        "UV_LINK_MODE": "copy",
        "UV_PYTHON_INSTALL_DIR": str(TOOLS / "python"),
        "UV_PYTHON_PREFERENCE": "only-managed",
    }


def private_cache(task: dict, dest: pathlib.Path) -> pathlib.Path:
    """A copy of TASK's seed cache at DEST, for one session's or one scoring's writes.
    Callers hold lock(), so no setup writes the seed while it is copied."""
    shutil.rmtree(dest, ignore_errors=True)
    if seed_of(task).exists():
        shutil.copytree(seed_of(task), dest, symlinks=True)
    else:
        dest.mkdir(parents=True)
    return dest


MODELS = {"normal": "claude-opus-5-5", "budget": "claude-sonnet-5-5"}
REVIEWER = JUDGE = "claude-opus-5-5"
AGENT_TOOLS = "Read,Edit,Write,Glob,Grep,Bash"
REVIEW_TOOLS = "Read,Glob,Grep,Bash"
MAX_REVIEWS = 3
TURNS, TIMEOUT = 60, 20 * 60
TEST_TIMEOUT = 15 * 60
SEED = 20261029

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"enum": ["Blocking", "Should-fix"]},
                    "class": {"type": "string"},
                    "anchor": {"type": "string"},
                    "scenario": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "class", "anchor", "scenario", "fix"],
            },
        }
    },
    "required": ["findings"],
}
CRITERIA = ("root_cause", "inputs_covered", "no_regression", "regression_test", "scope")
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        **{c: {"type": "integer", "minimum": 0, "maximum": 3} for c in CRITERIA},
        "cheated": {"type": "boolean"},
        "cheated_reason": {"type": "string"},
        "blocking_defect": {"type": "boolean"},
        "blocking_reason": {"type": "string"},
    },
    "required": [*CRITERIA, "cheated", "cheated_reason", "blocking_defect", "blocking_reason"],
}

# A test file, by path; test configuration a run must not touch.
TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$|[^/]*\.test\.[jt]s$)")
TEST_CONFIG = re.compile(
    r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml|__snapshots__/"
    r"|[^/]*\.snap)"
)
# Programs that try to reach past the sandbox: network tools, git remotes, GitHub. A URL
# alone is not one: the sandbox has no network, and a test may parse one. The text match
# below decides; the shell parser only clears a match it can show is data, such as a grep
# pattern or `git stash push`, and adds programs the text hides (`$CMD` set to curl).
NET_PROGRAMS = frozenset({"gh", "curl", "wget", "ssh", "scp", "nc"})
GIT_REMOTE = frozenset({"fetch", "clone", "pull", "push", "remote", "ls-remote"})
# Git subcommands that never reach a remote or run a configured program from their words;
# any other (lfs, submodule, config, an alias) leaves a text match standing.
GIT_LOCAL = frozenset(
    {"status", "log", "diff", "show", "add", "commit", "stash", "checkout", "switch"}
    | {"restore", "reset", "branch", "tag", "rev-parse", "ls-files", "grep", "blame", "init"}
    | {"mv", "rm", "describe", "shortlog", "reflog", "rev-list", "cat-file", "show-ref"}
    | {"ls-tree", "diff-tree", "diff-index", "diff-files", "merge-base", "check-ignore"}
    | {"name-rev", "for-each-ref", "symbolic-ref", "hash-object", "count-objects", "version"}
)
GIT_OPTION_ARG = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--attr-source"}
)
# git's own options that take no value; any other before the subcommand leaves it unknown.
GIT_FLAGS = frozenset(
    {"--no-pager", "-p", "--paginate", "-P", "--bare", "--no-replace-objects"}
    | {"--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs"}
    | {"--no-optional-locks", "--no-advice", "--exec-path", "--html-path", "--man-path"}
    | {"--info-path", "-v", "--version", "-h", "--help", "--no-lazy-fetch"}
)
# Variables whose value a program runs as a command (git's, a pager, an editor, a shell's
# start-up file), so the value is not data.
EXECUTED_VAR = re.compile(
    r"GIT_\w+|\w*(?:PAGER|EDITOR|COMMAND|ASKPASS|PROXY)\w*|VISUAL|BASH_ENV|ENV|LESSOPEN"
    r"|LESSCLOSE|PYTHONSTARTUP"
)
SHELLS = frozenset({"bash", "sh", "dash", "zsh", "ksh"})
SHELL_OPTION_ARG = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
CHDIR = {"env": ("-C", "--chdir"), "sudo": ("-D", "--chdir")}  # run the program in a folder
# Programs that run the rest of their words as a command: how many words follow their own
# options before the program (timeout's duration, flock's file), and their options that take
# a value. An option in UNREAD hands a shell a command string, which is read as `sh -c`.
WRAPPERS: dict[str, tuple[int, frozenset[str]]] = {
    "env": (0, frozenset({"-u", "--unset", "-C", "--chdir"})),
    "command": (0, frozenset()),
    "builtin": (0, frozenset()),
    "exec": (0, frozenset({"-a"})),
    "nohup": (0, frozenset()),
    "time": (0, frozenset({"-f", "--format", "-o", "--output"})),
    "nice": (0, frozenset({"-n", "--adjustment"})),
    "sudo": (
        0,
        frozenset(
            {"-u", "--user", "-g", "--group", "-C", "--close-from", "-D", "--chdir", "-h"}
            | {"--host", "-p", "--prompt", "-r", "--role", "-t", "--type", "-U", "-T"}
            | {"--other-user", "--command-timeout"}
        ),
    ),
    "stdbuf": (0, frozenset({"-i", "-o", "-e"})),
    "xargs": (
        0,
        frozenset(
            {"-a", "--arg-file", "-d", "--delimiter", "-E", "-I", "-L", "-n", "--max-args"}
            | {"-P", "--max-procs", "-s", "--max-chars"}
        ),
    ),
    "timeout": (1, frozenset({"-s", "--signal", "-k", "--kill-after"})),
    "flock": (1, frozenset({"-w", "--timeout", "-E", "--conflict-exit-code"})),
    # `uv run PROGRAM`: the subcommand is the one word skipped.
    "uv": (
        1,
        frozenset(
            {"--with", "--with-editable", "--with-requirements", "--python", "-p", "--project"}
            | {"--directory", "--env-file", "--extra", "--group", "--only-group", "--no-group"}
            | {"--package", "--index", "--default-index", "--index-url", "--extra-index-url"}
            | {"--find-links", "-f", "--config-file", "--cache-dir", "--color", "--from"}
        ),
    ),
}
WRAPPERS["uvx"] = (0, WRAPPERS["uv"][1])
UNREAD = {"env": ("-S", "--split-string"), "flock": ("-c", "--command"), "sudo": ("-s", "-i")}
# Where a matched program name is only data: the arguments of a search, which print lines of
# files; and the stages a printed line may pass through without being run. WRITERS write
# their words or a heredoc, which a later call may run, so their words are never cleared.
SEARCHES = frozenset({"grep", "egrep", "fgrep", "rg"})
FILTERS = SEARCHES | frozenset({"head", "tail", "wc", "uniq", "cut", "tr", "cat", "nl", "column"})
WRITERS = frozenset({"cat", "tee", "printf", "echo"})
PYTHON = re.compile(r"python(?:3(?:\.\d+)?)?$")
# Python calls that run a command line through a shell, and those that run a program.
PY_SHELL = frozenset(
    {"os.system", "os.popen", "subprocess.getoutput", "subprocess.getstatusoutput"}
    | {"asyncio.create_subprocess_shell"}
)
PY_EXEC = frozenset(
    {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output"}
    | {"subprocess.Popen", "pty.spawn", "asyncio.create_subprocess_exec", "os.posix_spawn"}
    | {"os.posix_spawnp"}
    | {f"os.exec{s}" for s in ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")}
    | {f"os.spawn{s}" for s in ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")}
)
# Python that reaches a function by a name the reader cannot follow.
PY_INDIRECT = frozenset({"exec", "eval", "compile", "__import__", "getattr", "importlib"})
# The text-only reading: what a command must contain to be a network leak at all, and the
# whole check for a command the shell parser cannot read cleanly.
LEAK = re.compile(
    r"\b(?:gh|curl|wget|ssh|scp|nc)\s"
    r"|\bgit\b[^|;&\n]*?\s(?:fetch|clone|pull|push|remote|ls-remote)\b"
)
LEAK_BYTES = re.compile(LEAK.pattern.encode())
# An absolute path outside the system folders, and a climb of two or more levels.
HOME_PATH = re.compile(r"(?<![\w.])/(?:home|root|tmp|mnt|var/tmp)(?:/[^\s'\";|&)]*)?")
REGISTERED = ("/home", "/root", "/tmp", "/mnt", "/var/tmp")
TEXT_LABEL = "text: "  # leads a leak flag the parser found only as text
CLEARED_LABEL = "cleared: "  # every match the parser shows inert; still a registered flag
EXTRA_LABEL = "extra: "  # the parser shows a reach the registered rule misses
RESTRICTED = re.compile(f"(?:{'|'.join(REGISTERED)})(?:/|$)")
ESCAPE = re.compile(r"(?:^|[\s'\"=])(?:\.\./){2,}")
# What separates path-like tokens inside a word or a block of text.
PATH_SPLIT = re.compile(r"[\s'\"`;|&()<>=:,\[\]{}]+")
WORD_SPLIT = re.compile(r"[\s'\"`;|&()<>=:]+")  # PATH_SPLIT, keeping braces and globs whole
BRACE = re.compile(r"\{([^{},]*,[^{}]*)\}")  # an innermost comma brace
GLOB = re.compile(r"[*?]|\[[^\]/]+\]")
# Options of grep and rg that take the next word as their value.
SEARCH_VALUE = {
    "grep": frozenset({"-m", "-A", "-B", "-C", "-d", "-D", "--max-count", "--context", "--label"}),
    "rg": frozenset(
        {"-m", "-A", "-B", "-C", "-g", "-t", "-T", "-j", "-M", "-r", "-E", "-d", "--max-count"}
        | {"--context", "--glob", "--iglob", "--type", "--type-not", "--threads", "--replace"}
        | {"--max-columns", "--encoding", "--max-depth", "--sort", "--sortr"}
    ),
}
CWD_RESET = re.compile(r"Shell cwd was reset to (/[^\s\"\\]+)")
BASH = None  # the tree-sitter parser, built on first use
LITERAL = re.compile(r"""(?:"([^"\\\n]{4,})"|'([^'\\\n]{4,})'|\b(\d{3,}(?:\.\d+)?)\b)""")
# A name the parent tree lacks, as a hidden test's failure on it reads.
MISSING_NAME = re.compile(
    r"has no attribute '(\w+)'|cannot import name '(\w+)'|No module named '([\w.]+)'"
    r"|does not have the attribute '(\w+)'"  # mock.patch
)
# A name the parent refuses outright: with the gold patch passing, the fix added it or
# stopped passing it; either way the report must name it in a code span.
REFUSED_NAME = re.compile(r"unexpected keyword argument '(\w+)'|invalid choice: '([\w-]+)'")
UNRECOGNIZED = re.compile(r"unrecognized arguments: ([^\n]+)")  # argparse lists them all
# A module a test loads by its path, which fails on the parent as a missing file.
MISSING_FILE = re.compile(
    r"No such file or directory: '([^'\n]+)'|can't open file '([^'\n]+)'"  # Python, python3
    r"|(?:^|\s)(\S+\.\w+): No such file or directory"  # bash
)
# Files whose words are prose, never names the code defines.
CODE_SUFFIX = (".py", ".pyi", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".rs", ".go")
FLAG = re.compile(r"(?<![\w-])--?[A-Za-z][\w-]*")
# A quoted string in a file that is not Python, escapes included.
QUOTED = re.compile(r""""((?:[^"\\\n]|\\.){4,})"|'((?:[^'\\\n]|\\.){4,})'""")
WORD = re.compile(r"<?[^\W_][\w'.~$<>/-]*|→")


def sh(cmd: Sequence[str], cwd: pathlib.Path | None = None, **kw) -> subprocess.CompletedProcess:
    # A file the agent wrote in another encoding must not crash the harness.
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, errors="replace", check=False, **kw
    )


def git(repo: pathlib.Path, *args: str) -> str:
    out = sh(["git", "-C", str(repo), *args])
    if out.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip()[:300]}")
    return out.stdout


def load_tasks(path: pathlib.Path) -> list[dict]:
    tasks = tomllib.loads(path.read_text(encoding="utf-8"))["task"]
    for t in tasks:
        t["clone"] = pathlib.Path(os.path.expanduser(t["clone"]))
    return tasks


def workspace(task: dict, dest: pathlib.Path) -> None:
    """The parent tree with no history and the fix's new test files left out."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    pipe = (
        f"set -o pipefail; git -C {shlex.quote(str(task['clone']))} archive "
        f"{shlex.quote(task['parent'])} | tar -x -C {shlex.quote(str(dest))}"
    )
    out = sh(["bash", "-c", pipe])
    if out.returncode:
        raise RuntimeError(f"archive: {out.stderr.strip()[:300]}")
    existed = set(git(task["clone"], "ls-tree", "-r", "--name-only", task["parent"]).split("\n"))
    for rel in task["hidden_tests"]:
        if rel not in existed:
            (dest / rel).unlink(missing_ok=True)
    for cmd in (
        "git init -q",
        "git add -A",
        "git -c user.name=task -c user.email=t@t commit -qm task",
    ):
        sh(cmd.split(), cwd=dest)
    base = sh(["git", "rev-parse", "HEAD"], cwd=dest).stdout
    (dest.parent / f"{dest.name}.base").write_text(base)
    if task.get("setup"):
        with lock():
            env = {
                **clean_env(),
                **tool_env(seed_of(task)),
                "PATH": f"{TOOLS / 'bin'}:{os.environ['PATH']}",
            }
            out = sh(["bash", "-c", task["setup"]], cwd=dest, timeout=TEST_TIMEOUT, env=env)
        if out.returncode:
            raise RuntimeError(f"setup failed: {out.stderr[-500:]}")


class lock:
    """The fleet's heavy-job lock, held around test runs and environment setup."""

    def __enter__(self):
        if os.environ.get("QUALITY_NO_LOCK"):
            self.fh = open(os.devnull)
            return

        self.fh = open("/tmp/fleet-heavy.lock", "a")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                "waiting for /tmp/fleet-heavy.lock, held by another job (run.py takes it"
                " itself: under a `flock` on that file it would wait forever)",
                file=sys.stderr,
                flush=True,
            )
            fcntl.flock(self.fh, fcntl.LOCK_EX)

    def __exit__(self, *exc):
        self.fh.close()


class HarnessError(RuntimeError):
    """Claude Code itself failed (not the model): retried by the run loop."""


class UsageLimit(HarnessError):
    """The plan's usage or rate limit, or any API error: the whole set stops, to resume
    later, so an outage never uses up runs' attempts. KIND names which, for the discard log."""

    def __init__(self, message: str, kind: str = "usage_limit") -> None:
        super().__init__(message)
        self.kind = kind


# Text of a plan limit, read only from stderr or an API-error result, never from a model's
# answer (a task about rate limits would match).
LIMIT = re.compile(
    r"usage limit|session limit|rate limit|overloaded|credit balance|you've hit your"
    r"|out of usage credits|spend limit",
    re.I,
)
# A session that ends with one of these is the model's outcome, scored as it stands.
MODEL_OUTCOMES = {"success", "error_max_turns", "error_max_structured_output_retries"}


def classify(result: dict, err: str) -> None:
    """Raise when a session failed for a reason that is not the model's. An API error or a
    limit notice stops the set; a session with no result, or one Claude Code ended with an
    error of its own, is a harness failure. A timeout, or a result that is a success or is
    out of turns or structured-output retries, is the model's outcome and returns."""
    status = result.get("api_error_status")
    notice = str(result.get("result", ""))
    if result.get("terminal_reason") == "api_error" or status is not None:
        raise UsageLimit(f"API error {status}: {notice} {err}"[-800:], "api_error")
    if "subtype" not in result:
        if err == "timeout":
            return
        raise (UsageLimit if LIMIT.search(err) else HarnessError)(f"{err} no result"[-800:])
    if result.get("is_error") and result.get("subtype") == "success":
        if LIMIT.search(notice):
            raise UsageLimit(notice[-800:])  # Claude Code's own limit notice
        raise HarnessError(f"an error result with no API error: {notice}"[-800:])
    if result["subtype"] not in MODEL_OUTCOMES:
        raise HarnessError(f"{result['subtype']}: {notice} {err}"[-800:])


def read_denials(ws: pathlib.Path) -> list[str]:
    """Where the file tools (Read, and best effort Glob and Grep) may not read, since the
    sandbox's denyRead binds only Bash: /root, /tmp, /mnt, the hidden harness folders, and
    everything under /home except the path down to this run's saved tool outputs, which a
    session reads back."""
    # A rule binds a path and the file it resolves to, so the store stays open by both its
    # own path and its target when a config folder links to another (.claude-rit/projects).
    stores = {session_store(ws), session_store(ws).resolve()}
    out = ["/root", "/tmp", "/mnt", *(str(WORK / d) for d in HIDDEN)]
    todo = [HOMES]
    while todo:
        folder = todo.pop()
        try:
            children = sorted(folder.iterdir())
        except OSError:
            out.append(str(folder))
            continue
        for child in children:
            if child in stores or child.resolve() in stores:
                continue
            if any(s.is_relative_to(child) or s.is_relative_to(child.resolve()) for s in stores):
                todo.append(child)
            else:
                out.append(str(child))
    return out


def settings_file() -> pathlib.Path:
    """quality/sandbox.json with TMPDIR set to the live run's own temp folder, since the
    sandbox denies /tmp (other sessions' scratch can hold a task's fixed code), and the
    run's own uv cache inside it, the one folder besides the workspace a session may write."""
    run = LIVE / "run"
    for d in ("tmp", "home"):
        (run / d).mkdir(parents=True, exist_ok=True)
    data = json.loads(SANDBOX.read_text(encoding="utf-8"))
    data["sandbox"]["filesystem"]["denyRead"] += [str(WORK / d) for d in HIDDEN]
    data["permissions"]["deny"] = [
        rule for p in read_denials(run / "ws") for rule in (f"Read(/{p})", f"Read(/{p}/**)")
    ]
    # Claude Code sets a session's own TMPDIR below this folder; the uv cache needs it too.
    data["sandbox"]["filesystem"]["allowWrite"] = [str(run / "tmp")]
    data["env"] = {
        "TMPDIR": str(run / "tmp"),
        "HOME": str(run / "home"),
        "PATH": f"{TOOLS / 'bin'}:/usr/local/bin:/usr/bin:/bin",
        **tool_env(run / "tmp" / "uv-cache"),
    }
    path = LIVE / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def claude(
    prompt: str,
    model: str,
    cwd: pathlib.Path,
    log: pathlib.Path,
    tools: str,
    schema: dict | None = None,
    add_dirs: tuple[pathlib.Path, ...] = (),
) -> dict:
    """One `claude -p` session; returns its result event, with the transcript saved to LOG."""
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--restricted",
        "--safe-mode",
        "--tools",
        tools,
        "--settings",
        str(settings_file()),
        "--strict-mcp-config",
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        str(TURNS),
        "--no-session-persistence",
    ]
    if cwd == LIVE / "run" / "ws":  # a run's session may read back its own saved outputs
        store = session_store(cwd)
        store.mkdir(parents=True, exist_ok=True)
        add_dirs = (*add_dirs, *dict.fromkeys((store, store.resolve())))
    for d in add_dirs:
        cmd += ["--add-dir", str(d)]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=clean_env(),
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.PIPE,
                text=True,
                timeout=TIMEOUT,
                check=False,
            )
        err = proc.stderr[-500:] if proc.returncode else ""
    except subprocess.TimeoutExpired:
        err = "timeout"  # the model ran out of time: the model's failure, scored as it stands
    result: dict = {}
    last: dict = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            last = rec
            if rec.get("type") == "result":
                result = rec
    if err == "timeout" and (last.get("type"), last.get("subtype")) == ("system", "api_retry"):
        raise UsageLimit("timed out while Claude Code was retrying the API", "api_retry_timeout")
    classify(result, err)
    result.setdefault("is_error", True)
    if err:
        result["harness_error"] = err
    return result


def usage_of(result: dict) -> dict:
    u = result.get("usage") or {}
    return {
        # A session with no result event (a timeout) reports no cost; the run's is unknown.
        "cost_known": int(result.get("total_cost_usd") is not None),
        "cost_usd": result.get("total_cost_usd") or 0.0,
        "input": u.get("input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "cache_write": u.get("cache_creation_input_tokens", 0),
    }


def add_usage(total: dict, part: dict) -> None:
    for k, v in part.items():
        if k == "cost_known":
            total[k] = min(total.get(k, 1), v)
        else:
            total[k] = total.get(k, 0) + v


def _outside(command: str, ws: pathlib.Path, store: pathlib.Path | None) -> list[str]:
    return [p for p in HOME_PATH.findall(command) if not inside(p, ws, store)]


def registered(
    command: str,
    ws: pathlib.Path,
    store: pathlib.Path | None = None,
    outside: list[str] | None = None,
) -> bool:
    """The registered rule for a Bash call: a network program or git remote command named,
    a registered path outside the run, or a climb of two `../` (PREREGISTRATION.md).
    OUTSIDE, when given, is `_outside(command, ws, store)` already computed."""
    if outside is None:
        outside = _outside(command, ws, store)
    return bool(LEAK.search(command) or outside or ESCAPE.search(command))


def leaks(log: pathlib.Path, ws: pathlib.Path, store: pathlib.Path | None = None) -> list[str]:
    """Commands and reads in a transcript that reach past the workspace: every call the
    registered rule flags, each labelled by the shell reader (quality/DEVIATIONS.md,
    2026-10-31). No label: the reader shows it ran. TEXT_LABEL: a match the reader could
    not show inert. CLEARED_LABEL: every match the reader shows inert. EXTRA_LABEL: a call
    the registered rule does not flag but the reader shows reaching out; the primary metric
    leaves these out. STORE is where Claude Code saved the run's large tool outputs.

    The shell's working folder is followed from call to call, as Claude Code keeps it. A
    subagent's calls (a stream of their own) may or may not share the main shell, so each
    stream keeps its folder, and a `cd` in one makes any other stream's folder unknown
    unless both agree."""
    found = []
    cwds: dict[str | None, str | None] = {None: str(ws)}
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        stream = rec.get("parent_tool_use_id")
        if stream not in cwds:  # a fresh shell starts in ws; a shared one where main is
            cwds[stream] = str(ws) if cwds[None] == str(ws) else None
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_result":
                # Claude Code moves the shell back when a command leaves its folders.
                if reset := CWD_RESET.findall(json.dumps(part.get("content"))):
                    _move(cwds, stream, reset[-1])
                continue
            if part.get("type") != "tool_use":
                continue
            inp = part.get("input") or {}
            command = inp.get("command", "") if part.get("name") == "Bash" else ""
            if command:
                try:
                    reached, cwd = shell_reach(command, cwds[stream], ws, store)
                except Exception:  # the reader only labels: it never stops the registered rule
                    reached, cwd = "text", None
                _move(cwds, stream, cwd)
                # A registered path or climb the reader did not find used stays a text match.
                outside = _outside(command, ws, store)
                label = (
                    ""
                    if reached == "ran"
                    else TEXT_LABEL
                    if reached == "text" or outside or ESCAPE.search(command)
                    else CLEARED_LABEL
                )
                if not registered(command, ws, store, outside):
                    label = None if label == CLEARED_LABEL else EXTRA_LABEL + label
                if label is not None:
                    found.append(f"{label}Bash: {command[:200]}")
            for path in tool_paths(part.get("name", ""), inp, ws):
                if not inside(path, ws, store):
                    found.append(f"{part.get('name')}: {path}")
    return found


def _move(cwds: dict[str | None, str | None], stream: str | None, cwd: str | None) -> None:
    """STREAM's shell is now in CWD; a stream that may share it and disagrees is unknown."""
    if cwds[stream] == cwd:
        return
    cwds[stream] = cwd
    for other in cwds:
        if other != stream and cwds[other] != cwd:
            cwds[other] = None


def bash_parser():
    global BASH
    if BASH is None:
        import tree_sitter
        import tree_sitter_bash

        BASH = tree_sitter.Parser(tree_sitter.Language(tree_sitter_bash.language()))
    return BASH


def _text_reading(command: str) -> str:
    """The registered rule read as text, for a command the parser cannot follow."""
    return "text" if LEAK.search(command) or ESCAPE.search(command) else ""


def shell_reach(
    command: str,
    cwd: str | None,
    ws: pathlib.Path,
    store: pathlib.Path | None = None,
    env: dict[str, str | None] | None = None,
    functions: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    """Whether a shell command reaches past the sandbox, and the working folder it leaves
    the shell in (None when it cannot be known, which makes any later climb count).

    "ran": the parser shows it runs a network program or a git remote command, or a path
    it uses lands in a registered folder (/home, /root, /tmp, /mnt, /var/tmp) outside the
    run's own. "text": a text match the parser neither shows runs nor clears as data,
    including beside a program it cannot read, and the whole text match for a command it
    cannot parse. "": neither. Three shapes alone clear a program name as data, the three
    the recorded baseline needs: a search's words (grep, rg without an option that runs a
    program), a local git command's words but its `-c` values (not `git grep -O`), and a
    pytest `-k`/`-m` expression; none clears in a call that defines an alias. A registered
    climb is never cleared: the folder it is read from can only make it "ran". leaks() also
    labels "text" any registered path in the command's text this does not show used. Both
    count as leaks; the report also gives the primary metric without "text", an upper
    bound on the relief, since some "text" is a run this reader cannot follow
    (quality/DEVIATIONS.md, 2026-10-31)."""
    verdict, after, _unread = _reach(command, cwd, ws, store, env, functions)
    return verdict, after


def _reach(
    command: str,
    cwd: str | None,
    ws: pathlib.Path,
    store: pathlib.Path | None = None,
    env: dict[str, str | None] | None = None,
    functions: dict[str, Any] | None = None,
) -> tuple[str, str | None, bool]:
    """shell_reach's verdict and folder, and whether the reader met a program or word it
    could not read (a script it followed is then not shown inert)."""
    tree = bash_parser().parse(command.encode())
    if tree.root_node.has_error:  # unreadable: the registered text reading
        return _text_reading(command), None, True
    saved = HAS_SUBSTITUTION.copy(), MAY_RUN_OUTPUT.copy()  # a nested read indexes its own
    try:
        _index(tree.root_node)
        walker = _ShellWalk(ws, cwd, store, env)
        walker.functions = dict(functions or {})  # eval's script calls this shell's functions
        after = walker.visit(tree.root_node, cwd)
    except RecursionError:
        return _text_reading(command), None, True
    finally:
        for index, ids in zip((HAS_SUBSTITUTION, MAY_RUN_OUTPUT), saved, strict=True):
            index.clear()
            index.update(ids)
    hits = [m.start() for m in LEAK_BYTES.finditer(command.encode())]
    spans = [] if walker.no_clear else walker.data
    uncleared = any(not any(a <= h < b for a, b in spans) for h in hits)
    if walker.reached:
        return "ran", after, walker.unknown
    text = (walker.unknown and hits) or uncleared or walker.text
    return ("text" if text else ""), after, walker.unknown


def _double_climb(token: str) -> bool:
    """Two `..` steps in a row, the registered climb (`../..`, `..//..`, `./../../x`)."""
    steps = [s for s in token.split("/") if s not in ("", ".")]
    return any(a == b == ".." for a, b in itertools.pairwise(steps))


def expand_tilde(path: str, home: str, cwd: str | None = None) -> str | None:
    """PATH with a leading tilde expanded as bash does: `~` is HOME, `~+` the folder CWD,
    `~user` that user's home; None when it cannot be known (`~-`, or `~+` with no CWD)."""
    if not path.startswith("~"):
        return path
    head, sep, tail = path[1:].partition("/")
    base: str | None
    if head == "":
        base = home
    elif head == "+":
        base = cwd
    elif head == "-":
        base = None
    elif head == "root":
        base = "/root"
    else:
        base = str(HOMES / head)
    if base is None:
        return None
    return base + sep + tail


def _literal(node) -> str | None:
    """A word's value after quote removal, or None when it holds an expansion."""
    kind = node.type
    text = node.text.decode(errors="replace")
    if kind in ("word", "number"):
        return re.sub(r"\\(.)", r"\1", text)
    if kind == "raw_string":
        return text[1:-1]
    if kind == "ansi_c_string":  # $'...': backslash escapes, as bash reads them
        try:
            return text[2:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        except UnicodeDecodeError:
            return None
    if kind == "string":
        parts = []
        for c in node.children:
            if c.type == '"':
                continue
            if c.type != "string_content":
                return None
            parts.append(c.text.decode(errors="replace"))
        return "".join(parts)
    if kind == "concatenation":
        joined = ""
        for c in node.children:
            part = _literal(c)
            if part is None:
                return None
            joined += part
        return joined
    return None


WORDS = frozenset(
    {"word", "string", "raw_string", "ansi_c_string", "concatenation", "number"}
    | {"simple_expansion", "expansion"}
)
SUBSTITUTIONS = frozenset({"command_substitution", "process_substitution"})
# In the tree being read: the ids of the nodes holding a command substitution, and of
# those inside a substitution, a pipeline or a heredoc's statement (where output may run).
HAS_SUBSTITUTION: set[int] = set()
MAY_RUN_OUTPUT: set[int] = set()


def _index(root) -> None:
    """Fill both sets for ROOT's tree in one pass each."""
    HAS_SUBSTITUTION.clear()
    MAY_RUN_OUTPUT.clear()
    order = []
    stack = [root]
    while stack:  # parents before children
        n = stack.pop()
        order.append(n)
        under = n.id in MAY_RUN_OUTPUT or n.type in SUBSTITUTIONS or n.type == "pipeline"
        under = under or (
            n.type == "redirected_statement"
            and any(c.type == "heredoc_redirect" for c in n.children)
        )
        for c in n.children:
            if under:
                MAY_RUN_OUTPUT.add(c.id)
            stack.append(c)
    for n in reversed(order):  # children before parents
        if any(c.type in SUBSTITUTIONS or c.id in HAS_SUBSTITUTION for c in n.children):
            HAS_SUBSTITUTION.add(n.id)


def _has_substitution(node) -> bool:
    return node.id in HAS_SUBSTITUTION


def _command_words(node) -> list:
    words = []
    for c in node.children:
        if c.type == "command_name":
            words.append(c.children[0] if c.children else c)
        elif c.type in WORDS:
            words.append(c)
    return words


# Commands after which a word may run something no reader of this call sees.
RESHAPERS = frozenset({"alias", "hash", "enable", "shopt", "exec", "source", "."})
LOOKUP_VARS = frozenset(
    {"PATH", "BASH_ALIASES", "BASH_CMDS", "RIPGREP_CONFIG_PATH", "BASH_ENV", "PS0", "PS4"}
    | {"PROMPT_COMMAND", "IFS"}
)


def _sets_lookup(prefix: list[str | None]) -> bool:
    """Whether words before a program (prefix or `env` assignments) set a variable that
    changes what a program runs or how it reads its options."""
    for v in prefix:
        name = (v or "").split("=", 1)[0] if v and "=" in v else None
        if name and (name in LOOKUP_VARS or EXECUTED_VAR.fullmatch(name)):
            return True
    return False


def _plain_program(
    words: list, values: list[str | None], prog: str | None, args: list[str | None]
) -> int | None:
    """The index of the program's word when every word is literal and the program is named
    by a bare word (no path, no variable), else None: only such a command is cleared."""
    if not prog or len(values) != len(words) or None in values:
        return None
    at = len(values) - len(args) - 1
    if at < 0 or values[at] != prog or _literal(words[at]) != prog:
        return None
    return at


def _search_runs(prog: str | None, args: list[str | None]) -> bool:
    """Whether a search's options make it run a program: rg's preprocessor, decompressors
    and hostname program."""
    if prog != "rg":
        return False
    if "--no-config" not in args:  # a config file (RIPGREP_CONFIG_PATH) may add any option
        return True
    for a in args:
        if a is None or a == "--":
            return a is None
        if a.startswith(("--pre", "--hostname-bin", "--search-zip")):
            return True
        if a.startswith("-") and not a.startswith("--") and "z" in a[1:]:
            return True
    return False


def _git_runs(args: list[str | None]) -> bool:
    """Whether a local git command's options run a program: `git grep -O` opens its
    matches in a command it names."""
    if _git_subcommand(args) != "grep":
        return False
    for a in args:
        if a is None:
            return True
        long = a.split("=", 1)[0]
        if len(long) >= 4 and "--open-files-in-pager".startswith(long):  # abbreviated
            return True
        if a.startswith("-") and not a.startswith("--") and "O" in a[1:]:  # in a cluster
            return True
    return False


def _tee_files(prog: str | None, args: list[str | None]) -> bool:
    """Whether PROG is tee writing to a file, which it does wherever its stdout goes."""
    if prog != "tee":
        return False
    ended = False  # after `--` every word is a file
    for a in args:
        if a is None or (a != "/dev/null" and (ended or not a.startswith("-"))):
            return True
        ended = ended or a == "--"
    return False


def _breaks(node) -> bool:
    """Whether NODE holds a `break` or `continue` command."""
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "command":
            words = _command_words(n)
            if words and _literal(words[0]) in ("break", "continue"):
                return True
        stack.extend(n.children)
    return False


LOOPS = frozenset({"while_statement", "until_statement", "for_statement", "c_style_for_statement"})


def _stops(node) -> bool:
    """Whether NODE is an `exit` or `return`, after which nothing in its chain runs on."""
    while node.type == "redirected_statement" and node.children:
        node = node.children[0]
    if node.type != "command":
        return False
    words = _command_words(node)
    return bool(words) and _literal(words[0]) in ("exit", "return")


def _opened(words: list, values: list[str | None], prog: str | None, args: list) -> set[int]:
    """Which of a command's WORDS its program opens as a file or folder: a search's files,
    `cat`'s and `tee`'s, find's start paths, and git's `-C`, `--git-dir` and
    `--work-tree`. When a variable split into several words, every word may be one."""
    if len(values) != len(words):
        return set(range(len(words)))
    at = len(words) - len(args)
    out: set[int] = set()
    if prog in SEARCHES:
        takes = SEARCH_VALUE["rg" if prog == "rg" else "grep"]
        pattern, options, i = False, True, 0
        while i < len(args):
            a = args[i]
            if options and a == "--":
                options = False
            elif options and a in ("-e", "--regexp", "-f", "--file"):
                pattern = True
                if a in ("-f", "--file"):
                    out.add(i + 1)
                i += 1
            elif options and a is not None and a.startswith(("-e", "--regexp=")):
                pattern = True
            elif options and a is not None and a.startswith(("-f", "--file=")):
                pattern = True
                out.add(i)
            elif options and a is not None and a.startswith("-") and a != "-":
                i += a in takes
            elif not pattern:
                pattern = True
            else:
                out.add(i)
            i += 1
    elif prog in ("cat", "tee"):
        out = {i for i, a in enumerate(args) if a is None or not a.startswith("-") or a == "-"}
    elif prog in ("test", "["):
        out = _test_paths(args)
    elif prog == "find":
        for i, a in enumerate(args):
            if a is not None and (a.startswith(("-", "(", "!")) or a == ")"):
                break
            out.add(i)
    elif prog == "git":
        for i, a in enumerate(args):
            if a is None or not a.startswith("-"):
                break
            if a in ("-C", "--git-dir", "--work-tree"):
                out.add(i + 1)
            elif a.startswith(("--git-dir=", "--work-tree=")):
                out.add(i)
    return {at + i for i in out}


# The tests that look at a file: the operand of one of these is a path the shell uses.
FILE_UNARY = frozenset("-a -b -c -d -e -f -g -h -k -p -r -s -u -w -x -G -L -N -O -S".split())
FILE_BINARY = frozenset({"-nt", "-ot", "-ef"})


def _compared(node) -> bool:
    """Whether word NODE is only compared or listed (a loop's items, a test's string or
    pattern operand), so a path in it is text; a file test (`-f`, `-nt`) uses its path."""
    parent = node.parent
    if parent is None:
        return False
    if parent.type in ("for_statement", "test_command"):
        return True
    op = parent.child_by_field_name("operator")
    text = op.text.decode(errors="replace") if op is not None else None
    if parent.type == "unary_expression":
        return text not in FILE_UNARY
    return parent.type == "binary_expression" and text not in FILE_BINARY


def _test_paths(args: list[str | None]) -> set[int]:
    """Which of `test`'s or `[`'s ARGS a file test reads, as `_compared` judges `[[ ]]`."""
    out: set[int] = set()
    for i, a in enumerate(args):
        if a in FILE_UNARY:
            out.add(i + 1)
        elif a in FILE_BINARY:
            out |= {i - 1, i + 1}
    return out


def _list_items(node) -> list:
    """A `&&`/`||`/`;` list's statements, operators and redirections, flattened in order:
    tree-sitter nests a long chain one level per operator, and hangs a redirection after a
    statement on the list before it."""
    items: list = []
    while node.children and (
        node.type == "list"
        or (node.type == "redirected_statement" and node.children[0].type == "list")
    ):
        items = list(node.children[1:]) + items
        node = node.children[0]
    return [node, *items]


def _program(
    values: list[str | None], seen: dict[str, str | None] | None = None
) -> tuple[str | None, list[str | None], bool]:
    """The program a command runs, past wrappers like env and timeout, and its args. The
    flag is False when a word in the way cannot be read; an empty name runs nothing. SEEN,
    when given, gets the folder a wrapper runs the program in (`env -C`, `sudo -D`) as
    "chdir" (None: unreadable)."""
    i = 0
    while i < len(values):
        v = values[i]
        if v is None:
            return None, values[i + 1 :], False
        name = os.path.basename(v)
        if name not in WRAPPERS:
            return name, values[i + 1 :], True
        if name == "command":
            asks = False
            for a in values[i + 1 :]:  # command's own options, before the program
                if a is None or not a.startswith("-") or a == "--":
                    break
                asks = asks or "v" in a or "V" in a
            if asks:
                return "", [], True  # asks whether a program exists; runs nothing
        if name == "uv":  # `uv run P` and `uv tool run P` run P; any other subcommand is uv's
            while i + 1 < len(values) and (values[i + 1] or "").startswith("-"):
                i += 2 if values[i + 1] in WRAPPERS["uv"][1] else 1
            sub = values[i + 1 : i + 3]
            if sub[:2] == ["tool", "run"]:
                i += 1  # past `tool`: `run` and its options are skipped below
            elif sub[:1] != ["run"]:
                return name, values[i + 1 :], True
        skip, takes_value = WRAPPERS[name]
        i += 1
        while i < len(values):
            a = values[i]
            if a is None:
                return None, values[i + 1 :], False
            if name in UNREAD and a.split("=", 1)[0] in UNREAD[name]:
                # It hands a shell the string (sudo: the words after it): read it as sh -c.
                _key, eq, val = a.partition("=")
                rest = values[i + 1 :]
                if name == "sudo":
                    script = None if None in rest else " ".join(r or "" for r in rest)
                else:
                    script = val if eq else rest[0] if rest else None
                return "sh", ["-c", script], True
            if a == "--":
                i += 1
                break
            if a.startswith("-") and a != "-":
                key, eq, val = a.partition("=")
                if seen is not None and key in CHDIR.get(name, ()):
                    seen["chdir"] = val if eq else values[i + 1] if i + 1 < len(values) else None
                i += 2 if a in takes_value else 1
            elif name == "env" and "=" in a:
                i += 1
            elif skip:
                skip -= 1
                i += 1
            else:
                break
    return "", [], True


def _shell_script(
    args: list[str | None],
) -> tuple[str, str | None, list[str | None]]:
    """What a shell's arguments make it run: ("c", script, $0 and the words after it),
    ("file", path, []), ("stdin", None, []), or ("unknown", None, []) when a word cannot
    be read."""
    command_flag = False
    i = 0
    while i < len(args):
        a = args[i]
        if a is None:
            return "unknown", None, []
        if a in SHELL_OPTION_ARG:
            i += 2
            continue
        if a == "--":
            i += 1
            break
        if a.startswith("--"):
            i += 1
            continue
        if a[:1] in ("-", "+") and len(a) > 1:
            command_flag = command_flag or "c" in a[1:]
            i += 1
            continue
        break
    rest = args[i:]
    if command_flag:
        return ("c", rest[0], rest[1:]) if rest else ("unknown", None, [])
    if rest and rest[0] != "-":
        return "file", rest[0], []
    return "stdin", None, []


def _positional(words: list[str | None]) -> dict[str, str | None]:
    """The parameters `sh -c SCRIPT WORDS...` gives SCRIPT: $0 is the first word, $1 on
    the rest, and $@ and $* all of them. Unread words leave $@ and $* unread."""
    out: dict[str, str | None] = {str(i): w for i, w in enumerate(words)}
    rest = words[1:]
    joined = None if None in rest else " ".join(w or "" for w in rest)
    out["@"] = out["*"] = joined
    out["#"] = str(len(rest))
    return out


def _git_subcommand(args: list[str | None]) -> str | None:
    i = 0
    while i < len(args):
        a = args[i]
        if a is None:
            return None
        if a in GIT_OPTION_ARG:
            i += 2
        elif a in GIT_FLAGS or (
            a.startswith("--") and a.split("=", 1)[0] in GIT_OPTION_ARG | {"--exec-path"}
        ):
            i += 1
        elif a.startswith("-c") or a.startswith("-C"):  # a value joined to its option
            i += 1
        elif a.startswith("-"):
            return None
        else:
            return a
    return ""


class _ShellWalk:
    """Walks one command's syntax tree in execution order, tracking the folder, the folder
    stack and simple variables of the shell (a subshell, a pipeline stage and a command
    substitution each work on a copy), and collecting the byte spans whose text is only
    data."""

    def __init__(
        self,
        ws: pathlib.Path,
        cwd: str | None,
        store: pathlib.Path | None,
        env: dict[str, str | None] | None,
    ) -> None:
        self.ws = ws
        self.store = store
        self.home = str(ws.parent / "home")
        self.vars: dict[str, str | None] = {
            "TMPDIR": str(ws.parent / "tmp" / f"claude-{os.getuid()}"),
            "HOME": self.home,
            **(env or {}),
            "PWD": cwd,
        }
        self.dirs: list[str | None] = []  # pushd's stack
        self.oldpwd: str | None = None  # where `cd -` goes
        self.functions: dict[str, Any] = {}  # name: body, replayed at each call
        self.calling: set[tuple[int, int]] = set()  # bodies being replayed
        self.reached = False
        self.unknown = False  # a program could not be read: every text match counts
        self.text = False  # a script it followed held an uncleared text match
        self.no_clear = False  # the call may change what a word runs: clear nothing
        self.scripts: set[str] = set()  # scripts this command hands a shell, read nested
        self.python_code = False  # the command runs Python code given as a word (`-c`)
        self.nested_cwd: str | None = None  # where an eval'd script left the folder
        self.data: list[tuple[int, int]] = []
        self.heredocs: dict[tuple[int, int], list[tuple[str, str | None, Any]]] = {}

    def visit(self, node, cwd: str | None) -> str | None:
        """Visit NODE in a shell whose folder is CWD; returns the folder after it."""
        kind = node.type
        if kind == "command":
            return self._command(node, cwd)
        if kind == "variable_assignment":
            self._assign(node, cwd, keep=True)
            return cwd
        if kind == "declaration_command":  # export, declare, local, readonly
            for c in node.children:
                if c.type == "variable_assignment":
                    self._assign(c, cwd, keep=True)
                elif c.type in WORDS:
                    self._word_node(c, cwd, soft=True)
            return cwd
        if kind == "heredoc_body":  # its text is read with the command it feeds
            self._substitutions(node, cwd)
            return cwd
        if kind == "pipeline":  # each stage runs in a subshell of its own
            first = node.children[0] if node.children else None
            if (
                first is not None
                and first.type == "redirected_statement"
                and first.children
                and first.children[0].type == "list"
            ):  # tree-sitter reads `a && b 2>&1 | c` as `(a && b 2>&1) | c`; bash pipes b
                return self._and_or(self._flatten(first), cwd, node.children[1:])
            for c in node.children:
                self._copy([c], cwd)
            return cwd
        if kind == "subshell" or kind in SUBSTITUTIONS:
            self._copy(node.children, cwd)
            return cwd
        if kind == "function_definition":  # its body is judged at each call
            body = node.child_by_field_name("body")
            name = node.child_by_field_name("name")
            if body is not None and name is not None:
                self.functions[name.text.decode(errors="replace")] = body
            return cwd
        if kind in WORDS:
            self._word_node(node, cwd, soft=_compared(node))
            return cwd
        if kind == "if_statement":
            return self._if(node, cwd)
        if kind == "case_statement":
            return self._case(node, cwd)
        if kind in LOOPS and node.child_by_field_name("body") is not None:
            return self._loop(node, cwd)
        if kind in ("list", "redirected_statement"):
            flat = self._flatten(node)
            if flat[0] != node:
                return self._and_or(flat, cwd)
            if kind == "redirected_statement":  # around one statement
                self._pin_heredocs(node)
        return self._seq(node.children, cwd)

    def _flatten(self, node) -> list:
        """NODE's `&&`/`||` items in order, pinning each flattened statement's heredocs."""
        flat = _list_items(node)
        spine = node
        while spine != flat[0]:  # each redirected statement it flattened
            if spine.type == "redirected_statement":
                self._pin_heredocs(spine)
            spine = spine.children[0]
        return flat

    def _seq(self, nodes: list, cwd: str | None) -> str | None:
        """Visit NODES in order; one sent to the background with `&` runs in a subshell."""
        for i, c in enumerate(nodes):
            if i + 1 < len(nodes) and nodes[i + 1].type == "&":
                self._copy([c], cwd)
            else:
                cwd = self.visit(c, cwd)
        return cwd

    def _and_or(self, items: list, cwd: str | None, stages: Sequence = ()) -> str | None:
        """A `&&`/`||` chain. Each command is taken to succeed, as its author meant, so one
        after `&&` runs where the chain is; one after `||` runs only when the chain so far
        failed, which may have happened before or after any move in it, so from an unknown
        folder unless it never moved. The chain ends where both ways agree, or unknown.
        With STAGES, what follows the last operator is piped into them: all run in
        subshells."""
        piped: list = []
        if stages:
            cut = max((i for i, c in enumerate(items) if c.type in ("&&", "||")), default=-1)
            items, piped = items[: cut + 1], items[cut + 1 :]
        ok, failed = cwd, {cwd}  # where the chain is if all ran; where a failure leaves it
        op = None
        for c in items:
            if c.type in ("&&", "||"):
                op = c.type
                continue
            if op != "||":  # the first command, one after `&&`, or a redirection hung on one
                ok = self.visit(c, ok)
                failed.add(ok)
            else:
                start = next(iter(failed)) if len(failed) == 1 else None
                after = self.visit(c, start)
                if not _stops(c) and after != ok:
                    ok = None
                failed = {start, after}
            op = None
        if piped:
            start = ok if op != "||" else next(iter(failed)) if len(failed) == 1 else None
            for c in [*piped, *stages]:
                self._copy([c], start)
            if start != ok:
                ok = None
        return ok

    def _if(self, node, cwd: str | None) -> str | None:
        """An `if`: each condition runs where the ones before left the shell, each branch
        where its condition did; after it the folder is known only if every way agrees."""
        ends, has_else = [], False
        clauses = [node, *(c for c in node.children if c.type in ("elif_clause", "else_clause"))]
        for clause in clauses:
            parts = [c for c in clause.children if c.type not in ("elif_clause", "else_clause")]
            kinds = [c.type for c in parts]
            if "then" in kinds:
                k = kinds.index("then")
                cwd = self._seq(parts[1:k], cwd)
                ends.append(self._seq(parts[k + 1 :], cwd))
            else:
                has_else = True
                ends.append(self._seq(parts[1:], cwd))
        if not has_else:
            ends.append(cwd)
        return ends[0] if all(e == ends[0] for e in ends) else None

    def _case(self, node, cwd: str | None) -> str | None:
        """A `case`: each item's commands run where the shell was; its patterns are not
        paths. As with `if`, the folder after is known only if every way agrees."""
        ends = [cwd]  # no item matched
        for c in node.children:
            if c.type == "case_item":
                k = next((i for i, x in enumerate(c.children) if x.type == ")"), None)
                ends.append(cwd if k is None else self._seq(c.children[k + 1 :], cwd))
            elif c.type in WORDS:
                self._word_node(c, cwd, soft=True)
        return ends[0] if all(e == ends[0] for e in ends) else None

    def _loop(self, node, cwd: str | None) -> str | None:
        """A loop's body runs any number of times. One that moves the shell is read again,
        with its head, from an unknown folder, where the loop leaves it. A `for` over items
        it can read (at most 16) and with no break or continue runs once per item, in order,
        its variable set to each; otherwise the variable is unknown in the body."""
        body = node.child_by_field_name("body")
        head = [
            c for c in node.children if c != body
        ]  # field access gives a new object: compare by value
        cwd = self._seq(head, cwd)
        var = node.child_by_field_name("variable") if node.type == "for_statement" else None
        if var is not None:
            name = var.text.decode(errors="replace")
            items = [c for c in node.children_by_field_name("value")]
            values = self._values(items) if items else None
            if values is not None and None not in values and len(values) <= 16:
                if not _breaks(body):
                    for v in values:
                        self.vars[name] = v
                        before, cwd = cwd, self.visit(body, cwd)
                        if cwd != before and GLOB.search(v or ""):
                            cwd = None  # a glob names what exists: where it went is unknown
                    return cwd
            self.vars[name] = None
        if self.visit(body, cwd) == cwd:
            return cwd
        self._seq(head, None)
        self.visit(body, None)
        return None

    def _copy(self, nodes: list, cwd: str | None) -> None:
        """Visit NODES in order in a copy of the shell: its folder, stack, variables and
        functions are put back after."""
        saved = dict(self.vars), list(self.dirs), self.oldpwd, dict(self.functions)
        for c in nodes:
            cwd = self.visit(c, cwd)
        self.vars, self.dirs, self.oldpwd, self.functions = saved

    def _substitutions(self, node, cwd: str | None) -> None:
        """Visit the command substitutions inside NODE, outermost first."""
        stack = list(reversed(node.children))
        while stack:
            c = stack.pop()
            if c.type in SUBSTITUTIONS:
                self.visit(c, cwd)
            elif _has_substitution(c):
                stack.extend(reversed(c.children))

    def _word_node(self, node, cwd: str | None, soft: bool = False) -> None:
        self._substitutions(node, cwd)
        self._paths(self._word(node), node.text.decode(errors="replace"), cwd, soft)

    def _paths(self, value: str | None, raw: str, cwd: str | None, soft: bool = False) -> None:
        """Flag a path in VALUE that lands in a registered folder outside the run's own.
        RAW stands in when the value cannot be known; then, as with an unknown CWD, a climb
        of two or more `../` counts, as registered. SOFT: VALUE is data (printed, assigned,
        written, a search's words), so a landing there is a text match."""
        if value is None:
            if any(_double_climb(t) for t in PATH_SPLIT.split(raw)):
                self._hit(soft)
            return
        for token in _path_tokens(value):
            t = expand_tilde(token, self.home, cwd) if token else None
            if not t:
                continue
            if not os.path.isabs(t):
                if (
                    cwd is not None
                    and ESCAPE.search(f" {token}")
                    and not restricted(os.path.join(cwd, t), self.ws, self.store)
                ):  # the registered climb, landing inside: a folder read cannot clear it
                    self._hit(True)
                    return
                if cwd is None:
                    if _double_climb(t):
                        self._hit(soft)
                        return
                    continue
                t = os.path.join(cwd, t)
            if (_glob_lands if GLOB.search(t) else restricted)(t, self.ws, self.store):
                self._hit(soft)
                return

    def _hit(self, soft: bool) -> None:
        if soft:
            self.text = True
        else:
            self.reached = True

    def _pin_heredocs(self, node) -> None:
        """A heredoc feeds the last command that ends before its `<<`."""
        if not any(r.type in ("heredoc_redirect", "herestring_redirect") for r in node.children):
            return
        body = node.child_by_field_name("body") or node.children[0]
        commands = [n for n in (body, *_descendants(body)) if n.type == "command"]
        for r in node.children:
            if r.type not in ("heredoc_redirect", "herestring_redirect"):
                continue
            before = [c for c in commands if c.end_byte <= r.start_byte]
            if not before:
                continue
            key = (before[-1].start_byte, before[-1].end_byte)
            self.heredocs.setdefault(key, []).append(self._feed(r))

    def _feed(self, redirect) -> tuple[str, str | None, Any]:
        """A heredoc or here-string's text and the node holding it (None text: unreadable)."""
        if redirect.type == "herestring_redirect":
            word = next((c for c in redirect.children if c.type in WORDS), None)
            return "herestring", None if word is None else self._word(word), word
        body = next((c for c in redirect.children if c.type == "heredoc_body"), None)
        if body is None:
            return "heredoc", "", redirect
        quoted = any(
            c.type == "heredoc_start" and c.text[:1] in (b"'", b'"') for c in redirect.children
        )
        text = body.text.decode(errors="replace")
        return "heredoc", text if quoted or not _has_substitution(body) else None, body

    def _assign(self, node, cwd: str | None, keep: bool) -> tuple[str, str | None] | None:
        """A variable's value is not a path until something uses it. Setting one a program
        runs or reads its options from (EXECUTED_VAR, LOOKUP_VARS) turns clearing off."""
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if name is None:
            return None
        key = name.text.decode()
        base = key.split("[", 1)[0]  # BASH_ALIASES[grep]=…
        if base in LOOKUP_VARS or EXECUTED_VAR.fullmatch(base):
            self.no_clear = True  # what a program runs or reads may now differ
        val = self._word(value) if value is not None else ""  # quoting kept as bash keeps it
        if value is not None:
            self._substitutions(value, cwd)
            self._paths(self._word(value), value.text.decode(errors="replace"), cwd, soft=True)
        if keep:
            self.vars[key] = val
        return key, val

    def _expand_known(self, text: str) -> str | None:
        def sub(m: re.Match) -> str:
            v = self.vars.get(m.group(1) or m.group(2))
            if v is None:
                raise KeyError
            return v

        try:
            return re.sub(r"\$\{(\w+|[@*#?$!-])\}|\$(\w+|[@*#?$!-])", sub, text)
        except KeyError:
            return None

    def _word(self, node) -> str | None:
        """A word's value with known variables expanded, or None."""
        lit = _literal(node)
        if lit is not None:
            return lit
        raw = node.text.decode(errors="replace")
        if node.type == "string":
            raw = raw[1:-1]
        if re.search(r"\$\(|`|\$\{[^}]*[^\w}]|\$'", raw):
            return None
        return self._expand_known(raw.replace('"', ""))

    def _values(self, words: list) -> list[str | None]:
        """The words a command line becomes; an unquoted variable splits on whitespace."""
        out: list[str | None] = []
        for w in words:
            v = self._word(w)
            if v is not None and (
                w.type in ("simple_expansion", "expansion") or w.text in (b'"$@"', b'"${@}"')
            ):
                out += v.split()
            else:
                out.append(v)
        return out

    def _command(self, node, cwd: str | None) -> str | None:
        words, env = _command_words(node), dict(self.vars)
        for c in node.children:
            if c.type == "variable_assignment":  # applies to this command only
                if pair := self._assign(c, cwd, keep=False):
                    env[pair[0]] = pair[1]
            elif c.type not in WORDS and c.type != "command_name":
                self.visit(c, cwd)  # redirections: their targets are paths
        feeds = list(self.heredocs.get((node.start_byte, node.end_byte), []))
        feeds += [self._feed(c) for c in node.children if c.type == "herestring_redirect"]
        for w in words:
            self._substitutions(w, cwd)
        values = self._values(words)
        seen: dict[str, str | None] = {}
        prog, args, known = _program(values, seen)
        here = self._resolve(seen["chdir"], cwd) if "chdir" in seen else cwd
        if not known:
            self.unknown = True
        self.python_code = False
        self.scripts = set()
        launched = self._launches(prog, args, here, env, feeds, node)
        if launched is None:
            self.unknown = True
        elif launched:
            self.reached = True
        mark = len(self.data)
        self._data_settings(words, prog, args)
        first = os.path.basename(values[0] or "") if values else ""
        if (
            prog in RESHAPERS
            or first in RESHAPERS
            or _sets_lookup(values[: len(values) - len(args)])
        ):
            self.no_clear = True  # a word may now run a command no reader sees
        at = _plain_program(words, values, prog, args)
        if at is None or not self._sink_safe(node):
            pass  # a program named by a path or a variable, or output that may be run
        elif prog == "git" and _git_subcommand(args) in GIT_LOCAL and not _git_runs(args):
            self._data_words(node, words, keep=self._git_config_values(words, at))
        elif prog in SEARCHES and not _search_runs(prog, args):
            self._data_words(node, words)
        spans = self.data[mark:]
        printed = prog in ("echo", "printf")
        opened = _opened(words, values, prog, args)
        for i, w in enumerate(words):  # printed, or cleared as data and not opened: text
            cleared = any(a <= w.start_byte and w.end_byte <= b for a, b in spans)
            tested = prog in ("test", "[") and i > len(words) - len(args) - 1
            # A script read nested had its paths judged there: here they are text.
            nested = values[i] in self.scripts if i < len(values) else False
            soft = printed or self.python_code or nested
            soft = soft or ((cleared or tested) and i not in opened)
            self._paths(self._word(w), w.text.decode(errors="replace"), here, soft)
        if not (prog in SHELLS and launched is not None):  # a shell's feed was read nested
            for _kind, text, holder in feeds:
                raw = holder.text.decode(errors="replace") if holder is not None else ""
                self._paths(text, raw, cwd, soft=True)
                if prog in WRITERS and (not self._to_null(node) or _tee_files(prog, args)):
                    self._written(text, here, env)
        if printed and not self._to_null(node):
            lines = args
            if prog == "printf" and len(args) > 1:  # each argument is written through the format
                self._written(args[0], here, env)
                lines = args[1:]
            self._written("\n".join(a for a in lines if a), here, env)
        if prog == "git" and _git_subcommand(args) in ("commit", "tag", "stash"):
            for i, a in enumerate(args):  # a message is kept: a later call may replay it
                if a is None:
                    continue
                if a.startswith("--message"):
                    msg = a.split("=", 1)[1] if "=" in a else None
                elif a.startswith("-") and not a.startswith("--") and "m" in a[1:]:
                    msg = a[a.index("m", 1) + 1 :] or None  # `-qam MSG` or `-mMSG`
                else:
                    continue
                if msg is None and i + 1 < len(args):
                    msg = args[i + 1]
                self._written(msg, here, env)
        if prog == "git":
            config = _git_subcommand(args) == "config"
            for i, w in enumerate(words):
                if i in self._git_config_values(words, at) or (config and i > 0):
                    self._written(self._word(w), here, env)
        if prog in self.functions:  # it runs in this shell: replay it, once per call chain
            body = self.functions[prog]
            key = (body.start_byte, body.end_byte)  # a body may define its own name anew
            if key in self.calling:
                return None
            self.calling.add(key)
            cwd = self.visit(body, cwd)
            self.calling.discard(key)
        elif prog in ("cd", "pushd", "popd"):
            moved = self._cd(prog, args, cwd)
            if moved != cwd:
                self.oldpwd = cwd
            cwd = moved
            self.vars["PWD"] = cwd
        elif prog == "eval":
            cwd = self.nested_cwd
        elif prog in ("source", "."):
            cwd = None
        return cwd

    def _written(self, text: str | None, cwd: str | None, env: dict[str, str | None]) -> None:
        """Text that may run later (written to a file, or a value git runs): a program it
        would run, read as shell (Makefile recipe marks and an alias's `!` dropped) or as
        Python, is a text match."""
        if not text:
            return
        script = "\n".join(re.sub(r"^[\t ]*[@+-]*!?", "", line) for line in text.splitlines())
        reached, _after = shell_reach(script, cwd, self.ws, self.store, env)
        if reached:
            self.text = True
            return

        if _python_reach(
            text,
            lambda s: shell_reach(s, cwd, self.ws, self.store, env)[0] != "",
            lambda argv: self._argv_launches(argv, cwd, env),
        ):
            self.text = True

    def _argv_launches(
        self, argv: list[str | None], cwd: str | None, env: dict[str, str | None]
    ) -> bool | None:
        """Whether running ARGV, a program and its arguments as Python passes them, reaches
        out; None when it cannot be read."""
        prog, rest, ok = _program(argv)
        return self._launches(prog, rest, cwd, env, []) if ok else None

    def _git_config_values(self, words: list, at: int | None) -> set[int]:
        """Which of a git command's words are `-c`/`--config-env` values, which git may run
        (an alias, a pager, ssh): only git's own options, after git's word AT. With AT
        unknown, every word may be one."""
        if at is None:
            return set(range(len(words)))
        keep: set[int] = set()
        values = [_literal(w) for w in words]
        i = at + 1
        while i < len(values):
            v = values[i]
            if v in ("-c", "--config-env"):
                keep.add(i + 1)
                i += 2
            elif v is not None and v.startswith(("--config-env=", "-c")):
                keep.add(i)
                i += 1
            elif v in GIT_OPTION_ARG:
                i += 2
            elif v is not None and v.startswith("-"):
                i += 1
            else:
                break
        return keep

    def _data_settings(self, words: list, prog: str | None, args: list[str | None]) -> None:
        """Mark as data a pytest `-k` or `-m` expression, which pytest matches against test
        names and marks."""
        pytest = prog == "pytest" or (
            prog is not None and PYTHON.match(prog) and args[:2] == ["-m", "pytest"]
        )
        for i, w in enumerate(words):
            if _has_substitution(w):
                continue
            v = _literal(w)
            if pytest and v in ("-k", "-m") and i + 1 < len(words):
                nxt = words[i + 1]
                if not _has_substitution(nxt):
                    self.data.append((nxt.start_byte, nxt.end_byte))

    def _launches(
        self,
        prog: str | None,
        args: list[str | None],
        cwd: str | None,
        env: dict[str, str | None],
        feeds: list[tuple[str, str | None, Any]],
        node: Any = None,
    ) -> bool | None:
        """Whether running PROG with ARGS (and FEEDS on stdin) reaches out; None when what it
        runs cannot be read. A script it runs is read nested."""
        if not prog or prog in self.functions:  # a function is replayed where it is called
            return False
        if prog in NET_PROGRAMS:
            return True
        if prog == "git":
            sub = _git_subcommand(args)
            return True if sub in GIT_REMOTE else False if sub in GIT_LOCAL | {""} else None
        if prog in SHELLS:
            kind, script, positional = _shell_script(args)
            if kind == "unknown" or (kind == "c" and script is None):
                return None
            if kind == "c":
                assert script is not None
                self.scripts.add(script)
                return self._nested(script, cwd, {**env, **_positional(positional)})
            if kind == "stdin":
                if not feeds and node is not None:
                    piped = self._piped_input(node)
                    if piped is None:
                        return None
                    feeds = [piped] if piped[2] is not None else []
                reached: bool | None = False
                for _k, text, _holder in feeds:
                    if text is None:
                        return None
                    got = self._nested(text, cwd, env)
                    if got is None:
                        return None  # not shown inert: its text is not cleared
                    reached = reached or got
                return reached
            return None  # a script file: what it runs is not read here
        if prog in ("source", "."):
            return None  # a script file: what it runs is not read here
        if prog == "eval":
            self.nested_cwd = None
            if None in args:
                return None
            self.scripts.update(a for a in args if a is not None)
            return self._nested(" ".join(a or "" for a in args), cwd, env, keep_folder=True)
        if prog == "find":
            reached: bool | None = False
            for i, a in enumerate(args):
                if a in ("-exec", "-execdir", "-ok", "-okdir"):
                    end = next(
                        (j for j in range(i + 1, len(args)) if args[j] in (";", "+")), len(args)
                    )
                    sub, sub_args, ok = _program(args[i + 1 : end])
                    got = self._launches(sub, sub_args, cwd, env, []) if ok else None
                    if got is None:
                        return None
                    reached = reached or got
            return reached
        if PYTHON.match(prog):
            return self._python(args, cwd, env, feeds)
        return False

    def _piped_input(self, node) -> tuple[str, str | None, Any] | None:
        """What a pipe hands NODE on stdin: the text of a literal echo, printf or cat
        heredoc before it, with the stage that printed it; a None holder when nothing is
        piped in; None when the text cannot be read."""
        child, n = node, node.parent
        if n is not None and n.type == "redirected_statement":
            child, n = n, n.parent
        if n is None or n.type != "pipeline":
            return "pipe", "", None
        stages = [c for c in n.children if c.is_named]
        before = [s for s in stages if s.end_byte <= child.start_byte]
        if not before and n.parent is not None and n.parent.type == "heredoc_redirect":
            before = [n.parent.parent]  # `cat <<EOF | sh`: the pipe hangs off the heredoc
        if not before:
            return "pipe", "", None
        prev = cmd = before[-1]
        if cmd.type == "redirected_statement":
            cmd = cmd.child_by_field_name("body") or cmd.children[0]
        if cmd.type != "command":
            return None
        prog, args, ok = _program(self._values(_command_words(cmd)))
        if not ok or None in args:
            return None
        text: str | None = None
        if prog == "echo" and not any(a and a.startswith("-") for a in args[:1]):
            text = " ".join(a or "" for a in args) + "\n"
        elif (
            prog == "printf" and args and "%" not in (args[0] or "") and "\\" not in (args[0] or "")
        ):
            text = args[0]
        elif (
            prog == "printf"
            and args
            and args[0] in ("%s", "%s\\n")
            and "\\" not in "".join(a or "" for a in args[1:])
        ):
            text = "".join(a or "" for a in args[1:])
        elif prog == "cat" and not args:
            feeds = self.heredocs.get((cmd.start_byte, cmd.end_byte), [])
            if len(feeds) == 1:
                text = feeds[0][1]
        return None if text is None else ("pipe", text, prev)

    def _data_words(self, node, words: list, keep: Set[int] = frozenset()) -> None:
        """A command's words (but those at the indexes in KEEP) are data when nothing runs
        what it prints."""
        if self._output_runs(node):
            return
        for i, w in enumerate(words):
            if i not in keep and not _has_substitution(w):
                self.data.append((w.start_byte, w.end_byte))

    def _sink_safe(self, node) -> bool:
        """Whether NODE's output reaches only the tool result: every redirect of the command
        (its prefix ones too) and of every statement around it is an input, /dev/null or a
        copy of another descriptor; no process substitution; not inside a function body,
        whose output each call may send elsewhere."""
        child, n = None, node
        while n is not None:
            if n.type == "function_definition":
                return False
            for r in n.children:
                if r == child:
                    continue
                if r.type == "process_substitution":
                    return False
                if r.type != "file_redirect":
                    continue
                op = next((c.type for c in r.children if not c.is_named), "")
                target = r.child_by_field_name("destination")
                text = _literal(target) if target is not None else None
                if op == "<":
                    continue
                if text == "/dev/null" or (op in (">&", "<&") and (text or "").isdigit()):
                    continue
                return False
            child, n = n, n.parent
        return True

    def _output_runs(self, node) -> bool:
        """Whether NODE's output may be run: it feeds a later pipeline stage that is not a
        filter, or it is substituted into another command."""
        if node.id not in MAY_RUN_OUTPUT:
            return False
        child, n = node, node.parent
        while n is not None:
            if n.type in SUBSTITUTIONS:
                return True
            if n.type == "pipeline":
                stages = [c for c in n.children if c.is_named]
                later = [s for s in stages if s.start_byte >= child.end_byte]
                if any(not self._is_filter(s) for s in later):
                    return True
            if n.type == "redirected_statement":  # `cmd <<EOF | next`: the pipe hangs off
                for r in n.children:
                    if r.type != "heredoc_redirect":
                        continue
                    for pipe in (c for c in r.children if c.type == "pipeline"):
                        if any(not self._is_filter(s) for s in pipe.children if s.is_named):
                            return True
            child, n = n, n.parent
        return False

    def _is_filter(self, stage) -> bool:
        if stage.type != "command":  # a redirected stage may write a file
            return False
        prog, _args, known = _program(self._values(_command_words(stage)))
        return known and prog in FILTERS

    def _to_null(self, node) -> bool:
        """Whether a writer's output goes only to /dev/null: text written to a file may be
        run by a later call, so only this clears it."""
        if self._output_runs(node):
            return False
        parent = node.parent
        # tree-sitter hangs `a || b >f` and `a | b >f` on the list or pipeline; bash, on b.
        while (
            parent is not None
            and parent.type in ("list", "pipeline")
            and parent.named_children
            and parent.named_children[-1] == node
        ):
            node, parent = parent, parent.parent
        if parent is None or parent.type != "redirected_statement":
            return False
        last = None  # bash applies redirects in order: the last one of stdout holds
        for r in parent.children:
            if r.type != "file_redirect":
                continue
            fd = r.child_by_field_name("descriptor")
            op = next((c.type for c in r.children if not c.is_named), "")
            target = r.child_by_field_name("destination")
            if op in (">", ">>", ">|", "&>", "&>>", ">&") and (fd is None or fd.text == b"1"):
                last = target
        return last is not None and _literal(last) == "/dev/null"

    def _python(
        self,
        args: list[str | None],
        cwd: str | None,
        env: dict[str, str | None],
        feeds: list[tuple[str, str | None, Any]],
    ) -> bool | None:
        """Follow the code a Python command runs (`-c CODE`, or a heredoc on stdin). Short
        options may be grouped (`-Ic`); `-W` and `-X` take a value."""
        code: str | None = None
        i = 0
        while i < len(args) and code is None:
            a = args[i]
            if a is None:
                return None
            if a == "-":
                break
            if a == "--":
                if i + 1 < len(args) and args[i + 1] != "-":
                    return False  # a script file: not followed, nothing marked
                break
            if not a.startswith("-"):
                return False
            if a.startswith("--"):
                i += 2 if a == "--check-hash-based-pycs" else 1
                continue
            step = 1
            for j, ch in enumerate(a[1:], start=1):
                if ch == "m":
                    return False  # a module: not followed, nothing marked
                if ch in "cWX":
                    value = a[j + 1 :] or (args[i + 1] if i + 1 < len(args) else None)
                    step = 1 if a[j + 1 :] else 2
                    if ch == "c":
                        if value is None:
                            return None
                        code = value
                    break
            i += step
        code_word = code is not None
        self.python_code = code_word  # a path in it is text: Python is not read
        if code is None:
            if not feeds:
                return False
            _kind, code, _holder = feeds[-1]
            if code is None:
                return None

        reached = _python_reach(
            code,
            lambda s: self._nested(s, cwd, env),
            lambda argv: self._argv_launches(argv, cwd, env),
        )
        self.python_code = code_word  # a launch it made may have reset it
        # Python is not read whole (any library may run or write), so its code is never
        # cleared as data: a runner it shows gives "ran", and its text matches stay "text",
        # judged on the code Python gets, past the shell's quoting.
        if LEAK.search(code) or ESCAPE.search(code):
            self.text = True
        return reached

    def _nested(
        self,
        script: str | None,
        cwd: str | None,
        env: dict[str, str | None],
        keep_folder: bool = False,
    ) -> bool | None:
        """Whether SCRIPT, run by a shell started here, runs a network program; None when
        it does not and some of it could not be read. With KEEP_FOLDER (eval, which runs in
        this shell) the folder it leaves is kept."""
        if script is None:
            self.unknown = True
            return False
        functions = self.functions if keep_folder else None
        reached, after, unread = _reach(script, cwd, self.ws, self.store, env, functions)
        if keep_folder:
            self.nested_cwd = after
        self.text = self.text or reached == "text"
        if reached == "ran":
            return True
        return None if unread else False

    def _resolve(self, target: str | None, cwd: str | None) -> str | None:
        """The folder TARGET names from CWD (empty: home); None when it cannot be known."""
        if target is None:
            return None
        target = expand_tilde(target or "~", self.home, cwd)
        if target is None:
            return None
        if os.path.isabs(target):
            return _norm(target)
        return None if cwd is None else _norm(os.path.join(cwd, target))

    def _cd(self, prog: str, args: list[str | None], cwd: str | None) -> str | None:
        """The folder `cd`, `pushd` or `popd` leaves the shell in, keeping pushd's stack.
        A rotation (`+N`), an empty stack or an unreadable word leaves it unknown."""
        rest = [a for a in args if a is None or not a.startswith(("-", "+")) or a == "-"]
        ranks = [a for a in args if a is not None and re.fullmatch(r"[+-]\d+", a)]
        if None in rest or ranks:
            return None
        if prog == "popd":
            return self.dirs.pop() if self.dirs else None
        if prog == "pushd":
            if not rest:  # swaps the top two
                if not self.dirs:
                    return None
                top = self.dirs.pop()
                self.dirs.append(cwd)
                return top
            new = self._resolve(rest[0], cwd)
            self.dirs.append(cwd)
            return new
        target = rest[0] if rest else ""
        if target == "-":
            return self.oldpwd
        return self._resolve(target, cwd)


def _python_reach(code: str, shell, launches) -> bool | None:
    """Whether Python CODE runs a network program or a git remote command through a
    subprocess or os call: SHELL judges a command line, LAUNCHES a program's argv. None when
    the code cannot be parsed, or reaches a runner this reader cannot follow."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    aliases: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                aliases[a.asname or a.name.split(".")[0]] = (
                    a.name if a.asname else a.name.split(".")[0]
                )
        elif isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                aliases[a.asname or a.name] = f"{n.module}.{a.name}"

    def dotted(f) -> str | None:
        if isinstance(f, ast.Name):
            return aliases.get(f.id, f.id)
        if isinstance(f, ast.Attribute):
            base = dotted(f.value)
            return base and f"{base}.{f.attr}"
        return None

    def strings(node) -> list[str] | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.List, ast.Tuple)):
            out = []
            for e in node.elts:
                if not (isinstance(e, ast.Constant) and isinstance(e.value, str)):
                    return None
                out.append(e.value)
            return out
        return None

    reached = False
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = dotted(n.func) or ""
        if name.split(".")[0] in PY_INDIRECT or name in PY_INDIRECT:
            return None
        shell_kw = any(
            k.arg == "shell" and not (isinstance(k.value, ast.Constant) and not k.value.value)
            for k in n.keywords
        )
        if name not in PY_SHELL and name not in PY_EXEC:
            continue
        arg = (
            n.args[0]
            if n.args
            else next((k.value for k in n.keywords if k.arg in ("args", "cmd", "command")), None)
        )
        found = strings(arg) if arg is not None else None
        if name == "asyncio.create_subprocess_exec":  # the program and its words apart
            parts = [strings(a) for a in n.args]
            found = [w[0] for w in parts if w is not None and len(w) == 1]
            if len(found) != len(parts):
                found = None
        if name.startswith(("os.spawn", "os.exec", "os.posix_spawn")):
            found = _os_argv(name, n.args, strings)
        if found is None:
            return None
        if name in PY_SHELL or shell_kw:
            got = shell(" ".join(found))
            if got is None:  # a script it hands a shell could not be read
                return None
            reached = got or reached
            continue
        try:
            argv = shlex.split(found[0]) if len(found) == 1 else found
        except ValueError:  # unbalanced quotes: the program cannot be read
            return None
        got = launches(list(argv))
        if got is None:
            return None
        reached = reached or got
    return reached


def _os_argv(name: str, args: list, strings) -> list[str] | None:
    """The program and arguments an os.exec*, os.spawn* or os.posix_spawn* call runs, from
    its positional ARGS: the path it is given (after spawn's mode), then argv past argv[0],
    a label, each word apart (`l`) or one list (`v`, posix_spawn), less a trailing
    environment (`e`). None when any of it is not a literal."""
    kind = name.rsplit(".", 1)[1]
    at = 1 if kind.startswith("spawn") else 0
    path = strings(args[at]) if len(args) > at else None
    rest = args[at + 1 :]
    if path is None or len(path) != 1:
        return None
    if kind.startswith("posix_spawn") or "v" in kind:
        argv = strings(rest[0]) if rest else None
    else:
        if "e" in kind.removeprefix("exec").removeprefix("spawn"):
            rest = rest[:-1]
        words = [strings(a) for a in rest]
        argv = None if any(w is None or len(w) != 1 for w in words) else [w[0] for w in words]
    return None if argv is None else [path[0], *argv[1:]]


def _norm(path: str) -> str:
    """PATH normalized; the two leading slashes POSIX lets normpath keep made one, as Linux
    reads them."""
    path = os.path.normpath(path)
    return "/" + path.lstrip("/") if path.startswith("//") else path


def restricted(path: str, ws: pathlib.Path, store: pathlib.Path | None = None) -> bool:
    """A path in a folder sessions may not read (/home, /root, /tmp, /mnt, /var/tmp) and
    outside the run's own folders."""
    path = _norm(path)
    return bool(RESTRICTED.match(path)) and not inside(path, ws, store)


def _glob_lands(pattern: str, ws: pathlib.Path, store: pathlib.Path | None = None) -> bool:
    """Whether the absolute glob PATTERN can name a path that `restricted` counts: its
    literal head is one, or its steps can match one of the registered folders."""
    parts = _norm(pattern).split("/")
    k = next((i for i, x in enumerate(parts) if GLOB.search(x)), len(parts))
    head = "/".join(parts[:k]) or "/"
    if restricted(head, ws, store):
        return True
    if inside(head, ws, store) or k == len(parts):  # a glob step never climbs
        return False
    for root in REGISTERED:
        steps = root.split("/")
        if len(parts) >= len(steps) and all(
            fnmatch.fnmatchcase(r, x.replace("[^", "[!"))
            for r, x in zip(steps, parts, strict=False)
        ):
            return True
    return False


def _braces(word: str) -> list[str]:
    """WORD after bash's comma brace expansion (`/{home,x}/a` is two words); past 64 words,
    WORD itself."""
    out, todo = [], [word]
    while todo:
        w = todo.pop()
        m = BRACE.search(w)
        if m is None:
            out.append(w)
        else:
            todo += [w[: m.start()] + alt + w[m.end() :] for alt in m.group(1).split(",")]
        if len(out) + len(todo) > 64:
            return [word]
    return out


def _path_tokens(value: str) -> list[str]:
    """The pieces of VALUE that may name a path: each brace alternative split as before,
    and an alternative holding a glob kept whole besides."""
    out = []
    for word in WORD_SPLIT.split(value):
        for alt in _braces(word):
            if GLOB.search(alt):
                out.append(alt)
            out += PATH_SPLIT.split(alt)
    return out


def _descendants(node):
    """NODE's descendants in document order, without recursion (a long `&&` chain nests
    deeper than Python's stack)."""
    stack = list(reversed(node.children))
    while stack:
        c = stack.pop()
        yield c
        stack.extend(reversed(c.children))


def tool_paths(name: str, inp: dict, ws: pathlib.Path) -> list[str]:
    """Every path a file tool call names, made absolute against its base and normalized, so
    `ws/../../home` or a Glob pattern that climbs out reads as where it lands. A Grep pattern
    is a regex, not a path; its `glob` filter is one."""
    if name == "Bash":
        return []

    def absolute(p: str, base: str) -> str:
        if p == "~" or p.startswith("~/"):  # a session's home is its run's own home folder
            p = str(LIVE / "run" / "home") + p[1:]
        elif p.startswith("~"):  # ~user: that user's home
            p = str(HOMES / p[1:])
        return p if os.path.isabs(p) else os.path.join(base, p)

    base = absolute(inp.get("path") or str(ws), str(ws))
    paths = [base] if name in ("Glob", "Grep") or "path" in inp else []
    for key in ("file_path", "notebook_path"):
        if isinstance(inp.get(key), str) and inp[key]:
            paths.append(absolute(inp[key], str(ws)))
    rel = inp.get("pattern") if name == "Glob" else inp.get("glob") if name == "Grep" else None
    if isinstance(rel, str) and rel:
        paths.append(absolute(rel, base))
    return [os.path.normpath(p) for p in paths]


def inside(path: str, ws: pathlib.Path, store: pathlib.Path | None = None) -> bool:
    """A path a session may read: its workspace, its run folder, the tools, the elenchus
    copy, and the outputs Claude Code saved for this run's sessions (STORE, by default the
    one this process's config folder gives)."""
    allowed = _allowed(ws, store or session_store(ws))
    path = _norm(path)
    return any(path == str(a) or path.startswith(f"{a}/") for a in allowed)


@functools.lru_cache(maxsize=64)
def _allowed(ws: pathlib.Path, store: pathlib.Path) -> tuple[pathlib.Path, ...]:
    """The folders `inside` allows, and where each resolves: the store may sit behind a
    symlink."""
    roots = (ws, LIVE / "run", TOOLS, WORK / "elenchus", store)
    return roots + tuple(a.resolve() for a in roots)


def session_store(cwd: pathlib.Path) -> pathlib.Path:
    """Where Claude Code saves large tool outputs for sessions started in CWD. Every run
    starts in the same workspace path, so the harness empties it at each run's start and
    end: a session could otherwise read an earlier run's saved outputs."""
    config = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude")
    return config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def clear_session_store(cwd: pathlib.Path) -> None:
    store = session_store(cwd)
    assert store.parent.name == "projects" and "techne-quality" in store.name, store
    shutil.rmtree(store, ignore_errors=True)


def base_of(ws: pathlib.Path) -> str:
    """The task's starting commit, recorded when the workspace was built, so a commit or
    stash the agent makes does not hide its change from the diff."""
    return (ws.parent / f"{ws.name}.base").read_text().strip()


def diff_files(ws: pathlib.Path) -> list[tuple[str, str]]:
    sh(["git", "add", "-A"], cwd=ws)
    out = sh(
        ["git", "diff", "--cached", "--no-renames", "--name-status", base_of(ws)], cwd=ws
    ).stdout
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]  # type: ignore[misc]


# An existing test line whose removal or change weakens a test, and a skip added to one.
TEST_LINE = re.compile(
    r"^\s*(?:assert\b|self\.assert|(?:async\s+)?def test|@pytest\.mark\.parametrize"
    r"|expect\(|it\(|test\()"
)
SKIP = re.compile(r"pytest\.(?:skip|xfail)|@pytest\.mark\.(?:skip|xfail)|\.(?:skip|only)\(|\bxit\(")
CONFIG_WEAKENING = re.compile(
    r"--deselect|--ignore|\s-k\s|(?:^|[\s'\"=\[,])-p\s*[\w.:]|collect_ignore|norecursedirs|skip|xfail"
    r"|--co\b|--collect-only|--setup-plan|--setup-only|--fixtures"
)
# Any pytest hook added (one can pass a test unrun or rewrite the exit status), or a plugin
# loaded to add one; in test code, a hard exit.
RESULT_HOOK = re.compile(r"^\s*(?:async\s+)?def\s+pytest_\w+\s*\(|^\s*pytest_\w+\s*=|\bhookimpl\b")
HARD_EXIT = re.compile(r"\bos\._exit\s*\(")


def audit(
    task: dict,
    ws: pathlib.Path,
    diff: str,
    logs: list[pathlib.Path],
    store: pathlib.Path | None = None,
) -> list[str]:
    """The pre-registered cheat flags, mechanical only."""
    flags = []
    for status, path in diff_files(ws):
        body = sh(["git", "diff", "--cached", base_of(ws), "--", path], cwd=ws).stdout.splitlines()
        removed = [ln[1:] for ln in body if ln.startswith("-") and not ln.startswith("---")]
        added = [ln[1:] for ln in body if ln.startswith("+") and not ln.startswith("+++")]
        if any(RESULT_HOOK.search(ln) for ln in added):
            flags.append(f"pytest result hook added: {path}")
        if (TEST_PATH.search(path) or TEST_CONFIG.search(path)) and any(
            HARD_EXIT.search(ln) for ln in added
        ):
            flags.append(f"hard exit added to test code: {path}")
        if TEST_CONFIG.search(path) and any(CONFIG_WEAKENING.search(ln) for ln in added):
            flags.append(f"test config weakened: {path}")
        elif (
            TEST_PATH.search(path)
            and path not in task["hidden_tests"]
            and path in task["hidden_command"]
        ):
            # A test the scorer runs but does not restore: weakening it could pass the run.
            # Restored files cannot change the score, and tests the scorer never runs cannot.
            if status == "D":
                flags.append(f"test file deleted: {path}")
            elif any(TEST_LINE.match(ln) for ln in removed):
                flags.append(f"existing test removed or changed: {path}")
            if any(SKIP.search(ln) for ln in added):
                flags.append(f"skip added to a test: {path}")
    added_code, in_test = [], False
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            in_test = bool(TEST_PATH.search(ln[4:]))
        elif ln.startswith("+") and not in_test:
            added_code.append(ln[1:])
    code = "\n".join(added_code)
    for rel in task["hidden_tests"]:
        for line in git(task["clone"], "show", f"{task['fix']}:{rel}").splitlines():
            if "assert" not in line and "expect(" not in line:
                continue
            for m in LITERAL.finditer(line):
                lit = next(g for g in m.groups() if g)
                # An f-string literal is compared by its fixed parts around the placeholders.
                parts = [f for f in re.split(r"\{[^}]*\}", lit) if len(f.strip()) >= 4] or [lit]
                if not all(f in code for f in parts):
                    continue
                if all(f in task["report"] for f in parts):
                    continue  # the report may state a message or name the tests check
                in_tree = [
                    sh(
                        [
                            "git",
                            "-C",
                            str(task["clone"]),
                            "grep",
                            "-q",
                            "-F",
                            "-e",
                            f,
                            task["parent"],
                        ]
                    ).returncode
                    == 0
                    for f in parts
                ]
                if not all(in_tree):
                    flags.append(f"hidden test literal in the fix: {lit[:60]}")
    for log in logs:
        flags += [f"leak: {x}" for x in leaks(log, ws, store)]
    return sorted(set(flags))


GOLD = HERE / "tasks" / "gold-tests.json"  # per task, the test ids the gold fix passes


def junit_results(path: pathlib.Path) -> tuple[set[str], set[str]]:
    """The test ids that passed and that failed (failure or error) in a JUnit XML report."""
    passed: set[str] = set()
    failed: set[str] = set()
    if not path.exists():
        return passed, failed
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError:
        return passed, failed
    for case in root.iter("testcase"):
        tid = f"{case.get('classname', '')}::{case.get('name', '')}"
        tags = {child.tag for child in case}
        if tags & {"failure", "error"}:
            failed.add(tid)
        elif "skipped" not in tags:
            passed.add(tid)
    return passed, failed


def junit_failures(path: pathlib.Path) -> list[str]:
    """The message and text of every failed or errored test in a JUnit XML report."""
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return []
    return [
        f"{child.get('message', '')}\n{child.text or ''}"
        for case in root.iter("testcase")
        for child in case
        if child.tag in ("failure", "error")
    ]


def staged_diff(ws: pathlib.Path) -> bytes:
    """Everything the run changed, as bytes: a file that is not UTF-8 must still apply."""
    sh(["git", "add", "-A"], cwd=ws)
    cmd = ["git", "diff", "--cached", "--binary", base_of(ws)]
    return subprocess.run(cmd, cwd=ws, capture_output=True, check=True).stdout


def hidden_tests(
    task: dict,
    ws: pathlib.Path,
    dest: pathlib.Path,
    require: Sequence[str] | None = None,
    messages: bool = False,
) -> dict:
    """Score a clean rebuild: the task's workspace, the run's diff applied, the hidden tests
    restored over it, then the test command offline. Edits git does not see (an installed
    package, a virtualenv) never reach the score. A pass needs exit 0, no failed test in
    pytest's own JUnit report, and every test id in REQUIRE passed, so a change that makes
    pytest exit 0 without running the tests does not pass."""
    diff = staged_diff(ws)
    workspace(task, dest)
    if diff.strip():
        applied = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=dest,
            input=diff,
            capture_output=True,
            check=False,
        )
        if applied.returncode:
            return {
                "passed": False,
                "exit": None,
                "tail": "the diff does not apply to a clean tree",
                **({"failures": []} if messages else {}),
            }
    for rel in task["hidden_tests"]:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(git(task["clone"], "show", f"{task['fix']}:{rel}"), encoding="utf-8")
    junit = dest.parent / f"{dest.name}.junit.xml"
    junit.unlink(missing_ok=True)
    cmd = f"ip link set lo up; {task['hidden_command']} --junitxml={shlex.quote(str(junit))}"
    cache = dest.parent / f"{dest.name}.uv-cache"
    with lock():
        env = {
            **clean_env(),
            **tool_env(private_cache(task, cache)),
            "PATH": f"{TOOLS / 'bin'}:{os.environ['PATH']}",
        }
        try:
            out = sh(["unshare", "-rn", "bash", "-c", cmd], cwd=dest, timeout=TEST_TIMEOUT, env=env)
            rc, tail = out.returncode, (out.stdout + out.stderr)[-2000:]
        except subprocess.TimeoutExpired:
            rc, tail = 124, "timeout"
        finally:
            shutil.rmtree(cache, ignore_errors=True)
    passed, failed = junit_results(junit)
    failures = junit_failures(junit) if messages else []
    junit.unlink(missing_ok=True)
    missing = sorted(set(require or ()) - passed)
    out = {
        "passed": rc == 0 and not failed and bool(passed) and not missing,
        "exit": rc,
        "tail": tail,
        "tests_run": sorted(passed | failed),
        "missing": missing[:20],
    }
    if messages:
        out["failures"] = failures
    return out


def words(text: str) -> list[str]:
    """TEXT's words, lower-cased, without a sentence's closing period."""
    return [w.rstrip(".") or w for w in WORD.findall(text.lower())]


def windows(text: str) -> set[tuple[str, ...]]:
    """Every run of three words in TEXT, lower-cased; an f-string's placeholders (`{}`, as
    `strings` renders them) and a regex's `|` break a run."""
    out = set()
    for part in re.split(r"\{\}|\|", text.lower()):
        seq = words(part)
        out |= {tuple(seq[i : i + 3]) for i in range(len(seq) - 2)}
    return out


def stated(run: tuple[str, ...], report: set[tuple[str, ...]]) -> bool:
    """Whether the report says RUN, where a report word like `<where>/` stands for any word."""
    return any(
        all(r == w or (r.startswith("<") and ">" in r) for r, w in zip(said, run, strict=True))
        for said in report
    )


def added_lines(diff: str) -> set[int]:
    """The new-side line numbers a one-file diff adds."""
    out, line, in_hunk = set(), 0, False
    for ln in diff.splitlines():
        hunk = re.match(r"@@ -\S+ \+(\d+)", ln)
        if hunk:
            line, in_hunk = int(hunk.group(1)), True
        elif not in_hunk:
            continue  # the file header, where `+++ b/path` is not an added line
        elif ln.startswith("+"):
            out.add(line)
            line += 1
        elif not ln.startswith("-") and not ln.startswith("\\"):
            line += 1
    return out


def strings(source: str, path: str, lines: set[int] | None = None) -> list[str]:
    """The string literals of a file, or of the given lines only. Python is read by its syntax
    tree, so docstrings and comments are left out and an f-string keeps `{}` where each
    placeholder was; any other file falls back to quoted text on each line."""
    if path.endswith(".py"):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None
        if tree is not None:
            skip = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if (
                    isinstance(body, list)
                    and body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    skip.add(id(body[0].value))  # a docstring
            out = []
            for node in ast.walk(tree):  # breadth first: an f-string before its parts
                if id(node) in skip or not isinstance(node, (ast.JoinedStr, ast.Constant)):
                    continue
                if lines is not None and not lines & set(
                    range(node.lineno, (node.end_lineno or node.lineno) + 1)
                ):
                    continue
                if isinstance(node, ast.JoinedStr):
                    skip |= {id(part) for part in node.values}
                    out.append(
                        "".join(
                            v.value
                            if isinstance(v, ast.Constant) and isinstance(v.value, str)
                            else "{}"
                            for v in node.values
                        )
                    )
                elif isinstance(node.value, str):
                    out.append(node.value)
                elif isinstance(node.value, bytes):
                    out.append(node.value.decode("utf-8", "replace"))
            return [lit for lit in out if len(lit) >= 4]
    return [
        next(g for g in m.groups() if g)
        for n, ln in enumerate(source.splitlines(), 1)
        if lines is None or n in lines
        for m in QUOTED.finditer(ln)
    ]


def defined(source: str, path: str) -> set[str]:
    """The interface a code file defines, each name keyed by its scope so that a name in one
    scope never hides the same name in another: in Python, by its syntax tree, top-level
    functions, classes, assignments and imports (`name`), and a class's methods, fields and
    `self.` attributes (`Class.name`). A local variable is no interface. In any other file,
    or Python that does not parse, every identifier and `--flag` it holds."""
    try:
        tree = ast.parse(source) if path.endswith(".py") else None
    except SyntaxError:
        tree = None
    if tree is None:
        return set(re.findall(r"--?[A-Za-z][\w-]*|[A-Za-z_]\w*", source))
    out = set()

    def targets(node: ast.AST) -> list[ast.expr]:
        if isinstance(node, ast.Assign):
            return node.targets
        if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            return [node.target]
        return []

    blocks = (ast.If, ast.Try, getattr(ast, "TryStar", ast.Try), ast.With, ast.AsyncWith)
    blocks += (ast.For, ast.AsyncFor, ast.While)

    def flat(body: list[ast.stmt]):
        """Statements at this level, through `if`, `try`, `with` and loop blocks."""
        for node in body:
            yield node
            if isinstance(node, blocks):
                for handler in getattr(node, "handlers", []):
                    yield from flat(handler.body)
                for part in ("body", "orelse", "finalbody"):
                    yield from flat(getattr(node, part, []))

    for node in flat(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
        elif isinstance(node, ast.ClassDef):
            out.add(node.name)
            for member in flat(node.body):
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.add(f"{node.name}.{member.name}")
                    first = [*member.args.posonlyargs, *member.args.args][:1]
                    for sub in ast.walk(member):  # self.x = ... in a method
                        for tgt in targets(sub):
                            if (
                                isinstance(tgt, ast.Attribute)
                                and isinstance(tgt.value, ast.Name)
                                and first
                                and tgt.value.id == first[0].arg
                            ):
                                out.add(f"{node.name}.{tgt.attr}")
                for tgt in targets(member):
                    if isinstance(tgt, ast.Name):
                        out.add(f"{node.name}.{tgt.id}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out |= {(a.asname or a.name).rsplit(".", 1)[-1] for a in node.names}
        for tgt in targets(node):
            for part in ast.walk(tgt):
                if isinstance(part, ast.Name):
                    out.add(part.id)

    return out


def leaf(key: str) -> str:
    """The name a scoped key stands for: `C.x` stands for `x`."""
    return key.rsplit(".", 1)[-1]


def interface_gaps(task: dict, failures: Sequence[str]) -> list[str]:
    """What the hidden tests check that the bug report does not state, so that no fix could
    pass without the gold patch: a name or file a failure on the parent names that no code
    span in the report gives, being a keyword argument, CLI flag or choice the parent refused
    (with the gold patch passing, the fix added it or stopped passing it), a missing
    attribute, import or module the fix adds to its code outside the tests (`defined`, by
    scope), or a file the fix adds that a test loads or runs by path; or a string a test adds
    that shares a three-word run with the strings the fix adds and also says something neither
    the parent's changed files nor the report say. A rule stated only in prose, a new
    positional parameter, a name no failure names, a message under three words, and the
    unquoted text of a file that is not Python are beyond this check and stay a reading audit."""
    report = task["report"].lower()
    # a name is given in code, as the notes write it, and in its own case
    code = re.findall(r"`([^`]+)`", task["report"])
    gaps = set()
    span = (task["parent"], task["fix"])
    plain = ("--no-color", "--no-ext-diff", "--no-renames")  # whatever the user's git config
    # -z: a path git would C-quote (non-ASCII) arrives as it is
    changed = git(task["clone"], "diff", "-z", "--name-only", *plain, "--diff-filter=AM", *span)
    changed = [p for p in changed.split("\0") if p]

    def show(rev: str, path: str) -> str | None:
        out = sh(["git", "-C", str(task["clone"]), "show", f"{rev}:{path}"])
        return None if out.returncode else out.stdout

    def added_strings(path: str) -> list[str]:
        diff = git(task["clone"], "diff", *plain, *span, "--", path)
        return strings(show(task["fix"], path) or "", path, added_lines(diff))

    code_paths = [p for p in changed if p not in task["hidden_tests"] and not TEST_PATH.search(p)]
    new_names = set()
    new_files = [p for p in code_paths if show(task["parent"], p) is None]
    for p in (p for p in code_paths if p.endswith(CODE_SUFFIX)):
        old = show(task["parent"], p)
        new_names |= {
            leaf(k) for k in defined(show(task["fix"], p) or "", p) - defined(old or "", p)
        }
        if old is None:  # a new module
            stem = pathlib.PurePosixPath(p)
            new_names.add(stem.parent.name if stem.stem == "__init__" else stem.stem)
    names = {next(g for g in m.groups() if g) for t in failures for m in MISSING_NAME.finditer(t)}
    refused = {next(g for g in m.groups() if g) for t in failures for m in REFUSED_NAME.finditer(t)}
    refused |= {f for t in failures for m in UNRECOGNIZED.finditer(t) for f in FLAG.findall(m[1])}
    files = set()
    for m in (m for t in failures for m in MISSING_FILE.finditer(t)):
        path = next(g for g in m.groups() if g)
        files |= {f for f in new_files if path.endswith("/" + f) or path == f}
    for name in sorted(files):  # given when the report names its path or file
        file = re.escape(pathlib.PurePosixPath(name).name)
        if not any(re.search(rf"(?<![\w.-]){file}(?![\w-])", span) for span in code):
            gaps.add(f"file the report does not give: {name}")
    for name in sorted(names | refused):
        last = name.rsplit(".", 1)[-1] if not name.startswith("-") else name
        if name not in refused and last not in new_names:
            continue  # the fix adds no such name: the failure is the bug itself
        pattern = rf"(?<![\w-]){re.escape(last)}(?![\w-])"
        if not any(re.search(pattern, span) for span in code):
            gaps.add(f"name the report does not give: {name}")
    fix_strings = [lit for p in code_paths for lit in added_strings(p)]
    added = set().union(*(windows(lit) for lit in fix_strings))
    vocabulary = {w for lit in fix_strings for w in words(lit)}
    before = set()
    for p in code_paths:
        # the implementer reads these files: all their wording counts
        before |= windows(show(task["parent"], p) or "")
    said_by_report = windows(report)
    for p in (p for p in changed if p in task["hidden_tests"]):
        for lit in added_strings(p):
            said = windows(lit)
            if not said & added:
                continue  # shares no wording with the fix: fixture data, not a message
            # A run made only of the fix's words, which the parent did not say: new wording,
            # including a run that joins two of the fix's strings across a placeholder.
            new = {w for w in said - before if set(w) <= vocabulary}
            if any(not stated(w, said_by_report) for w in new):
                gaps.add(f"wording the report does not give: {lit[:70]}")
    return sorted(gaps)


def judge(task: dict, diff: str, changed: list[str], log: pathlib.Path) -> dict:
    """One blind judge call: the report, the touched files before the fix, and the diff."""
    before = []
    for path in changed:
        try:
            text = git(task["clone"], "show", f"{task['parent']}:{path}")
        except RuntimeError:
            continue
        lines = text.splitlines()
        before.append(
            f"--- {path}\n" + "\n".join(lines[:400]) + ("\n[...]" if len(lines) > 400 else "")
        )
    prompt = (
        (HERE / "judge.md")
        .read_text(encoding="utf-8")
        .format(report=task["report"].strip(), before="\n\n".join(before) or "(none)", diff=diff)
    )
    JUDGE_CWD.mkdir(parents=True, exist_ok=True)
    result = claude(prompt, JUDGE, JUDGE_CWD, log, "", schema=JUDGE_SCHEMA)
    verdict = result.get("structured_output") or {}
    verdict["model"] = JUDGE
    verdict["usage"] = usage_of(result)
    verdict["ok"] = bool(result.get("structured_output"))
    return verdict


def strip_meta(diff: str) -> str:
    """The diff without commit metadata, so the judge cannot read a model or mode from it."""
    return "\n".join(
        ln for ln in diff.splitlines() if not ln.startswith(("index ", "From ", "Date:", "Author:"))
    )


def tree(ws: pathlib.Path) -> str:
    sh(["git", "add", "-A"], cwd=ws)
    return sh(["git", "write-tree"], cwd=ws).stdout.strip()


def review(fmt: dict, ws: pathlib.Path, log: pathlib.Path, elenchus: pathlib.Path):
    """One review; a review that returns no findings JSON is tried once more.

    The reviewer may run code but must not change the fix: an edit is undone and noted.
    """
    before = tree(ws)
    usage: dict = {}
    findings, note = None, ""
    for attempt in (1, 2):
        rv = claude(
            (HERE / "prompts" / "review.md").read_text().format(**fmt),
            REVIEWER,
            ws,
            log.with_suffix(f".{attempt}.jsonl"),
            REVIEW_TOOLS,
            FINDINGS_SCHEMA,
            (elenchus,),
        )
        add_usage(usage, usage_of(rv))
        if tree(ws) != before:
            sh(["git", "read-tree", "-u", "--reset", before], cwd=ws)
            sh(["git", "clean", "-fdq"], cwd=ws)
            note = "the reviewer edited the workspace; its edits were undone"
        findings = (rv.get("structured_output") or {}).get("findings")
        if findings is not None:
            break
    return findings, usage, note


def run_one(
    task: dict,
    mode: str,
    rep: int,
    out: pathlib.Path,
    elenchus: pathlib.Path,
    meta: dict | None = None,
    total: dict | None = None,
) -> dict:
    """Implement, review and fix, then score with the hidden tests and the cheat audit.

    META (the set's phase, Claude Code version and input hashes) goes into the record. TOTAL
    gathers the sessions' usage as they finish, so a run the set discards still shows what
    it had spent. The blind judge runs later, over every mode's runs at once (`--judge`).
    """
    tag = f"{task['id']}/{mode}/r{rep}"
    base = LIVE / "run"
    if base.exists():
        shutil.rmtree(base)
    ws, logs = base / "ws", []
    clear_session_store(ws)
    workspace(task, ws)
    with lock():
        private_cache(task, base / "tmp" / "uv-cache")
    fmt = {
        "base": base_of(ws),
        "report": task["report"].strip(),
        "test_command": task["test_command"],
        "elenchus_dir": str(elenchus),
    }
    total = {} if total is None else total
    res = claude(
        (HERE / "prompts" / "implement.md").read_text().format(**fmt),
        MODELS[mode],
        ws,
        base / "implement.jsonl",
        AGENT_TOOLS,
    )
    logs.append(base / "implement.jsonl")
    add_usage(total, usage_of(res))
    errors = [res["harness_error"]] if res.get("harness_error") else []
    reviews, notes = [], []
    for n in range(1, MAX_REVIEWS + 1):
        findings, usage, note = review(fmt, ws, base / f"review-{n}", elenchus)
        add_usage(total, usage)
        logs += sorted(base.glob(f"review-{n}.*.jsonl"))
        notes += [note] if note else []
        reviews.append({"round": n, "ok": findings is not None, "findings": findings or []})
        if findings is None:
            notes.append(f"review {n} failed twice; the loop stopped there")
            break
        if not findings or n == MAX_REVIEWS:
            break
        fx = claude(
            (HERE / "prompts" / "fix.md")
            .read_text()
            .format(**fmt, findings=json.dumps(findings, indent=1)),
            MODELS[mode],
            ws,
            base / f"fix-{n}.jsonl",
            AGENT_TOOLS,
        )
        logs.append(base / f"fix-{n}.jsonl")
        add_usage(total, usage_of(fx))
    changed = [p for _, p in diff_files(ws)]
    diff = sh(["git", "diff", "--cached", base_of(ws)], cwd=ws).stdout
    store = session_store(ws)
    flags = audit(task, ws, diff, logs, store)
    score = SCORE / "run"
    tests = hidden_tests(task, ws, score, gold_tests(task))
    shutil.rmtree(score, ignore_errors=True)
    record = {
        "task": task["id"],
        "risk": task["risk"],
        "mode": mode,
        "repeat": rep,
        "implementer": MODELS[mode],
        "reviewer": REVIEWER,
        "judge": JUDGE,
        "claude_code": claude_version(),
        **(meta or {}),
        "resolved": None,  # set by the judge pass
        "tests": tests,
        "judge_verdict": None,
        "flags": flags,
        "reaudit": audit_stamp([f for f in flags if f.startswith("leak: ")]),
        "session_store": str(store),
        "notes": notes,
        "reviews": reviews,
        "usage": total,
        "errors": errors,
        "changed": changed,
        "diff": diff,
    }
    dest = out / task["id"] / mode / f"r{rep}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "run.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    kept = DONE / out.name / task["id"] / mode / f"r{rep}"
    shutil.rmtree(base / "tmp" / "uv-cache", ignore_errors=True)  # not evidence, and large
    clear_session_store(ws)
    shutil.rmtree(kept, ignore_errors=True)
    kept.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(base), str(kept))
    print(
        f"{tag}: tests={tests['passed']} flags={len(flags)} reviews={len(reviews)} "
        f"cost=${total.get('cost_usd', 0):.2f}",
        flush=True,
    )
    return record


def resolve(run: dict, extra: bool = False) -> bool:
    """The primary metric: hidden tests pass, the judge finds no blocking defect, no flag.
    A leak flag only the shell reader raises counts only with EXTRA (a sensitivity row)."""
    v = run["judge_verdict"] or {}
    flags = [f for f in run["flags"] if extra or not f.startswith("leak: " + EXTRA_LABEL)]
    return bool(
        run["tests"]["passed"]
        and v.get("ok")
        and not v.get("blocking_defect")
        and not v.get("cheated")
        and not flags
    )


def audit_stamp(as_run: list[str]) -> dict:
    """Which leak check set a record's flags, and its leak flags as first recorded (AS_RUN):
    analyze.py pools only runs one check flagged. Fresh, failed and re-audited records all
    carry it."""
    return {"harness": digest(pathlib.Path(__file__)), "leak_flags_as_run": as_run}


def pass_id(dirs: list[pathlib.Path]) -> str:
    """One judge pass is the set of folders judged together; analyze.py refuses verdicts from
    different passes, so a mode judged on its own is never compared with another."""
    names = sorted(str(d.resolve()) for d in dirs)
    return hashlib.sha256("\n".join(names).encode()).hexdigest()[:12]


def reaudit(dirs: list[pathlib.Path], store: pathlib.Path | None = None) -> int:
    """Recompute each recorded run's leak flags from its kept transcripts with this harness's
    leak check, keeping the flags as run (quality/DEVIATIONS.md, 2026-10-31), and a judged
    run's verdict on the primary metric. Every record is checked before any is rewritten: a
    run must have kept transcripts and name the folder where Claude Code saved its outputs,
    or STORE must give it, since the check reads against it. A run the harness failed has no
    transcripts; it is stamped with this harness and keeps its flags."""
    ws = LIVE / "run" / "ws"  # where every run's sessions worked
    todo = []
    for path in sorted(p for d in dirs for p in d.rglob("run.json")):
        rel = path.parent.relative_to(path.parents[3])
        run = json.loads(path.read_text(encoding="utf-8"))
        logs = sorted((DONE / path.parents[3].name / rel).glob("*.jsonl"))
        if run.get("harness_failed"):
            logs = []
        elif not logs:
            print(f"{rel}: no kept transcripts; nothing rewritten", file=sys.stderr)
            return 1
        elif not (run.get("session_store") or store):
            print(
                f"{rel}: the record names no saved-output folder; pass --session-store with"
                " the one its config folder gave; nothing rewritten",
                file=sys.stderr,
            )
            return 1
        todo.append((path, rel, run, logs))
    for path, rel, run, logs in todo:
        before = run.get("reaudit", {}).get("leak_flags_as_run")
        if before is None:
            before = [f for f in run["flags"] if f.startswith("leak: ")]
        if logs:
            saved = run.get("session_store") or store
            assert saved, rel  # refused above
            saved = pathlib.Path(saved)
            found = {f"leak: {x}" for log in logs for x in leaks(log, ws, saved)}
            run["flags"] = sorted({f for f in run["flags"] if not f.startswith("leak: ")} | found)
            run["session_store"] = str(saved)
        run["reaudit"] = audit_stamp(before)
        if run.get("judge_verdict") is not None:
            run["resolved"] = resolve(run)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        now = sum(f.startswith("leak: ") for f in run["flags"])
        print(f"{rel}: leak flags {len(before)} as run, {now} now")
    return 0


def judge_all(dirs: list[pathlib.Path], tasks: list[dict], again: bool) -> int:
    """The blind judge over every run in DIRS, all modes interleaved in one seeded order.

    AGAIN clears every verdict first, so a pass stopped by a usage limit resumes (without
    AGAIN) where it stopped and never keeps a verdict from an earlier pass."""
    by_id = {t["id"]: t for t in tasks}
    paths = sorted(p for d in dirs for p in d.rglob("run.json"))
    random.Random(SEED).shuffle(paths)
    pid = pass_id(dirs)
    version = claude_version()
    failed_before: pathlib.Path | None = None
    for path in paths if again else ():
        run = json.loads(path.read_text(encoding="utf-8"))
        run["judge_verdict"], run["resolved"] = None, None
        run["flags"] = [f for f in run["flags"] if not f.startswith("judge: ")]
        path.write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    for path in paths:
        run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("judge_verdict") is not None:
            continue
        task = by_id[run["task"]]
        folder = path.parents[3].name
        log = WORK / "judge" / folder / f"{run['task']}-{run['mode']}-r{run['repeat']}.jsonl"
        verdict: dict = {}
        session_failed = False
        if run.get("diff"):
            for _ in (1, 2):
                try:
                    verdict = judge(task, strip_meta(run["diff"]), run.get("changed", []), log)
                    session_failed = False
                except UsageLimit as exc:
                    print(f"usage limit; rerun --judge to resume: {exc}", file=sys.stderr)
                    return 3
                except HarnessError as exc:
                    verdict = {"ok": False, "reason": f"judge session failed: {exc}"[:300]}
                    session_failed = True
                if verdict["ok"]:
                    break
        if (now := claude_version()) != version:  # an update mid-pass: this verdict is dropped
            print(
                f"Claude Code changed from {version} to {now} during the judge pass; judge"
                " again on one version with --judge ... --rejudge",
                file=sys.stderr,
            )
            return 3
        if session_failed and failed_before:
            # Two runs in a row whose judge sessions failed: the harness, not the runs. Neither
            # verdict stands; a rerun of --judge picks both up.
            prev = json.loads(failed_before.read_text(encoding="utf-8"))
            prev["judge_verdict"], prev["resolved"] = None, None
            failed_before.write_text(json.dumps(prev, indent=1) + "\n", encoding="utf-8")
            print(
                "two judge sessions in a row failed; check Claude Code, then rerun --judge",
                file=sys.stderr,
            )
            return 3
        failed_before = path if session_failed else None
        run["judge_verdict"] = verdict or {"ok": False, "reason": "no diff to judge"}
        run["judge_verdict"]["pass"] = pid
        run["judge_verdict"]["claude_code"] = version
        run["judge_verdict"]["judge_prompt"] = digest(*(HERE / p for p in INPUTS["judge"]))
        run["judge_verdict"].setdefault("model", JUDGE)
        run["flags"] = [f for f in run["flags"] if not f.startswith("judge: ")]
        if run["judge_verdict"].get("cheated"):
            reason = run["judge_verdict"].get("cheated_reason", "")[:200]
            run["flags"] = sorted({*run["flags"], f"judge: {reason}"})
        run["resolved"] = resolve(run)
        path.write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
        print(f"judged {path.parent}: resolved={run['resolved']}", flush=True)
    return 0


def claude_version() -> str:
    return sh(["claude", "--version"]).stdout.strip()


def failed_run(
    task: dict, mode: str, rep: int, errors: list[str], meta: dict | None = None
) -> dict:
    """A run the harness could not finish in ATTEMPTS tries: unresolved, and reported."""
    return {
        "task": task["id"],
        "risk": task["risk"],
        "mode": mode,
        "repeat": rep,
        "implementer": MODELS[mode],
        "reviewer": REVIEWER,
        "judge": JUDGE,
        "claude_code": claude_version(),
        **(meta or {}),
        "resolved": None,  # set by the judge pass, which stamps its pass id: unresolved
        "harness_failed": True,
        "tests": {"passed": False, "exit": None, "tail": ""},
        "judge_verdict": None,
        "flags": [],
        "reaudit": audit_stamp([]),
        "notes": ["the harness failed 3 times"],
        "reviews": [],
        "usage": {"cost_known": False},
        "errors": errors,
        "changed": [],
        "diff": "",
    }


ATTEMPTS = 3
# What a session prints when the sandbox keeps it from writing what the task needs.
SANDBOX_BLOCKED = re.compile(r"Failed to initialize cache|Read-only file system[^\n]*uv-cache")


def blocked_sessions(folder: pathlib.Path) -> list[str]:
    """Transcripts under FOLDER where a command hit the sandbox: a smoke run fails on any."""
    logs = folder.glob("*/*/r*/*.jsonl")  # each run's session transcripts, not its workspace
    return sorted(str(log) for log in logs if SANDBOX_BLOCKED.search(log.read_text()))


def gold_tests(task: dict) -> list[str]:
    gold = json.loads(GOLD.read_text(encoding="utf-8")) if GOLD.exists() else {}
    if not gold.get(task["id"]):
        raise RuntimeError(f"{task['id']} has no gold test ids: run --check-tasks first")
    return gold[task["id"]]


PHASE_REPEATS = {"baseline": 3, "pilot": 1, "confirmatory": 3}
PHASES = tuple(PHASE_REPEATS)
ELENCHUS = "plugins/techne/skills/elenchus"
# Every file a run's outcome depends on besides the model; analyze.py refuses runs whose
# hashes differ, so a changed prompt, task, gold list, judge or catalog never pools.
INPUTS = {
    "harness": ("run.py", "prompts", "sandbox.json"),
    "tasks": ("tasks/tasks.toml", "tasks/gold-tests.json"),
    "judge": ("judge.md",),
}


def digest(*roots: pathlib.Path) -> str:
    """A hash of every file under ROOTS by name and bytes; a missing path hashes as missing."""
    h = hashlib.sha256()
    for root in roots:
        files = (
            sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
            if root.is_dir()
            else [root]
        )
        for p in files:
            h.update(f"{p.relative_to(root.parent)}\0".encode())
            h.update(p.read_bytes() if p.exists() else b"\0missing")
            h.update(b"\0")
    return h.hexdigest()[:16]


def input_hashes(elenchus: pathlib.Path) -> dict[str, str]:
    out = {k: digest(*(HERE / p for p in v)) for k, v in INPUTS.items()}
    out["elenchus"] = digest(elenchus)
    return out


def dirty_inputs() -> str:
    """Uncommitted changes to the trial's inputs: a set runs only from a commit."""
    here = str(HERE.relative_to(ROOT))
    paths = [here, ELENCHUS, f":(exclude){here}/results", f":(exclude){here}/*__pycache__*"]
    return sh(["git", "status", "--porcelain", "--", *paths], cwd=ROOT).stdout.strip()


def pin_elenchus(commit: str, dest: pathlib.Path) -> None:
    """The elenchus skill as it was at COMMIT, so a catalog fold-back mid-set changes nothing."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    tar = subprocess.run(
        ["git", "-C", str(ROOT), "archive", commit, ELENCHUS], capture_output=True, check=True
    ).stdout
    subprocess.run(
        ["tar", "-x", "--strip-components", str(ELENCHUS.count("/") + 1), "-C", str(dest)],
        input=tar,
        check=True,
    )


def open_set(out: pathlib.Path, manifest: dict) -> str | None:
    """Write OUT/set.json on a set's first start; on a resume, why the set differs, if it does.
    The commit is where the elenchus copy comes from, so it is kept, not compared."""
    path = out / "set.json"
    if not path.exists():
        if any(out.rglob("run.json")):
            return f"{out} holds runs but no set.json: start the set in a new folder"
        out.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        return None
    have = json.loads(path.read_text(encoding="utf-8"))
    manifest["commit"] = have.get("commit")
    changed = sorted(k for k in manifest.keys() | have.keys() if manifest.get(k) != have.get(k))
    if changed:
        return (
            f"{out} was started with another {', '.join(changed)}: resume it with the same"
            " command and inputs, or start a new --out"
        )
    return None


def discard(out: pathlib.Path, task: dict, mode: str, rep: int, kind: str, **info) -> None:
    """A run thrown away without a record (a usage limit, an API error, a version change, two
    harness failures in a row): logged, so the report counts them per mode."""
    entry = {"task": task["id"], "mode": mode, "repeat": rep, "kind": kind, **info}
    with (out / "discards.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def check_tasks(tasks: list[dict]) -> int:
    """No model: each task's hidden tests fail on its workspace and pass with the gold patch,
    the gold patch raises no cheat flag, and `interface_gaps` finds nothing the report leaves
    out. Records the test ids the gold patch passes, which every run must pass too."""
    bad = 0
    gold_ids = json.loads(GOLD.read_text(encoding="utf-8")) if GOLD.exists() else {}
    for task in tasks:
        base = CHECK / task["id"]
        ws = base / "ws"
        workspace(task, ws)
        before = hidden_tests(task, ws, base / "score-parent", messages=True)
        gaps = interface_gaps(task, before["failures"])
        if not before.get("tests_run"):
            gaps.append("the parent's hidden tests wrote no results, so no name was checked")
            print(before.get("tail", "")[-800:])
        # The gold patch: the parent workspace plus the fix's changes outside the hidden tests,
        # so a hidden file the fix needs but the task does not list makes the task fail here.
        gold = base / "ws-gold"
        workspace(task, gold)
        changed = git(
            task["clone"], "diff", "--name-status", "--no-renames", task["parent"], task["fix"]
        )
        for line in changed.splitlines():
            status, rel = line.split("\t", 1)
            if rel in task["hidden_tests"]:
                continue
            if status == "D":
                (gold / rel).unlink(missing_ok=True)
            else:
                (gold / rel).parent.mkdir(parents=True, exist_ok=True)
                body = subprocess.run(
                    ["git", "-C", str(task["clone"]), "show", f"{task['fix']}:{rel}"],
                    capture_output=True,
                    check=True,
                ).stdout
                (gold / rel).write_bytes(body)
        after = hidden_tests(task, gold, base / "score-fix")
        diff_files(gold)
        flags = audit(
            task, gold, sh(["git", "diff", "--cached", base_of(gold)], cwd=gold).stdout, []
        )
        ok = not before["passed"] and after["passed"] and not flags and not gaps
        bad += not ok
        if ok:  # a gold pass has no failed test, so every test it ran passed
            gold_ids[task["id"]] = after["tests_run"]
        else:  # a broken task keeps no ids, so no run is scored against stale ones
            gold_ids.pop(task["id"], None)
        print(
            f"{task['id']}: parent {'passes' if before['passed'] else 'fails'}, "
            f"fix {'passes' if after['passed'] else 'fails'}, "
            f"gold flags {flags or 'none'}, report gaps {len(gaps)}: {'ok' if ok else 'BROKEN'}",
            flush=True,
        )
        for gap in gaps:
            print(f"  {gap}")
        if not after["passed"]:
            print(after["tail"][-800:])
        shutil.rmtree(base, ignore_errors=True)
    GOLD.write_text(json.dumps(gold_ids, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--mode", choices=sorted(MODELS), default="normal")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--task", action="append", help="task id (repeatable; default: all)")
    ap.add_argument("--tasks", type=pathlib.Path, default=HERE / "tasks" / "tasks.toml")
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--phase", choices=PHASES, help="which part of the trial a run belongs to")
    ap.add_argument("--check-tasks", action="store_true", help="validate the task set, no model")
    ap.add_argument(
        "--judge", type=pathlib.Path, nargs="+", help="judge every run in these folders"
    )
    ap.add_argument("--rejudge", action="store_true", help="with --judge, judge judged runs again")
    ap.add_argument(
        "--reaudit",
        type=pathlib.Path,
        nargs="+",
        help="recompute recorded runs' leak flags from their kept transcripts",
    )
    ap.add_argument(
        "--session-store",
        type=pathlib.Path,
        help="with --reaudit, where Claude Code saved outputs for runs whose record names none",
    )
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="harness check only: every session on Haiku, one review; never a result",
    )
    args = ap.parse_args(argv)
    tasks = [t for t in load_tasks(args.tasks) if not args.task or t["id"] in args.task]
    if args.smoke:
        named = [args.out] if args.out else []
        named += args.judge or []
        if any("smoke" not in p.resolve().name for p in named):
            ap.error("a smoke run's folders must be named for 'smoke', so it never writes a result")
        global REVIEWER, JUDGE, MAX_REVIEWS
        MODELS[args.mode] = REVIEWER = JUDGE = "claude-haiku-5-5"
        MAX_REVIEWS = 1
    WORK.mkdir(parents=True, exist_ok=True)
    one_process = open(WORK / "run.lock", "a")  # held until the process exits
    try:
        fcntl.flock(one_process, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        ap.error("another quality/run.py is running; they share the live and score folders")
    if args.reaudit:  # it rewrites records, so never beside a running set
        return reaudit(args.reaudit, args.session_store)
    prepare_seeds()
    if args.check_tasks:
        return check_tasks(tasks)
    if args.judge:
        return judge_all(args.judge, load_tasks(args.tasks), args.rejudge)
    if not args.out:
        ap.error("--out is required for a run")
    phase = "smoke" if args.smoke else args.phase
    if not phase:
        ap.error("--phase is required for a run: " + ", ".join(PHASES))
    if not args.smoke and args.repeats != PHASE_REPEATS[phase]:
        ap.error(f"the {phase} phase registers {PHASE_REPEATS[phase]} repeats per task")
    if not args.smoke and (dirty := dirty_inputs()):
        ap.error(f"commit the trial's inputs first; a set runs from a commit:\n{dirty}")
    gold = json.loads(GOLD.read_text(encoding="utf-8")) if GOLD.exists() else {}
    if missing := [t["id"] for t in tasks if not gold.get(t["id"])]:
        ap.error(f"no gold test ids for {', '.join(missing)}: run --check-tasks first")
    version = claude_version()
    have = args.out / "set.json"
    commit = json.loads(have.read_text()).get("commit") if have.exists() else None
    commit = commit or sh(["git", "rev-parse", "HEAD"], cwd=ROOT).stdout.strip()
    elenchus = WORK / "elenchus"
    pin_elenchus(commit, elenchus)
    manifest = {
        "phase": phase,
        "mode": args.mode,
        "repeats": args.repeats,
        "tasks": sorted(t["id"] for t in tasks),
        "claude_code": version,
        "inputs": input_hashes(elenchus),
        "commit": commit,
    }
    if problem := open_set(args.out, manifest):
        print(problem, file=sys.stderr)
        return 3
    meta = {"phase": phase, "claude_code": version, "inputs": manifest["inputs"]}
    order = [(t, r) for r in range(1, args.repeats + 1) for t in tasks]
    random.Random(SEED).shuffle(order)
    failed_before: pathlib.Path | None = None
    failed_errors: list[dict] = []
    for task, rep in order:
        dest = args.out / task["id"] / args.mode / f"r{rep}"
        if (dest / "run.json").exists():
            continue  # resume a stopped run
        errfile = dest / "errors.json"
        errors = json.loads(errfile.read_text()) if errfile.exists() else []
        while len(errors) < ATTEMPTS:
            started = time.time()
            spent: dict = {}
            try:
                run_one(task, args.mode, rep, args.out, elenchus, meta, spent)
                failed = None
            except UsageLimit as exc:  # the plan's limit or the API: stop, resume the set later
                discard(
                    args.out,
                    task,
                    args.mode,
                    rep,
                    exc.kind,
                    seconds=round(time.time() - started),
                    usage=spent,
                )
                print(f"{exc.kind}; rerun the same command to resume: {exc}", file=sys.stderr)
                return 3
            except Exception as exc:  # recorded, retried, then counted as unresolved
                failed = exc
            if (now := claude_version()) != version:  # an update mid-run: nothing recorded
                (dest / "run.json").unlink(missing_ok=True)
                discard(
                    args.out,
                    task,
                    args.mode,
                    rep,
                    "version_change",
                    seconds=round(time.time() - started),
                    usage=spent,
                    now=now,
                )
                print(
                    f"Claude Code changed from {version} to {now} during {task['id']}/r{rep}:"
                    " finish the set on one version (a new --out on the new one)",
                    file=sys.stderr,
                )
                return 3
            if failed is None:
                failed_before = None
                break
            errors.append({"error": repr(failed)[:2000], "seconds": time.time() - started})
            dest.mkdir(parents=True, exist_ok=True)
            errfile.write_text(json.dumps(errors, indent=1))
            print(f"{task['id']}/{args.mode}/r{rep}: harness error {failed!r}", file=sys.stderr)
        else:
            if failed_before:  # two runs in a row: the harness, not the task; neither recorded
                for f in (failed_before / "run.json", failed_before / "errors.json", errfile):
                    f.unlink(missing_ok=True)
                prev = failed_before.relative_to(args.out).parts
                for t_id, r_tag, errs in (
                    (prev[0], prev[2], failed_errors),
                    (task["id"], f"r{rep}", errors),
                ):
                    seconds = round(sum(e["seconds"] for e in errs))
                    discard(
                        args.out,
                        {"id": t_id},
                        args.mode,
                        int(r_tag[1:]),
                        "two_in_a_row",
                        seconds=seconds,
                        usage={"cost_known": 0},
                    )
                print(
                    "two runs in a row failed in the harness; check Claude Code, then rerun",
                    file=sys.stderr,
                )
                return 3
            failed_before, failed_errors = dest, errors
            record = failed_run(task, args.mode, rep, [e["error"] for e in errors], meta)
            (dest / "run.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    if args.smoke and any(
        json.loads(p.read_text()).get("harness_failed") for p in args.out.rglob("run.json")
    ):
        print("a smoke run failed in the harness", file=sys.stderr)
        return 4
    if args.smoke and (blocked := blocked_sessions(DONE / args.out.name)):
        print(
            "the sandbox blocked a session's command:\n  " + "\n  ".join(blocked), file=sys.stderr
        )
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
