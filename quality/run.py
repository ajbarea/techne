"""Run the budget-mode quality trial's tasks in one mode, as PREREGISTRATION.md fixes them.

Each task run: build a history-free workspace at the fix PR's parent, implement with the
mode's model, review with Opus (up to three reviews, a fix session between them), then score
outside any agent session: the hidden tests, the cheat audit and the blind judge. Agent
sessions are `claude -p --restricted` with Bash sandboxed (quality/sandbox.json): no network,
no reads of the source clones or Claude's config.

    uv run python quality/run.py --mode normal --repeats 3 --out quality/results/<name>

Transcripts and workspaces stay under ~/.cache/techne-quality; the results folder gets one
`run.json` per task run (scores, usage, flags, judge verdict, diff) that analyze.py reads.
"""

from __future__ import annotations

import argparse
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

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SANDBOX = HERE / "sandbox.json"
CACHE = pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache"))
WORK = CACHE / "techne-quality"
# Only the run in progress lives in LIVE; finished runs, score copies and task checks sit in
# folders quality/sandbox.json denies to every agent's shell, so no run reads another's
# answer or a restored hidden test.
LIVE, DONE, SCORE, CHECK = (WORK / d for d in ("live", "done", "score", "check"))
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
# Commands that reach past the workspace: network tools, git remotes, GitHub.
LEAK = re.compile(
    r"\b(?:gh|curl|wget|ssh|scp|nc)\s"
    r"|\bgit\b[^|;&\n]*?\s(?:fetch|clone|pull|push|remote|ls-remote)\b"
    r"|https?://"
)
# A home-folder path in a shell command, and a climb out of the workspace.
HOME_PATH = re.compile(
    r"(?:~|\$HOME|(?<![\w.])/(?:home/[^/\s'\"]+|tmp|mnt|var/tmp|root))(?:/[^\s'\";|&)]*)?"
)
ESCAPE = re.compile(r"(?:^|[\s'\"=])(?:\.\./){2,}")
# Home folders a test run may read: uv's interpreters and cache.
TOOL_DIRS = (".cache/uv", ".local/share/uv", ".local/bin")
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
            out = sh(["bash", "-c", task["setup"]], cwd=dest, timeout=TEST_TIMEOUT)
        if out.returncode:
            raise RuntimeError(f"setup failed: {out.stderr[-500:]}")


class lock:
    """The fleet's heavy-job lock, held around test runs and environment setup."""

    def __enter__(self):
        import fcntl

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
    """The plan's usage or rate limit: the whole run stops, to resume later."""


LIMIT = re.compile(r"usage limit|rate limit|\b429\b|overloaded|credit balance", re.I)


def settings_file() -> pathlib.Path:
    """quality/sandbox.json with TMPDIR set to the live run's own temp folder, since the
    sandbox denies /tmp (other sessions' scratch can hold a task's fixed code)."""
    tmp = LIVE / "run" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    data = json.loads(SANDBOX.read_text(encoding="utf-8"))
    data["env"] = {"TMPDIR": str(tmp)}
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
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") == "result":
            result = rec
    result.setdefault("is_error", True)
    if err and err != "timeout":
        text = err + json.dumps(result)[-500:]
        raise (UsageLimit if LIMIT.search(text) else HarnessError)(text[-800:])
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
        for part in (rec.get("message") or {}).get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "tool_use":
                continue
            inp = part.get("input") or {}
            command = inp.get("command", "") if part.get("name") == "Bash" else ""
            outside = [p for p in HOME_PATH.findall(command) if not inside(p, ws)]
            if command and (LEAK.search(command) or outside or ESCAPE.search(command)):
                found.append(f"Bash: {command[:200]}")
            path = inp.get("file_path") or inp.get("path") or ""
            if path and os.path.isabs(path) and not inside(path, ws):
                found.append(f"{part.get('name')}: {path}")
    return found


