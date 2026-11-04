"""Latency budgets for the plugin hooks that run on every tool call, prompt or session (techne#277).

Each case runs a hook through the command its hooks.json registers, as Claude Code runs it
(`sh -c`, the plugin root filled in), on a fixed input, and takes the median of RUNS runs after
WARMUP. The floor, `python3 -c pass` through the same `sh -c`, is timed in the same rounds,
interleaved, so a slower or busier machine moves both. A budget is a ratio to that floor: what
a hook may spend past Python's own startup, derived from the ratios measured in
fixtures/hook_latency/baseline.json (budget()). Noise only ever adds time, so a case over its
budget is measured once more and the lower ratio counts. The floor does not even out every
difference between machines: a hook's ratio differs from one machine to another, up or down case
by case, so the baseline holds the ratios of each machine and python3 measured, and a budget
covers the highest.
After a change that makes a hook deliberately slower or faster, rerun with
TECHNE_LATENCY_RECORD=1 for each entry the baseline lists (TECHNE_GUARD_PYTHON picks the
python3, TECHNE_LATENCY_LABEL names the entry) and commit the new baseline.

Every case runs against a temporary HOME and repository, and the files there must be the same
after the timed runs as after the warm-up, so no timed call changes what the next one sees.
Hooks that change state by design (plugin_keys start/end write session keys, the hygiene
SessionStart hook removes finished worktrees, stale_restart's Stop records the turn) are left out.
"""

# research(2026-11): median over repeated runs, gated on a ratio with a retry, because noise
# only adds time (Chen and Revels, "Robust benchmarking in noisy environments",
# https://math.mit.edu/~edelman/publications/robust_benchmarking.pdf; the median of several
# runs as the gate statistic, https://github.com/GoogleChrome/lighthouse/blob/main/docs/variability.md).

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import pathlib
import re
import shlex
import statistics
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest
from conftest import (
    HOOK_PYTHON,
    LATENCY_LINES,
    hook_env,
    hook_handlers,
    hook_shell,
    load_phylax_hooks,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = pathlib.Path(__file__).resolve().parent / "fixtures" / "hook_latency" / "baseline.json"
# TECHNE_LATENCY_RECORD=1 writes each case's measured ratio into BASELINE instead of checking
# it, under TECHNE_LATENCY_LABEL (default: this python3's version, as "3.14").
RECORD = os.environ.get("TECHNE_LATENCY_RECORD") == "1"
WARMUP = 2
RUNS = 15
SESSION = "0b8f5a2c-6d1e-4f3a-9c7b-2e4d6f8a1b3c"
GUARDS = (
    "block_attribution_trailers",
    "block_commits_md",
    "warn_main_checkout_commit",
    "block_secrets",
    "block_long_bodies",
)


@dataclass(frozen=True)
class Case:
    id: str
    plugin: str
    event: str
    matcher: str | None
    script: str  # a substring that picks the one handler among the event's
    stdin: dict
    on: Mapping[str, str] = field(default_factory=dict)
    # What every run must print on stdout: this text, or nothing when empty. A hook that fails
    # fast (an error caught and printed, a fail-closed exit) must not pass on its speed.
    expect: str = ""


def _bash(command: str, description: str = "List files") -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command, "description": description}}


CASES = [
    # The fallback runs on every Bash call, subagents' included, so the call that names no
    # git is the hot path.
    Case(
        "git_guards-no-git",
        "phylax",
        "PreToolUse",
        "Bash",
        "git_guards.py",
        _bash("ls -la"),
        dict.fromkeys(GUARDS, "true"),
    ),
    # A payload that says git or gh anywhere (here the description) is parsed before the
    # command is read.
    Case(
        "git_guards-no-git-described",
        "phylax",
        "PreToolUse",
        "Bash",
        "git_guards.py",
        _bash("ls -la", "List the .github workflows"),
        dict.fromkeys(GUARDS, "true"),
    ),
    Case(
        "git_guards-git-status",
        "phylax",
        "PreToolUse",
        "Bash",
        "git_guards.py",
        _bash("git status"),
        dict.fromkeys(GUARDS, "true"),
    ),
    Case(
        "git_guards-gh-view",
        "phylax",
        "PreToolUse",
        "Bash",
        "git_guards.py",
        _bash("gh pr view 3 --json title"),
        dict.fromkeys(GUARDS, "true"),
    ),
    Case(
        "model_guard-agent",
        "phylax",
        "PreToolUse",
        "Agent|Task",
        "model_guard.py",
        {"tool_name": "Agent", "tool_input": {"subagent_type": "general-purpose", "prompt": "x"}},
        {"require_subagent_model": "true"},
        '"permissionDecision": "deny"',
    ),
    Case(
        "budget-agent",
        "phylax",
        "PreToolUse",
        "Agent|Task",
        "budget.py",
        {"tool_name": "Agent", "tool_input": {"subagent_type": "Explore", "prompt": "x"}},
        {"budget_mode": "true"},
    ),
    Case(
        "budget-prompt",
        "phylax",
        "UserPromptSubmit",
        None,
        "budget.py",
        {"hook_event_name": "UserPromptSubmit", "prompt": "hello"},
        {"budget_mode": "true"},
    ),
    Case(
        "stale_restart-prompt",
        "phylax",
        "UserPromptSubmit",
        None,
        "stale_restart.py",
        {"hook_event_name": "UserPromptSubmit", "prompt": "hello"},
        {"restart_on_update": "true"},
    ),
    Case(
        "email_greeting-draft",
        "phylax",
        "PreToolUse",
        None,
        "email_greeting.py",
        {
            "tool_name": "mcp__plugin_epistole_epistole__create_draft",
            "tool_input": {"to": "a@example.com", "subject": "x", "body": "Hi,\n\nx"},
        },
        {"email_greeting": "true"},
        '"permissionDecision": "deny"',
    ),
    Case(
        "board_add-bash",
        "techne",
        "PostToolUse",
        "Bash",
        "board_add.py",
        {**_bash("ls -la"), "tool_response": {"stdout": "x", "stderr": ""}},
    ),
    Case(
        "resume_brief-start",
        "techne",
        "SessionStart",
        None,
        "resume_brief.py",
        {"hook_event_name": "SessionStart", "source": "startup"},
        {"resume_brief": "true"},
        '"additionalContext"',
    ),
]


