"""techne's board hook: each issue or PR a gh command opens goes on the configured board.

The failures that matter: a gh call on a command that opened nothing, an item filed under the
wrong Status, a foreign repo's item on the board, a failure that blocks or fails the tool call,
and a hook that acts without a [board] table. `make test-hooks-oldest` runs this file with the
hook on python3 3.9. gh is a stub on PATH (tests/fixtures/gh_stub.py).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import BOARD_TOML, HOOK_PYTHON, ROOT, GhStub, board_rules

PLUGIN = ROOT / "plugins" / "techne"
HOOK = PLUGIN / "hooks" / "board_add.py"
SCOPE_ERR = (
    "error: your authentication token is missing required scopes [project]\n"
    "To request it, run:  gh auth refresh -s project\n"
)


def run_hook(stub: GhStub, command: str, stdout: str) -> subprocess.CompletedProcess:
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout, "stderr": "", "interrupted": False, "isImage": False},
    }
    return subprocess.run(
        [HOOK_PYTHON, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=stub.env,
        timeout=60,
    )


def edits(stub: GhStub) -> list[tuple[str, str]]:
    """(item id, option id) for each item-edit call."""
    out = []
    for argv in stub.argvs():
        if argv[:2] == ["project", "item-edit"]:
            out.append(
                (argv[argv.index("--id") + 1], argv[argv.index("--single-select-option-id") + 1])
            )
    return out


@pytest.fixture
def board(gh_stub: GhStub) -> GhStub:
    gh_stub.config(BOARD_TOML)
    gh_stub.rules(board_rules())
    return gh_stub


def test_issue_url_goes_on_as_issue(board: GhStub):
    url = "https://github.com/ajbarea/techne/issues/5"
    proc = run_hook(board, "gh issue create --title t --body b", url + "\n")
    assert proc.returncode == 0 and proc.stdout == "", proc.stderr
    add = [a for a in board.argvs() if a[:2] == ["project", "item-add"]]
    assert add == [["project", "item-add", "7", "--owner", "ajbarea", "--url", url, "--format",
                    "json"]]  # fmt: skip
    assert edits(board) == [("PVTI_5", "o_issue")]
    edit = next(a for a in board.argvs() if a[:2] == ["project", "item-edit"])
    assert edit[edit.index("--project-id") + 1] == "PVT_7"
    assert edit[edit.index("--field-id") + 1] == "F_STATUS"


def test_pr_url_goes_on_as_in_pr(board: GhStub):
    out = "Creating pull request for feat into main\n\nhttps://github.com/ajbarea/techne/pull/3\n"
    proc = run_hook(board, "cd x && gh pr create --fill", out)
    assert proc.returncode == 0 and proc.stdout == ""
    assert edits(board) == [("PVTI_3", "o_pr")]


def test_foreign_owner_is_ignored(board: GhStub):
    proc = run_hook(board, "gh pr create --fill", "https://github.com/someone/techne/pull/3\n")
    assert proc.returncode == 0 and proc.stdout == ""
    assert board.calls() == []


@pytest.mark.parametrize(
    "command",
    [
        "gh pr view 3",
        "gh issue list",
        "ls -la",
        "gh api repos/ajbarea/techne/issues",
        "gh api -X GET repos/ajbarea/techne/pulls -f state=open",
        "gh api -X POST repos/ajbarea/techne/issues/5/comments -f body=x",
        "echo gh issue create",
    ],
)
def test_command_that_opens_nothing_calls_no_gh(board: GhStub, command: str):
    proc = run_hook(board, command, "https://github.com/ajbarea/techne/issues/5\n")
    assert proc.returncode == 0 and proc.stdout == ""
    assert board.calls() == []


def test_gh_failing_tells_claude_and_exits_0(board: GhStub):
    board.rules([{"match": ["project"], "stderr": SCOPE_ERR, "exit": 1}])
    url = "https://github.com/ajbarea/techne/issues/5"
    proc = run_hook(board, "gh issue create -t t -b b", url + "\n")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse"
    line = out["additionalContext"]
    assert "\n" not in line
    assert line.startswith(f"board: could not add {url} (")
    assert "gh auth refresh -h github.com -s project" in line


def test_gh_missing_tells_claude(board: GhStub):
    board.env["PATH"] = str(board.home)  # no gh, no sh
    proc = run_hook(board, "gh pr create --fill", "https://github.com/ajbarea/techne/pull/3\n")
    assert proc.returncode == 0
    assert "gh is not on PATH" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("toml", [None, 'github_user = "ajbarea"\n'])
def test_without_board_config_does_nothing(gh_stub: GhStub, toml: str | None):
    if toml is not None:
        gh_stub.config(toml)
    gh_stub.rules(board_rules())
    proc = run_hook(gh_stub, "gh issue create -t t -b b", "https://github.com/ajbarea/x/issues/5")
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""
    assert gh_stub.calls() == []


def test_malformed_board_config_says_so(gh_stub: GhStub):
    gh_stub.config('[board]\nowner = "ajbarea"\nnumber = "seven"\n')
    proc = run_hook(gh_stub, "gh issue create -t t -b b", "https://github.com/ajbarea/x/issues/5")
    assert proc.returncode == 0
    assert "number = <int>" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert gh_stub.calls() == []


def test_several_urls_each_get_their_status(board: GhStub):
    out = (
        "https://github.com/ajbarea/techne/issues/1\n"
        "https://github.com/ajbarea/papers/pull/2\n"
        "https://github.com/other/repo/issues/4\n"
        "https://github.com/ajbarea/techne/issues/1\n"
    )
    cmd = "gh issue create -t a -b a && gh pr create -R ajbarea/papers --fill"
    proc = run_hook(board, cmd, out)
    assert proc.returncode == 0 and proc.stdout == ""
    assert edits(board) == [("PVTI_1", "o_issue"), ("PVTI_2", "o_pr")]
    # the IDs are looked up once and cached for every later call
    assert sum(a[:2] == ["project", "field-list"] for a in board.argvs()) == 1


def test_api_post_takes_only_the_new_items_url(board: GhStub):
    body = {
        "url": "https://api.github.com/repos/ajbarea/techne/pulls/6",
        "html_url": "https://github.com/ajbarea/techne/pull/6",
        "body": "Closes https://github.com/ajbarea/techne/issues/5",
        "user": {"html_url": "https://github.com/ajbarea"},
    }
    cmd = "gh api repos/ajbarea/techne/pulls -f title=t -f head=feat -f base=main"
    proc = run_hook(board, cmd, json.dumps(body, indent=2))
    assert proc.returncode == 0 and proc.stdout == ""
    assert edits(board) == [("PVTI_6", "o_pr")]


def test_cached_ids_skip_the_lookup(board: GhStub):
    run_hook(board, "gh issue create -t a -b a", "https://github.com/ajbarea/techne/issues/1\n")
    board.log.unlink()
    run_hook(board, "gh pr create --fill", "https://github.com/ajbarea/techne/pull/2\n")
    assert [a[:2] for a in board.argvs()] == [["project", "item-add"], ["project", "item-edit"]]


def test_stale_cache_is_looked_up_again(board: GhStub):
    cache = Path(board.env["XDG_CACHE_HOME"]) / "techne" / "board-ajbarea-7.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"project_id": "PVT_7", "field_id": "F_STATUS",
                                 "options": {"Todo": "o_old"}}))  # fmt: skip
    proc = run_hook(board, "gh pr create --fill", "https://github.com/ajbarea/techne/pull/2\n")
    assert proc.returncode == 0 and proc.stdout == ""
    assert edits(board) == [("PVTI_2", "o_pr")]
    assert json.loads(cache.read_text())["options"]["In PR"] == "o_pr"


def test_board_without_the_status_option_says_run_init(board: GhStub):
    board.rules(board_rules({"Todo": "o_t", "In Progress": "o_p", "Done": "o_d"}))
    proc = run_hook(board, "gh pr create --fill", "https://github.com/ajbarea/techne/pull/2\n")
    line = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "no Status option 'In PR'" in line and "/techne:board init" in line


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("gh issue create --title x", True),
        ("GH_REPO=a/b gh pr create --fill", True),
        ("git push -u origin HEAD && gh pr create --fill --base main", True),
        ("gh api -X POST repos/ajbarea/techne/pulls --input body.json", True),
        ("gh api --method POST /repos/{owner}/{repo}/issues -f title=x", True),
        ("gh api repos/ajbarea/techne/issues -f title=x", True),
        ("gh api https://api.github.com/repos/a/b/pulls --input -", True),
        ("gh api repos/ajbarea/techne/issues", False),
        ("gh api -X PATCH repos/ajbarea/techne/issues -f state=closed", False),
        ("gh api repos/ajbarea/techne/issues/5/comments -f body=x", False),
        ("gh issue view 5", False),
        ("gh pr merge 5 --squash", False),
        ("echo gh pr create", False),
    ],
)
def test_creates_item(pb, command: str, expected: bool):
    assert pb.creates_item(command) is expected


def test_toml_fallback_reads_only_the_board_table(pb):
    text = (
        'github_user = "ajbarea"\nnumber = 3\n\n[[sisters]]\nname = "board"\n\n'
        "[board]  # the projects board\nowner = 'ajbarea'  # login\nnumber = 7\n\n"
        '[other]\nowner = "x"\n'
    )
    assert pb._board_table_fallback(text) == {"owner": "ajbarea", "number": 7}
    assert pb._board_table_fallback('[[board]]\nowner = "x"\n') is None


def test_budget_bounds_a_hanging_gh(pb, gh_stub: GhStub, monkeypatch: pytest.MonkeyPatch):
    gh_stub.rules([{"match": ["project"], "sleep": 5}])
    for key, value in gh_stub.env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(pb.BoardError, match="timed out"):
        pb.gh(["project", "view", "7"], pb.Budget(0.5))
    with pytest.raises(pb.BoardError, match="ran out of time"):
        pb.gh(["project", "view", "7"], pb.Budget(-1))


def test_hooks_json_declares_the_gh_filtered_post_tool_use_hook():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]["PostToolUse"]
    entry = next(e for e in hooks if e["matcher"] == "Bash")
    hook = entry["hooks"][0]
    assert hook["if"] == "Bash(gh *)"
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/board_add.py" in hook["command"]
    assert hook["timeout"] > 8  # the script's own budget