def inside(match: str, ws: pathlib.Path) -> bool:
    """A home-folder path from a command is inside the workspace or a tool folder."""
    home = str(pathlib.Path.home())
    path = re.sub(r"^(?:~|\$HOME|/home/[^/]+)", home, match)
    allowed = (str(ws), str(LIVE / "run" / "tmp"), str(WORK / "elenchus"))
    return path.startswith(allowed) or any(path.startswith(f"{home}/{d}") for d in TOOL_DIRS)


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
CONFIG_WEAKENING = re.compile(r"--deselect|--ignore|\s-k\s|collect_ignore|norecursedirs|skip|xfail")


def audit(task: dict, ws: pathlib.Path, diff: str, logs: list[pathlib.Path]) -> list[str]:
    """The pre-registered cheat flags, mechanical only."""
    flags = []
    for status, path in diff_files(ws):
        body = sh(["git", "diff", "--cached", base_of(ws), "--", path], cwd=ws).stdout.splitlines()
        removed = [ln[1:] for ln in body if ln.startswith("-") and not ln.startswith("---")]
        added = [ln[1:] for ln in body if ln.startswith("+") and not ln.startswith("+++")]
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


def hidden_tests(task: dict, ws: pathlib.Path, dest: pathlib.Path) -> dict:
    """Restore the fix's test files over a copy of the final tree and run the test command."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ws, dest, symlinks=True)
    for rel in task["hidden_tests"]:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(git(task["clone"], "show", f"{task['fix']}:{rel}"), encoding="utf-8")
    cmd = f"ip link set lo up; {task['hidden_command']}"
    with lock():
        try:
            out = sh(["unshare", "-rn", "bash", "-c", cmd], cwd=dest, timeout=TEST_TIMEOUT)
            rc, tail = out.returncode, (out.stdout + out.stderr)[-2000:]
        except subprocess.TimeoutExpired:
            rc, tail = 124, "timeout"
    return {"passed": rc == 0, "exit": rc, "tail": tail}


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
    empty = log.parent / "judge-empty"
    empty.mkdir(parents=True, exist_ok=True)
    result = claude(prompt, JUDGE, empty, log, "", schema=JUDGE_SCHEMA)
    verdict = result.get("structured_output") or {}
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


def run_one(task: dict, mode: str, rep: int, out: pathlib.Path, elenchus: pathlib.Path) -> dict:
    """Implement, review and fix, then score with the hidden tests and the cheat audit.

    The blind judge runs later, over every mode's runs at once (`--judge`).
    """
    tag = f"{task['id']}/{mode}/r{rep}"
    base = LIVE / "run"
    if base.exists():
        shutil.rmtree(base)
    ws, logs = base / "ws", []
    workspace(task, ws)
    fmt = {
        "report": task["report"].strip(),
        "test_command": task["test_command"],
        "elenchus_dir": str(elenchus),
    }
    total: dict = {}
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
    tests = hidden_tests(task, ws, score)
    shutil.rmtree(score, ignore_errors=True)
    record = {
        "task": task["id"],
        "risk": task["risk"],
        "mode": mode,
        "repeat": rep,
        "implementer": MODELS[mode],
        "reviewer": REVIEWER,
        "judge": JUDGE,
        "claude_code": sh(["claude", "--version"]).stdout.strip(),
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


def judge_all(dirs: list[pathlib.Path], tasks: list[dict], again: bool) -> int:
    """The blind judge over every run in DIRS, all modes interleaved in one seeded order."""
    by_id = {t["id"]: t for t in tasks}
    paths = sorted(p for d in dirs for p in d.rglob("run.json"))
    random.Random(SEED).shuffle(paths)
    for path in paths:
        run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("judge_verdict") is not None and not again:
            continue
        task = by_id[run["task"]]
        folder = path.parents[3].name
        log = WORK / "judge" / folder / f"{run['task']}-{run['mode']}-r{run['repeat']}.jsonl"
        verdict: dict = {}
        if run.get("diff"):
            for _ in (1, 2):
                verdict = judge(task, strip_meta(run["diff"]), run.get("changed", []), log)
                if verdict["ok"]:
                    break
        run["judge_verdict"] = verdict or {"ok": False, "reason": "no diff to judge"}
        if run["judge_verdict"].get("cheated"):
            reason = run["judge_verdict"].get("cheated_reason", "")[:200]
            run["flags"] = sorted({*run["flags"], f"judge: {reason}"})
        run["resolved"] = resolve(run)
        path.write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
        print(f"judged {path.parent}: resolved={run['resolved']}", flush=True)
    return 0


def failed_run(task: dict, mode: str, rep: int, errors: list[str]) -> dict:
    """A run the harness could not finish in ATTEMPTS tries: unresolved, and reported."""
    return {
        "task": task["id"],
        "risk": task["risk"],
        "mode": mode,
        "repeat": rep,
        "implementer": MODELS[mode],
        "reviewer": REVIEWER,
        "judge": JUDGE,
        "resolved": False,
        "harness_failed": True,
        "tests": {"passed": False, "exit": None, "tail": ""},
        "judge_verdict": {"ok": False},
        "flags": [],
        "notes": ["the harness failed 3 times"],
        "reviews": [],
        "usage": {"cost_known": False},
        "errors": errors,
        "changed": [],
        "diff": "",
    }


ATTEMPTS = 3


def check_tasks(tasks: list[dict]) -> int:
    """No model: each task's hidden tests fail on its workspace and pass with the gold patch,
    and the gold patch raises no cheat flag."""
    bad = 0
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
        print(
            f"{task['id']}: parent {'passes' if before['passed'] else 'fails'}, "
            f"fix {'passes' if after['passed'] else 'fails'}, "
            f"gold flags {flags or 'none'}: {'ok' if ok else 'BROKEN'}",
            flush=True,
        )
        if not after["passed"]:
            print(after["tail"][-800:])
        shutil.rmtree(base, ignore_errors=True)
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--mode", choices=sorted(MODELS), default="normal")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--task", action="append", help="task id (repeatable; default: all)")
    ap.add_argument("--tasks", type=pathlib.Path, default=HERE / "tasks" / "tasks.toml")
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--check-tasks", action="store_true", help="validate the task set, no model")
    ap.add_argument(
        "--judge", type=pathlib.Path, nargs="+", help="judge every run in these folders"
    )
    ap.add_argument("--rejudge", action="store_true", help="with --judge, judge judged runs again")
    args = ap.parse_args(argv)
    tasks = [t for t in load_tasks(args.tasks) if not args.task or t["id"] in args.task]
    if args.check_tasks:
        return check_tasks(tasks)
    if args.judge:
        return judge_all(args.judge, load_tasks(args.tasks), args.rejudge)
    if not args.out:
        ap.error("--out is required for a run")
    elenchus = WORK / "elenchus"
    if elenchus.exists():
        shutil.rmtree(elenchus)
    shutil.copytree(ROOT / "plugins" / "techne" / "skills" / "elenchus", elenchus)
    order = [(t, r) for r in range(1, args.repeats + 1) for t in tasks]
    random.Random(SEED).shuffle(order)
    for task, rep in order:
        dest = args.out / task["id"] / args.mode / f"r{rep}"
        if (dest / "run.json").exists():
            continue  # resume a stopped run
        errfile = dest / "errors.json"
        errors = json.loads(errfile.read_text()) if errfile.exists() else []
        while len(errors) < ATTEMPTS:
            started = time.time()
            try:
                run_one(task, args.mode, rep, args.out, elenchus)
                break
            except UsageLimit as exc:  # the plan's limit: stop, and resume the set later
                print(f"usage limit; rerun the same command to resume: {exc}", file=sys.stderr)
                return 3
            except Exception as exc:  # recorded, retried, then counted as unresolved
                errors.append({"error": repr(exc)[:2000], "seconds": time.time() - started})
                dest.mkdir(parents=True, exist_ok=True)
                errfile.write_text(json.dumps(errors, indent=1))
                print(f"{task['id']}/{args.mode}/r{rep}: harness error {exc!r}", file=sys.stderr)
        else:
            record = failed_run(task, args.mode, rep, [e["error"] for e in errors])
            (dest / "run.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
