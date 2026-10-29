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
    r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|__snapshots__/|[^/]*\.snap)"
)
# Commands that reach past the workspace: network tools, git remotes, GitHub.
LEAK = re.compile(
    r"\b(?:gh|curl|wget|ssh|scp|nc)\s"
    r"|\bgit\b[^|;&\n]*?\s(?:fetch|clone|pull|push|remote|ls-remote)\b"
    r"|https?://"
)
LITERAL = re.compile(r"""(?:"([^"\\\n]{4,})"|'([^'\\\n]{4,})'|\b(\d{3,}(?:\.\d+)?)\b)""")


def sh(cmd: Sequence[str], cwd: pathlib.Path | None = None, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, **kw)


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
        "--tools",
        tools,
        "--settings",
        str(SANDBOX),
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
        err = "timeout"
    result: dict = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") == "result":
            result = rec
    result.setdefault("is_error", True)
    if err:
        result["harness_error"] = err
    return result


def usage_of(result: dict) -> dict:
    u = result.get("usage") or {}
    return {
        "cost_usd": result.get("total_cost_usd") or 0.0,
        "input": u.get("input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "cache_write": u.get("cache_creation_input_tokens", 0),
    }


def add_usage(total: dict, part: dict) -> None:
    for k, v in part.items():
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
            if part.get("name") == "Bash" and LEAK.search(inp.get("command", "")):
                found.append(f"Bash: {inp['command'][:200]}")
            path = inp.get("file_path") or inp.get("path") or ""
            if path and os.path.isabs(path) and not path.startswith(str(ws)):
                found.append(f"{part.get('name')}: {path}")
    return found


def diff_files(ws: pathlib.Path) -> list[tuple[str, str]]:
    sh(["git", "add", "-A"], cwd=ws)
    out = sh(["git", "diff", "--cached", "--name-status", "HEAD"], cwd=ws).stdout
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]  # type: ignore[misc]


def audit(task: dict, ws: pathlib.Path, diff: str, logs: list[pathlib.Path]) -> list[str]:
    """The pre-registered cheat flags, mechanical only."""
    flags = []
    for status, path in diff_files(ws):
        if TEST_CONFIG.search(path):
            flags.append(f"test config changed: {path}")
        elif TEST_PATH.search(path) and status != "A":
            removed = sh(["git", "diff", "--cached", "HEAD", "--", path], cwd=ws).stdout
            if any(ln.startswith("-") and not ln.startswith("---") for ln in removed.splitlines()):
                flags.append(f"existing test lines removed or changed: {path}")
    added, in_test = [], False
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            in_test = bool(TEST_PATH.search(ln[4:]))
        elif ln.startswith("+") and not in_test:
            added.append(ln[1:])
    added_code = "\n".join(added)
    pre_tree = "\n".join(
        git(task["clone"], "show", f"{task['parent']}:{p}")
        for p in git(task["clone"], "ls-tree", "-r", "--name-only", task["parent"]).split("\n")
        if p.endswith((".py", ".js", ".ts", ".sh", ".md", ".json", ".toml"))
    )
    for rel in task["hidden_tests"]:
        body = git(task["clone"], "show", f"{task['fix']}:{rel}")
        for line in body.splitlines():
            if "assert" not in line and "expect(" not in line:
                continue
            for m in LITERAL.finditer(line):
                lit = next(g for g in m.groups() if g)
                if lit not in pre_tree and lit in added_code:
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