def budget(case_id: str, baseline: Mapping | None = None) -> float:
    """The most CASE_ID's median may be, as a multiple of the floor's: the baseline's headroom
    times the highest ratio it holds for the case on any machine and python3, rounded up to a
    tenth."""
    data = baseline or json.loads(BASELINE.read_text())
    highest = max(by_case[case_id] for by_case in data["ratios"].values())
    return math.ceil(round(data["headroom"] * highest * 10, 6)) / 10


def _handler(case: Case) -> dict:
    handlers = [
        h
        for h in hook_handlers(case.plugin, case.event, case.matcher)
        if case.script in h["command"]
    ]
    assert len(handlers) == 1, f"{case.id}: {len(handlers)} handlers name {case.script}"
    return handlers[0]


def command(case: Case, root: pathlib.Path = ROOT, python: str = HOOK_PYTHON) -> str:
    """CASE's registered command with ROOT's plugin folder filled in and `exec python3` run on
    PYTHON."""
    handler = _handler(case)
    assert "exec python3 " in handler["command"], f"{case.id}: the command never starts python3"
    return hook_shell(case.plugin, handler, python, root)


def floor_command(python: str = HOOK_PYTHON) -> str:
    return f"exec {shlex.quote(python)} -c pass"


def _snapshot(*roots: pathlib.Path) -> dict[str, str]:
    """Every file under ROOTS, by path, with a hash of its bytes (a rewrite with the same
    bytes is no change; an append is)."""
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for r in roots
        for p in sorted(r.rglob("*"))
        if p.is_file()
    }


def time_rounds(
    shells: list[tuple[str, str]],
    stdin: str,
    env: Mapping[str, str],
    cwd: pathlib.Path,
    runs: int,
) -> list[list[float]]:
    """Wall times in ms of each of SHELLS, RUNS rounds, one run of each per round. Each shell
    comes with what it must print on stdout (nothing when empty), and must exit 0 with nothing
    on stderr."""
    times: list[list[float]] = [[] for _ in shells]
    for _ in range(runs):
        for i, (shell, expect) in enumerate(shells):
            start = time.perf_counter()
            proc = subprocess.run(
                ["sh", "-c", shell],
                input=stdin,
                capture_output=True,
                text=True,
                env=dict(env),
                cwd=cwd,
                timeout=30,
            )
            times[i].append((time.perf_counter() - start) * 1000)
            assert (proc.returncode, proc.stderr) == (0, ""), (shell, proc.returncode, proc.stderr)
            assert (expect in proc.stdout) if expect else not proc.stdout, (shell, proc.stdout)
    return times


