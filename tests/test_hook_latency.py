"""Latency budgets for the plugin hooks that run on every tool call, prompt or session (techne#277).

Each case runs a hook through the command its hooks.json registers, as Claude Code runs it
(`sh -c`, the plugin root filled in), on a fixed input, and takes the median of RUNS runs after
WARMUP. The floor, `python3 -c pass` through the same `sh -c`, is timed in the same rounds,
interleaved, so a slower or busier machine moves both. A budget is a ratio to that floor: what
a hook may spend past Python's own startup, derived from the ratios measured in
fixtures/hook_latency/baseline.json (budget()). Noise only ever adds time, so a case over its
budget is measured once more and the lower ratio counts. After a change that makes a hook
deliberately slower or faster, rerun with TECHNE_LATENCY_RECORD=1 on each python3 the baseline
lists (TECHNE_GUARD_PYTHON picks it) and commit the new baseline.

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
from conftest import HOOK_PYTHON, hook_env, hook_handlers

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = pathlib.Path(__file__).resolve().parent / "fixtures" / "hook_latency" / "baseline.json"
# TECHNE_LATENCY_RECORD=1 writes each case's measured ratio into BASELINE under this python3's
# version instead of checking it, to set the budgets again after a deliberate change.
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


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


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
            "tool_input": {"to": "a@example.com", "subject": "x", "body": "Good morning,\n\nx"},
        },
        {"email_greeting": "true"},
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
    ),
]


def budget(case_id: str, baseline: Mapping | None = None) -> float:
    """The most CASE_ID's median may be, as a multiple of the floor's: the baseline's headroom
    times the highest ratio it holds for the case on any python3, rounded up to a tenth. A
    faster-starting python3 has a lower floor, so its ratios run higher."""
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
    shell = _handler(case)["command"].replace(
        "${CLAUDE_PLUGIN_ROOT}", str(root / "plugins" / case.plugin)
    )
    assert "exec python3 " in shell, f"{case.id}: the command never starts python3"
    return shell.replace("exec python3 ", f"exec {shlex.quote(python)} ")


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
    shells: list[str], stdin: str, env: Mapping[str, str], cwd: pathlib.Path, runs: int
) -> list[list[float]]:
    """Wall times in ms of each of SHELLS, RUNS rounds, one run of each per round."""
    times: list[list[float]] = [[] for _ in shells]
    for _ in range(runs):
        for i, shell in enumerate(shells):
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
            assert "Traceback" not in proc.stderr, proc.stderr
    return times


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory) -> tuple[pathlib.Path, pathlib.Path]:
    """A HOME with no configuration and a repository with one commit and an IMPL.md."""
    home = tmp_path_factory.mktemp("home")
    repo = tmp_path_factory.mktemp("repo")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True, env=env)
    (repo / "IMPL.md").write_text("# Impl\n\nNext: measure.\n")
    (repo / "a.txt").write_text("a\n")
    subprocess.run([*git, "add", "-A"], check=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True, env=env)
    return home, repo


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
    data["ratios"].setdefault(_python_version(), {})[case_id] = round(ratio, 2)
    BASELINE.write_text(json.dumps(data, indent=2) + "\n")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_hook_stays_within_its_latency_budget(case, sandbox):
    home, repo = sandbox
    env, stdin = case_env(case, home), case_stdin(case, repo)
    shells = [floor_command(), command(case)]
    limit = budget(case.id)
    time_rounds(shells, stdin, env, repo, WARMUP)
    before = _snapshot(home, repo)
    floor, hook = (statistics.median(t) for t in time_rounds(shells, stdin, env, repo, RUNS))
    if hook > limit * floor and not RECORD:
        again = time_rounds(shells, stdin, env, repo, RUNS)
        floor, hook = min(
            ((statistics.median(again[0]), statistics.median(again[1])), (floor, hook)),
            key=lambda pair: pair[1] / pair[0],
        )
    assert _snapshot(home, repo) == before, f"{case.id}: a timed run changed files"
    ratio = hook / floor
    print(f"{case.id}: {hook:.1f} ms, floor {floor:.1f} ms, {ratio:.2f}x (budget {limit}x)")
    if RECORD:
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


def test_every_case_has_a_baseline_on_every_python():
    ratios = json.loads(BASELINE.read_text())["ratios"]
    for version, by_case in ratios.items():
        assert set(by_case) == {c.id for c in CASES}, version


def test_every_case_runs_a_registered_handler():
    # A renamed script or matcher must fail here, not time a command that no longer exists.
    for case in CASES:
        scripts = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"\s]+\.py)", _handler(case)["command"])
        assert len(scripts) == 1, f"{case.id}: {scripts}"
        script = ROOT / "plugins" / case.plugin / scripts[0]
        assert script.is_file(), f"{case.id}: {script} is missing"
