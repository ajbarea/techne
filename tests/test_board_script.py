"""techne:board's script: show, sync, idea, live and init against a stub gh on PATH.

The failures that matter: a board shown out of Status order, a sync that moves a Live item off
Live or adds closed issues it should only move, init dropping Status options items still use,
and a command that acts without a [board] table.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys

import pytest
from conftest import BOARD_SCRIPT, BOARD_TOML, GhStub, board_rules


def run(stub: GhStub, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BOARD_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=stub.env,
        timeout=60,
    )


def item(item_id: str, status: str | None, url: str | None = None, **content) -> dict:
    record: dict = {"id": item_id, "content": dict(content)}
    if url:
        record["content"]["url"] = url
    if status is not None:
        record["status"] = status
    return record


def issue(n: int, status: str | None, repo: str = "ajbarea/techne", kind: str = "Issue") -> dict:
    path = "issues" if kind == "Issue" else "pull"
    return item(f"PVTI_{n}", status, f"https://github.com/{repo}/{path}/{n}", type=kind,
                number=n, repository=repo, title=f"title {n}")  # fmt: skip


def listing(items: list[dict]) -> dict:
    return {"match": ["project", "item-list"], "stdout": json.dumps({"items": items})}


@pytest.fixture
def board(gh_stub: GhStub) -> GhStub:
    gh_stub.config(BOARD_TOML)
    gh_stub.rules(board_rules())
    return gh_stub


def edits(stub: GhStub) -> list[tuple[str, str]]:
    return [
        (a[a.index("--id") + 1], a[a.index("--single-select-option-id") + 1])
        for a in stub.argvs()
        if a[:2] == ["project", "item-edit"]
    ]


def test_render_groups_in_status_order(bd):
    items = [
        issue(2, "Merged"),
        item("D1", "Idea", type="DraftIssue", title="a draft"),
        issue(3, "In PR", kind="PullRequest"),
        issue(4, "Live", repo="someone/else"),
        issue(5, None),
        issue(1, "Issue"),
    ]
    text = bd.render(items, "ajbarea")
    assert text.splitlines() == [
        "Idea (1)", "  a draft",
        "Issue (1)", "  techne#1 title 1",
        "In PR (1)", "  techne#3 title 3",
        "Merged (1)", "  techne#2 title 2",
        "Live (1)", "  someone/else#4 title 4",
        "No status (1)", "  techne#5 title 5",
    ]  # fmt: skip


def test_show_prints_the_board(board: GhStub):
    board.rules([listing([issue(1, "Issue")]), *board_rules()])
    proc = run(board, "show")
    assert proc.returncode == 0, proc.stderr
    assert "Issue (1)\n  techne#1 title 1" in proc.stdout
    assert ["--limit", "1000"] == next(
        a[a.index("--limit") : a.index("--limit") + 2] for a in board.argvs()
    )


def test_a_board_gh_cannot_list_whole_is_refused(board: GhStub):
    out = json.dumps({"items": [issue(1, "Live")], "totalCount": 1001})
    board.rules(
        [
            {"match": ["repo", "list"], "stdout": "[]"},
            {"match": ["project", "item-list"], "stdout": out},
            *board_rules(),
        ]
    )
    proc = run(board, "sync")
    assert proc.returncode == 1 and "1001 items and gh listed 1" in proc.stderr
    assert edits(board) == []


def test_plan_sync_never_moves_live_and_adds_only_what_it_should(bd):
    url = "https://github.com/ajbarea/techne/{}/{}".format
    items = [issue(1, "Live"), issue(2, "Issue"), issue(3, "In PR", kind="PullRequest")]
    found = [
        (url("issues", 1), "Merged", False),  # Live stays
        (url("issues", 2), "Issue", True),  # unchanged
        (url("pull", 3), "Merged", True),  # moved
        (url("pull", 3), "Merged", True),  # listed twice
        (url("issues", 8), "Issue", True),  # added
        (url("issues", 9), "Merged", False),  # closed, not on the board: left off
    ]
    actions, counts = bd.plan_sync(items, found)
    assert actions == [(url("pull", 3), "Merged", "PVTI_3"), (url("issues", 8), "Issue", None)]
    assert counts == {"add": 1, "move": 1, "unchanged": 1, "live": 1}


def test_sync_reads_only_recent_repos_and_reports_counts(board: GhStub):
    now = dt.datetime.now(dt.UTC)
    repos = [
        {"name": "techne", "pushedAt": (now - dt.timedelta(days=1)).isoformat()},
        {"name": "old", "pushedAt": (now - dt.timedelta(days=40)).isoformat()},
    ]
    u = "https://github.com/ajbarea/techne/{}/{}".format

    def urls(*xs: str) -> str:
        return json.dumps([{"url": x} for x in xs])

    board.rules(
        [
            {"match": ["repo", "list"], "stdout": json.dumps(repos)},
            {"match": ["issue", "list", "open"], "stdout": urls(u("issues", 1), u("issues", 2))},
            {"match": ["pr", "list", "open"], "stdout": urls(u("pull", 3))},
            {"match": ["pr", "list", "merged"], "stdout": urls(u("pull", 4))},
            {"match": ["issue", "list", "closed"], "stdout": urls(u("issues", 5), u("issues", 6))},
            listing([issue(1, "Issue"), issue(4, "Live", kind="PullRequest"), issue(5, "Issue")]),
            *board_rules(),
        ]
    )
    proc = run(board, "sync", "--days", "7")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[0] == (
        "sync: 1 repo(s) pushed in the last 7 day(s); added 2, moved 1, unchanged 1, "
        "kept on Live 1, failed 0"
    )
    queried = {a[a.index("-R") + 1] for a in board.argvs() if "-R" in a}
    assert queried == {"ajbarea/techne"}
    assert sorted(edits(board)) == [("PVTI_2", "o_issue"), ("PVTI_3", "o_pr"),
                                    ("PVTI_5", "o_merged")]  # fmt: skip
    since = (now - dt.timedelta(days=7)).date().isoformat()
    assert any(f"merged:>={since}" in a for a in board.argvs())


def test_sync_counts_a_failing_repo_and_goes_on(board: GhStub):
    now = dt.datetime.now(dt.UTC).isoformat()
    board.rules(
        [
            {"match": ["repo", "list"], "stdout": json.dumps([{"name": "a", "pushedAt": now}])},
            {"match": ["issue", "list"], "stderr": "the repo has disabled issues\n", "exit": 1},
            listing([]),
            *board_rules(),
        ]
    )
    proc = run(board, "sync")
    assert proc.returncode == 1
    assert "failed 1" in proc.stdout and "a: the repo has disabled issues" in proc.stdout


def test_idea_adds_a_draft_as_idea(board: GhStub):
    board.rules(
        [
            {"match": ["project", "item-create"], "stdout": json.dumps({"id": "PVTI_D"})},
            *board_rules(),
        ]
    )
    proc = run(board, "idea", "Cache the board", "--body", "why")
    assert proc.returncode == 0, proc.stderr
    create = next(a for a in board.argvs() if a[:2] == ["project", "item-create"])
    assert create[create.index("--title") + 1] == "Cache the board"
    assert create[create.index("--body") + 1] == "why"
    assert edits(board) == [("PVTI_D", "o_idea")]


def test_live_sets_live(board: GhStub):
    proc = run(board, "live", "https://github.com/ajbarea/techne/pull/7")
    assert proc.returncode == 0, proc.stderr
    assert edits(board) == [("PVTI_7", "o_live")]


def test_live_refuses_a_non_item_url(board: GhStub):
    proc = run(board, "live", "https://github.com/ajbarea/techne")
    assert proc.returncode == 1 and "not a GitHub issue or pull request URL" in proc.stderr
    assert board.calls() == []


@pytest.mark.parametrize("command", [["show"], ["sync"], ["idea", "x"], ["live", "u"]])
def test_without_board_config_commands_stop(gh_stub: GhStub, command: list[str]):
    proc = run(gh_stub, *command)
    assert proc.returncode == 1 and "no [board] table" in proc.stderr
    assert gh_stub.calls() == []


def test_status_plan_keeps_ids_and_reports_drops(bd):
    current = [{"id": f"o{i}", "name": n} for i, n in enumerate(bd.pb.STATUSES)]
    assert bd.status_plan(current) is None
    new, dropped = bd.status_plan([{"id": "o_t", "name": "Todo"}, {"id": "o_i", "name": "Issue"}])
    assert [o["name"] for o in new] == list(bd.pb.STATUSES)
    assert new[1] == {"id": "o_i", "name": "Issue", "color": "BLUE",
                      "description": "Filed as an issue"}  # fmt: skip
    assert "id" not in new[0] and dropped == ["Todo"]


DEFAULT_STATUS = {"Todo": "o_t", "In Progress": "o_p", "Done": "o_d"}


def init_rules(projects: list[dict], items: list[dict]) -> list[dict]:
    written = {"data": {"updateProjectV2Field": {"projectV2Field": {"options": [
        {"id": f"n{i}", "name": n} for i, n in enumerate(["Idea", "Issue", "In PR", "Merged",
                                                          "Live"])]}}}}  # fmt: skip
    return [
        {"match": ["project", "list"], "stdout": json.dumps({"projects": projects})},
        {"match": ["project", "create"], "stdout": json.dumps({"number": 9, "id": "PVT_9"})},
        {"match": ["api", "graphql"], "stdout": json.dumps(written)},
        listing(items),
        *board_rules(DEFAULT_STATUS),
    ]


def test_init_creates_the_board_and_sets_the_five_statuses(gh_stub: GhStub):
    gh_stub.config('github_user = "ajbarea"\n')
    gh_stub.rules(init_rules([{"number": 3, "title": "other"}], []))
    proc = run(gh_stub, "init", "--title", "ajsoftworks")
    assert proc.returncode == 0, proc.stderr
    create = next(a for a in gh_stub.argvs() if a[:2] == ["project", "create"])
    assert create[:6] == ["project", "create", "--owner", "ajbarea", "--title", "ajsoftworks"]
    call = next(c for c in gh_stub.calls() if c["argv"][:2] == ["api", "graphql"])
    body = json.loads(call["stdin"])
    assert "updateProjectV2Field" in body["query"]
    assert body["variables"]["field"] == "F_STATUS"
    assert [o["name"] for o in body["variables"]["options"]] == [
        "Idea", "Issue", "In PR", "Merged", "Live"]  # fmt: skip
    assert '[board]\nowner = "ajbarea"\nnumber = 9\n' in proc.stdout
    assert "Item closed" in proc.stdout and "Pull request merged" in proc.stdout
    assert not (gh_stub.home / ".claude" / "techne.toml").read_text().count("[board]")


def test_init_reuses_an_existing_board_and_keeps_used_options(gh_stub: GhStub):
    gh_stub.config(BOARD_TOML)
    gh_stub.rules(init_rules([{"number": 7, "title": "ajsoftworks"}], [issue(1, "Done")]))
    proc = run(gh_stub, "init", "--title", "ajsoftworks")
    assert proc.returncode == 1
    assert "1 item(s) have a Status that init would remove" in proc.stderr
    argvs = gh_stub.argvs()
    assert not any(a[:2] == ["project", "create"] for a in argvs)
    assert not any(a[:2] == ["api", "graphql"] for a in argvs)


def test_init_leaves_a_board_already_set_up(gh_stub: GhStub):
    gh_stub.config(BOARD_TOML)
    rules = init_rules([{"number": 7, "title": "ajsoftworks"}], [])
    gh_stub.rules([r for r in rules if r["match"][:2] != ["project", "field-list"]] + board_rules())
    proc = run(gh_stub, "init", "--title", "ajsoftworks")
    assert proc.returncode == 0, proc.stderr
    assert "Status already holds Idea, Issue, In PR, Merged, Live" in proc.stdout
    assert not any(a[:2] == ["api", "graphql"] for a in gh_stub.argvs())