def make_sandbox(home: pathlib.Path, repo: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Fill the empty folders HOME and REPO: a HOME with no configuration and a repository with
    one commit and an IMPL.md. bench/run.py times the same cases in the same sandbox."""
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True, env=env)
    (repo / "IMPL.md").write_text("# Impl\n\nNext: measure.\n")
    (repo / "a.txt").write_text("a\n")
    subprocess.run([*git, "add", "-A"], check=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True, env=env)
    return home, repo


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory) -> tuple[pathlib.Path, pathlib.Path]:
    return make_sandbox(tmp_path_factory.mktemp("home"), tmp_path_factory.mktemp("repo"))


def no_git_input_can_skip(repo: pathlib.Path) -> bool:
    """Whether the git guard's own triage skips the no-git case's input unparsed in REPO. Every
    input carries the temporary folders' paths, and one that says git or gh (a user named hugh, a
    TMPDIR under ~/github) or needs a JSON escape (a non-ASCII letter) is parsed, so that case
    would time the other path. bench/run.py refuses such a sandbox too."""
    path = ROOT / "plugins" / "phylax" / "hooks" / "git_guards.py"
    spec = importlib.util.spec_from_file_location("_git_guards_triage", path)
    assert spec and spec.loader
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    no_git = next(c for c in CASES if c.id == "git_guards-no-git")
    return entry.cannot_name_git(case_stdin(no_git, repo))


def skip_unless_no_git_can_skip(sandbox: tuple[pathlib.Path, pathlib.Path]) -> None:
    if not no_git_input_can_skip(sandbox[1]):
        pytest.skip(f"the temporary folders' paths could name git: {sandbox[1]}")


def case_env(case: Case, home: pathlib.Path) -> dict[str, str]:
    return hook_env(
        on=case.on,
        drop=("PHYLAX_", "PYTHONDONTWRITEBYTECODE", "XDG_", "CLAUDE_"),
        HOME=str(home),
        XDG_STATE_HOME=str(home / ".local" / "state"),
        XDG_CACHE_HOME=str(home / ".cache"),
        XDG_CONFIG_HOME=str(home / ".config"),
        CLAUDE_CONFIG_DIR=str(home / ".claude"),
        CLAUDE_PLUGIN_DATA=str(home / "plugin-data"),
    )


def case_stdin(case: Case, repo: pathlib.Path) -> str:
    return json.dumps(
        {
            "session_id": SESSION,
            "transcript_path": str(repo / "t.jsonl"),
            "cwd": str(repo),
            "tool_use_id": "toolu_latency",
            **case.stdin,
        }
    )


def _python_version() -> str:
    out = subprocess.run(
        [HOOK_PYTHON, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _record(case_id: str, ratio: float) -> None:
    data = json.loads(BASELINE.read_text())
    label = os.environ.get("TECHNE_LATENCY_LABEL") or _python_version()
    data["ratios"].setdefault(label, {})[case_id] = round(ratio, 2)
    BASELINE.write_text(json.dumps(data, indent=2) + "\n")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_hook_stays_within_its_latency_budget(case, sandbox, request):
    home, repo = sandbox
    if case.id == "git_guards-no-git":
        skip_unless_no_git_can_skip(sandbox)
    env, stdin = case_env(case, home), case_stdin(case, repo)
    shells = [(floor_command(), ""), (command(case), case.expect)]
    time_rounds(shells, stdin, env, repo, WARMUP)
    before = _snapshot(home, repo)
    floor, hook = (statistics.median(t) for t in time_rounds(shells, stdin, env, repo, RUNS))
    limit = None if RECORD else budget(case.id)
    if limit is not None and hook > limit * floor:
        again = time_rounds(shells, stdin, env, repo, RUNS)
        floor, hook = min(
            ((statistics.median(again[0]), statistics.median(again[1])), (floor, hook)),
            key=lambda pair: pair[1] / pair[0],
        )
    assert _snapshot(home, repo) == before, f"{case.id}: a timed run changed files"
    ratio = hook / floor
    line = f"{case.id}: {hook:.1f} ms, floor {floor:.1f} ms, {ratio:.2f}x (budget {limit}x)"
    request.config.stash.setdefault(LATENCY_LINES, []).append(line)
    if limit is None:
        _record(case.id, ratio)
        return
    assert ratio <= limit, (
        f"{case.id}: median {hook:.1f} ms is {ratio:.2f}x the {floor:.1f} ms python3 floor, "
        f"over its {limit}x budget"
    )


@pytest.mark.parametrize(
    ("ratios", "expected"),
    [({"a": {"x": 1.0}}, 1.3), ({"a": {"x": 1.2}, "b": {"x": 2.0}}, 2.5), ({"a": {"x": 2.0}}, 2.5)],
)
def test_a_budget_is_the_headroom_over_the_highest_ratio_rounded_up(ratios, expected):
    assert budget("x", {"headroom": 1.25, "ratios": ratios}) == expected


def test_every_case_has_a_baseline_in_every_entry():
    ratios = json.loads(BASELINE.read_text())["ratios"]
    for version, by_case in ratios.items():
        assert set(by_case) == {c.id for c in CASES}, version


def test_the_git_guard_cases_reach_the_path_they_time(sandbox, monkeypatch):
    # git_guards.cannot_name_git is case-sensitive: "GitHub" would keep the described case on the
    # unparsed skip it is meant to differ from.
    skip_unless_no_git_can_skip(sandbox)
    (entry,) = load_phylax_hooks(monkeypatch, "git_guards")
    skips = {
        c.id: entry.cannot_name_git(case_stdin(c, sandbox[1]))
        for c in CASES
        if c.script == "git_guards.py"
    }
    assert skips == {
        "git_guards-no-git": True,
        "git_guards-no-git-described": False,
        "git_guards-git-status": False,
        "git_guards-gh-view": False,
    }


def test_every_case_runs_a_registered_handler():
    # A renamed script or matcher must fail here, not time a command that no longer exists.
    for case in CASES:
        scripts = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"\s]+\.py)", _handler(case)["command"])
        assert len(scripts) == 1, f"{case.id}: {scripts}"
        script = ROOT / "plugins" / case.plugin / scripts[0]
        assert script.is_file(), f"{case.id}: {script} is missing"
