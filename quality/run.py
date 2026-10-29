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
import fcntl
import hashlib
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
from collections.abc import Sequence
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
# Commands that try to reach past the sandbox: network tools, git remotes, GitHub. A URL
# alone is not one: the sandbox has no network, and a test may parse one.
LEAK = re.compile(
    r"\b(?:gh|curl|wget|ssh|scp|nc)\s"
    r"|\bgit\b[^|;&\n]*?\s(?:fetch|clone|pull|push|remote|ls-remote)\b"
)
# An absolute path outside the system folders, and a climb out of the workspace.
HOME_PATH = re.compile(r"(?<![\w.])/(?:home|root|tmp|mnt|var/tmp)(?:/[^\s'\";|&)]*)?")
ESCAPE = re.compile(r"(?:^|[\s'\"=])(?:\.\./){2,}")
LITERAL = re.compile(r"""(?:"([^"\\\n]{4,})"|'([^'\\\n]{4,})'|\b(\d{3,}(?:\.\d+)?)\b)""")


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


def leaks(log: pathlib.Path, ws: pathlib.Path) -> list[str]:
    """Commands and reads in a transcript that reach past the workspace."""
    found = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict) or part.get("type") != "tool_use":
                continue
            inp = part.get("input") or {}
            command = inp.get("command", "") if part.get("name") == "Bash" else ""
            outside = [p for p in HOME_PATH.findall(command) if not inside(p, ws)]
            if command and (LEAK.search(command) or outside or ESCAPE.search(command)):
                found.append(f"Bash: {command[:200]}")
            for path in tool_paths(part.get("name", ""), inp, ws):
                if not inside(path, ws):
                    found.append(f"{part.get('name')}: {path}")
    return found


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


def inside(path: str, ws: pathlib.Path) -> bool:
    """A path a session may read: its workspace, its run folder, the tools, the elenchus
    copy, and the outputs Claude Code saved for this run's sessions."""
    allowed = (ws, LIVE / "run", TOOLS, WORK / "elenchus", session_store(ws))
    allowed += tuple(a.resolve() for a in allowed)  # the store may sit behind a symlink
    path = os.path.normpath(path)
    return any(path == str(a) or path.startswith(f"{a}/") for a in allowed)


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


def audit(task: dict, ws: pathlib.Path, diff: str, logs: list[pathlib.Path]) -> list[str]:
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
        flags += [f"leak: {x}" for x in leaks(log, ws)]
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


def staged_diff(ws: pathlib.Path) -> bytes:
    """Everything the run changed, as bytes: a file that is not UTF-8 must still apply."""
    sh(["git", "add", "-A"], cwd=ws)
    cmd = ["git", "diff", "--cached", "--binary", base_of(ws)]
    return subprocess.run(cmd, cwd=ws, capture_output=True, check=True).stdout


def hidden_tests(
    task: dict, ws: pathlib.Path, dest: pathlib.Path, require: Sequence[str] | None = None
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
    junit.unlink(missing_ok=True)
    missing = sorted(set(require or ()) - passed)
    return {
        "passed": rc == 0 and not failed and bool(passed) and not missing,
        "exit": rc,
        "tail": tail,
        "tests_run": sorted(passed | failed),
        "missing": missing[:20],
    }


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
    flags = audit(task, ws, diff, logs)
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


def resolve(run: dict) -> bool:
    """The primary metric: hidden tests pass, the judge finds no blocking defect, no flag."""
    v = run["judge_verdict"] or {}
    return bool(
        run["tests"]["passed"]
        and v.get("ok")
        and not v.get("blocking_defect")
        and not v.get("cheated")
        and not run["flags"]
    )


def pass_id(dirs: list[pathlib.Path]) -> str:
    """One judge pass is the set of folders judged together; analyze.py refuses verdicts from
    different passes, so a mode judged on its own is never compared with another."""
    names = sorted(str(d.resolve()) for d in dirs)
    return hashlib.sha256("\n".join(names).encode()).hexdigest()[:12]


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
    and the gold patch raises no cheat flag. Records the test ids the gold patch passes,
    which every run must pass too."""
    bad = 0
    gold_ids = json.loads(GOLD.read_text(encoding="utf-8")) if GOLD.exists() else {}
    for task in tasks:
        base = CHECK / task["id"]
        ws = base / "ws"
        workspace(task, ws)
        before = hidden_tests(task, ws, base / "score-parent")
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
        ok = not before["passed"] and after["passed"] and not flags
        bad += not ok
        if ok:  # a gold pass has no failed test, so every test it ran passed
            gold_ids[task["id"]] = after["tests_run"]
        else:  # a broken task keeps no ids, so no run is scored against stale ones
            gold_ids.pop(task["id"], None)
        print(
            f"{task['id']}: parent {'passes' if before['passed'] else 'fails'}, "
            f"fix {'passes' if after['passed'] else 'fails'}, "
            f"gold flags {flags or 'none'}: {'ok' if ok else 'BROKEN'}",
            flush=True,
        )
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
