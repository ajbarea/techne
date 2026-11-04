"""CPU benchmarks for the parsers the plugin hooks run on every call (techne#277).

CodSpeed runs these in simulation mode (`pytest tests/bench --codspeed` under its action), which
counts instructions and cache misses and leaves system calls out of the measure. So only pure
in-process work is timed here: shell parsing, body counting, command matching, the git guard's
triage. A hook's process start, imports, subprocesses and file reads are wall-clock costs, held
by tests/test_hook_latency.py. Each input is built before the timed call, which changes no state,
and each result is asserted, so a plain `pytest` run (where `benchmark` calls the function once)
checks the same calls.

Every parser gets a typical input and the largest one its caller lets through, where a regex
or loop with superlinear cost would show.
"""

# research(2026-11): simulation mode excludes system calls from the measure
# (https://codspeed.io/docs/instruments/cpu), so process-heavy hooks stay on wall-clock budgets;
# the `benchmark` fixture times only the call passed to it (https://pypi.org/project/pytest-codspeed/).

from __future__ import annotations

import io
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins" / "phylax" / "hooks"))
sys.path.insert(0, str(ROOT / "plugins" / "techne" / "_shared"))

import body_gate  # noqa: E402  # ty: ignore[unresolved-import]
import email_greeting  # noqa: E402  # ty: ignore[unresolved-import]
import git_checks  # noqa: E402  # ty: ignore[unresolved-import]
import git_guards  # noqa: E402  # ty: ignore[unresolved-import]
import git_options  # noqa: E402  # ty: ignore[unresolved-import]
import project_board  # noqa: E402  # ty: ignore[unresolved-import]

FIXTURES = ROOT / "tests" / "fixtures" / "body_gate"
TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"

COMMIT_HEREDOC = (
    "git add -A && git commit -m \"$(cat <<'EOF'\nfeat: x\n\n" + "Body line.\n" * 40 + 'EOF\n)"'
)
TYPICAL_COMMANDS = [
    "git status",
    "cd plugins/phylax && git add hooks/git_checks.py tests/test_git_guards.py",
    COMMIT_HEREDOC,
    "gh pr create --title 'feat: x' --body-file /tmp/body.md --label enhancement",
    "uv run pytest tests/test_git_guards.py -q 2>&1 | tail -3; git diff --stat",
]
# One Bash call carrying many subcommands, the shape a generated script takes.
MANY = 400
LONG_LINE = " && ".join(f"git add file{i}.txt" for i in range(MANY))
# A heredoc body the size of the largest one GitHub accepts.
BIG_HEREDOC = (
    "gh pr create -t x -F - <<'EOF'\nfeat: x\n\n"
    + "word " * (body_gate.GITHUB_MAX // 5 - 20)
    + "\nEOF"
)


def parse(command: str) -> list[list[str]]:
    """The guard's split of a command into subcommands, as check() runs it."""
    stripped, _ = git_checks.strip_heredocs(command)
    tokens = git_checks.tokenize(stripped)
    if tokens is None:
        tokens = git_checks.rough_tokenize(stripped)
    return git_checks.split_subcommands(tokens)


def test_git_command_parse_typical(benchmark):
    groups = benchmark(lambda: [parse(c) for c in TYPICAL_COMMANDS])
    assert [g[0][0] for g in groups] == ["git", "cd", "git", "gh", "uv"]


def test_git_command_parse_many_subcommands(benchmark):
    groups = benchmark(parse, LONG_LINE)
    assert len(groups) == MANY and groups[-1] == ["git", "add", f"file{MANY - 1}.txt"]


def test_git_command_parse_largest_heredoc(benchmark):
    groups = benchmark(parse, BIG_HEREDOC)
    assert groups[0][:3] == ["gh", "pr", "create"]


def test_body_budget_typical_pr(benchmark):
    body = (FIXTURES / "klepsydra-pr-188.md").read_text()
    denies, _ = benchmark(body_gate.check, "PR", body)
    assert denies == []


def test_body_budget_largest_body(benchmark):
    # GitHub refuses a longer body, so this is the most check() is ever handed.
    sentence = "This sentence keeps going so the counter has words to count. "
    body = (sentence * (body_gate.GITHUB_MAX // len(sentence)))[: body_gate.GITHUB_MAX]
    denies, _ = benchmark(body_gate.check, "PR", body)
    assert denies


def test_board_create_match(benchmark):
    commands = [*TYPICAL_COMMANDS, "gh issue create -t x -b y", "gh api -X POST repos/o/r/issues"]
    matched = benchmark(lambda: [project_board.creates_item(c) for c in commands])
    assert matched == [False, False, False, True, False, True, True]


def test_board_create_match_long_line(benchmark):
    assert benchmark(project_board.creates_item, LONG_LINE + " && gh pr create -f") is True


def test_email_greeting_html_body(benchmark):
    html = "<div><p>Good morning,</p>" + "<p>Line of the message.</p>" * 2000 + "</div>"
    lines = benchmark(email_greeting.first_lines, {"html": html, "body": "Good morning,\n\nx"})
    assert lines == ["Good morning,", "Good morning,"]


@pytest.fixture
def guards_on(monkeypatch):
    for key in git_options.OPTIONS:
        monkeypatch.setenv(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", "true")
    monkeypatch.delenv("PHYLAX_GUARD_CHECKED", raising=False)


class _Stdin(io.StringIO):
    """A stdin whose read() returns the same text every call, so each timed call sees the same
    input without resetting anything."""

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def read(self, size: int | None = -1) -> str:
        return self.text


@pytest.mark.parametrize(
    ("command", "description"),
    [("ls -la", "List files"), ("ls -la", "List files in the GitHub checkout")],
    ids=["skipped-unparsed", "skipped-parsed"],
)
def test_git_guard_triage(benchmark, guards_on, monkeypatch, command, description):
    payload = json.dumps(
        {
            "session_id": "0b8f5a2c-6d1e-4f3a-9c7b-2e4d6f8a1b3c",
            "cwd": str(ROOT),
            "tool_name": "Bash",
            "tool_input": {"command": command, "description": description},
        }
    )
    monkeypatch.setattr(sys, "stdin", _Stdin(payload))
    assert benchmark(git_guards.main) == 0