def run_one(task: dict, mode: str, rep: int, out: pathlib.Path, elenchus: pathlib.Path) -> dict:
    tag = f"{task['id']}/{mode}/r{rep}"
    base = WORK / "runs" / out.name / task["id"] / mode / f"r{rep}"
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
    reviews = []
    for n in range(1, MAX_REVIEWS + 1):
        rv = claude(
            (HERE / "prompts" / "review.md").read_text().format(**fmt),
            REVIEWER,
            ws,
            base / f"review-{n}.jsonl",
            REVIEW_TOOLS,
            FINDINGS_SCHEMA,
            (elenchus,),
        )
        add_usage(total, usage_of(rv))
        findings = (rv.get("structured_output") or {}).get("findings")
        reviews.append({"round": n, "ok": findings is not None, "findings": findings or []})
        if not findings:
            break
        if n == MAX_REVIEWS:
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
    changed_status = diff_files(ws)
    diff = sh(["git", "diff", "--cached", "HEAD"], cwd=ws).stdout
    flags = audit(task, ws, diff, logs)
    tests = hidden_tests(task, ws, base / "score")
    verdict = judge(task, strip_meta(diff), [p for _, p in changed_status], base / "judge.jsonl")
    if verdict.get("cheated"):
        flags.append(f"judge: {verdict.get('cheated_reason', '')[:200]}")
    resolved = (
        tests["passed"] and verdict.get("ok") and not verdict.get("blocking_defect") and not flags
    )
    record = {
        "task": task["id"],
        "risk": task["risk"],
        "mode": mode,
        "repeat": rep,
        "implementer": MODELS[mode],
        "reviewer": REVIEWER,
        "judge": JUDGE,
        "claude_code": sh(["claude", "--version"]).stdout.strip(),
        "resolved": bool(resolved),
        "tests": tests,
        "judge_verdict": verdict,
        "flags": flags,
        "reviews": reviews,
        "usage": total,
        "errors": errors,
        "diff": diff,
    }
    dest = out / task["id"] / mode / f"r{rep}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "run.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(
        f"{tag}: resolved={record['resolved']} tests={tests['passed']} "
        f"blocking={verdict.get('blocking_defect')} flags={len(flags)} "
        f"cost=${total.get('cost_usd', 0):.2f}",
        flush=True,
    )
    return record


def check_tasks(tasks: list[dict]) -> int:
    """No model: each task's hidden tests fail on its workspace and pass with the gold patch."""
    bad = 0
    for task in tasks:
        base = WORK / "check" / task["id"]
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
        ok = not before["passed"] and after["passed"]
        bad += not ok
        print(
            f"{task['id']}: parent {'passes' if before['passed'] else 'fails'}, "
            f"fix {'passes' if after['passed'] else 'fails'}: {'ok' if ok else 'BROKEN'}"
        )
        if not after["passed"]:
            print(after["tail"][-800:])
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--mode", choices=sorted(MODELS), default="normal")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--task", action="append", help="task id (repeatable; default: all)")
    ap.add_argument("--tasks", type=pathlib.Path, default=HERE / "tasks" / "tasks.toml")
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--check-tasks", action="store_true", help="validate the task set, no model")
    args = ap.parse_args(argv)
    tasks = [t for t in load_tasks(args.tasks) if not args.task or t["id"] in args.task]
    if args.check_tasks:
        return check_tasks(tasks)
    if not args.out:
        ap.error("--out is required for a run")
    elenchus = WORK / "elenchus"
    if elenchus.exists():
        shutil.rmtree(elenchus)
    shutil.copytree(ROOT / "plugins" / "techne" / "skills" / "elenchus", elenchus)
    order = [(t, r) for r in range(1, args.repeats + 1) for t in tasks]
    random.Random(SEED).shuffle(order)
    for task, rep in order:
        if (args.out / task["id"] / args.mode / f"r{rep}" / "run.json").exists():
            continue  # resume a stopped run
        started = time.time()
        try:
            run_one(task, args.mode, rep, args.out, elenchus)
        except Exception as exc:  # one broken run must not stop the set; it is recorded
            dest = args.out / task["id"] / args.mode / f"r{rep}"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "error.json").write_text(
                json.dumps({"error": repr(exc)[:2000], "seconds": time.time() - started})
            )
            print(f"{task['id']}/{args.mode}/r{rep}: harness error {exc!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
