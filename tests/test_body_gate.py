"""Tests for phylax's body budget (body_gate.py) and its guard in git_guards.py (techne#229).

The counting is checked against graphe's length_budget.markdown_words, whose rule it
mirrors; the guard is fed PreToolUse JSON for each way gh writes a body.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest
from conftest import HOOK_PYTHON, hook_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "phylax" / "hooks"
GUARDS = HOOKS / "git_guards.py"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "body_gate"
BODIES = "block_long_bodies"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


body_gate = _load("phylax_body_gate", HOOKS / "body_gate.py")
sys.path.insert(0, str(ROOT / "plugins" / "graphe" / "_shared"))
length_budget = _load(
    "graphe_length_budget", ROOT / "plugins" / "graphe" / "_shared" / "length_budget.py"
)


def words_of(n: int, sentence: int = 12) -> str:
    """N words in sentences of SENTENCE words."""
    out, line = [], []
    for i in range(n):
        line.append(f"word{i}")
        if len(line) == sentence:
            out.append(" ".join(line) + ".")
            line = []
    if line:
        out.append(" ".join(line) + ".")
    return " ".join(out)


PROSE_CASES = [
    "Plain words, and a [link](https://example.com/very/long/path) with `code`.",
    "| What | Result |\n|---|---|\n| tests | 34 passed |\n\n- a bullet\n- **bold** item",
    "Text\n\n```bash\nmake test && echo done\n```\n\nafter <!-- hidden note --> it.",
    "## Heading\n\nA line with 3 numbers, 4.5% and v1.2.3.",
]


@pytest.mark.parametrize("text", PROSE_CASES)
def test_counts_words_as_graphe_counts_a_markdown_page(text):
    assert body_gate.visible_words(text) == length_budget.markdown_words(text)


def test_details_comments_and_code_are_not_visible():
    body = (
        "Short top.\n\n<details><summary>Details</summary>\n\n"
        + words_of(500)
        + "\n<details>\nnested "
        + words_of(50)
        + "\n</details>\n</details>\n\nAfter. <!-- a note "
        + words_of(40)
        + " -->"
    )
    assert body_gate.visible_words(body) == 3
    assert body_gate.visible_words("Top.\n<details>\n" + words_of(300)) == 1, (
        "unclosed hides the rest"
    )


def test_pr_issue_and_comment_budgets_allow_about_a_tenth_more():
    for kind, budget in (("PR", 150), ("issue", 300), ("comment", 150)):
        assert body_gate.check(kind, words_of(int(budget * 1.1)))[0] == [], kind
        denies, _ = body_gate.check(kind, words_of(int(budget * 1.1) + 1))
        assert denies and f"budget is about {budget}" in denies[0], kind


def test_a_budget_marker_is_refused_even_under_budget():
    for body in ("Fine.\n<!-- budget: 150 words -->", "Fine.\n% budget: 2 pages"):
        denies, _ = body_gate.check("PR", body)
        assert any("budget:` marker" in d for d in denies)


def test_long_sentences_warn_without_refusing_and_tables_are_not_sentences():
    long = words_of(30, sentence=30)
    denies, warnings = body_gate.check("PR", long)
    assert denies == [] and warnings and "1 sentence(s)" in warnings[0]
    row = "| " + " ".join(f"w{i}" for i in range(40)) + " |"
    assert body_gate.long_sentences(row) == []


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.md")))
def test_real_bodies_written_to_the_rule_pass(name):
    assert body_gate.check("PR", (FIXTURES / name).read_text())[0] == []


def run_guard(command: str, cwd: pathlib.Path, on=(BODIES,)) -> dict | None:
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env(on),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def refused(out: dict | None) -> str | None:
    if out and out["hookSpecificOutput"].get("permissionDecision") == "deny":
        return out["hookSpecificOutput"]["permissionDecisionReason"]
    return None


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


LONG = words_of(200)
FOLDED = f"<details><summary>More</summary>\n\n{words_of(900)}\n</details>"
SHORT = words_of(100)


@pytest.mark.parametrize(
    "command",
    [
        f"gh pr create --title t --body '{LONG}'",
        f"gh pr create -t t -b '{LONG}'",
        f"gh pr edit 7 --body='{LONG}'",
        f"gh pr create --title t --body \"$(cat <<'EOF'\n{LONG}\nEOF\n)\"",
        f"gh pr create --title t --body-file - <<'EOF'\n{LONG}\nEOF",
        f"gh pr comment 7 --body '{LONG}'",
        f"gh issue comment 7 -b '{LONG}'",
        f"gh pr review 7 --comment --body '{LONG}'",
        f"gh issue create --title t --body '{words_of(400)}'",
        f"gh -R o/r issue edit 3 --body '{words_of(400)}'",
        f"gh api -X PATCH repos/o/r/pulls/9 -f body='{LONG}'",
        f"gh api repos/o/r/issues/9/comments -f body='{LONG}'",
        f"gh api --method PATCH /repos/o/r/issues/9 --raw-field body='{words_of(400)}'",
    ],
)
def test_each_way_gh_writes_an_overlong_body_is_refused(repo, command):
    assert "visible words" in (refused(run_guard(command, repo)) or "")


def test_body_files_are_read(repo):
    (repo / "long.md").write_text(LONG)
    (repo / "short.md").write_text(SHORT)
    (repo / "in.json").write_text(json.dumps({"body": LONG}))
    assert refused(run_guard("gh pr create -t t --body-file long.md", repo))
    assert refused(run_guard("gh pr create -t t -F long.md", repo))
    assert refused(run_guard("gh api -X PATCH repos/o/r/pulls/1 -F body=@long.md", repo))
    assert refused(run_guard("gh api -X PATCH repos/o/r/pulls/1 --input in.json", repo))
    assert run_guard("gh pr create -t t --body-file short.md", repo) is None


@pytest.mark.parametrize(
    "command",
    [
        f"gh pr create --title t --body '{SHORT}'",
        f"gh pr create --title t --body 'Top.\n\n{FOLDED}'",
        f"gh issue create --title t --body '{words_of(300)}'",
        "gh pr edit 7 --title 'a new title only'",
        f"gh pr view 7 --json body --jq '.body' # {LONG}",
        f"gh api repos/o/r/pulls/9 --jq .body # {LONG}",
        f"gh api graphql -f query='mutation {{ x }}' -f body='{LONG}'",
        "gh pr create --title t --body-file -",
    ],
)
def test_a_body_within_budget_or_no_body_passes(repo, command):
    assert refused(run_guard(command, repo)) is None


def test_off_by_default_and_off_per_repo(repo):
    command = f"gh pr create --title t --body '{LONG}'"
    assert run_guard(command, repo, on=()) is None
    subprocess.run(
        ["git", "-C", str(repo), "config", "phylax.blockLongBodies", "false"], check=True
    )
    assert run_guard(command, repo) is None
