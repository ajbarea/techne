#!/usr/bin/env python3
"""The techne board: one GitHub Projects board for every repo an owner has, by Status.

  show                     the board grouped by Status: Idea, Issue, In PR, Merged, Live
  sync [--days N]          add open issues, open PRs and recently merged PRs of recently
                           pushed repos, and move items whose state changed (never off Live)
  idea TITLE [--body B]    add a draft item with Status Idea
  live URL                 set an issue or PR to Live (after a deploy)
  init --title T [--owner O]
                           create the board if missing, set its Status options, and print
                           the [board] table for ~/.claude/techne.toml

Every command but init needs a [board] table (owner, number) in ~/.claude/techne.toml.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # the plugin cache stays as installed
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "_shared"))
import doctor_lib  # noqa: E402  # ty: ignore[unresolved-import]
import project_board as pb  # noqa: E402  # ty: ignore[unresolved-import]
import techne_config as tc  # noqa: E402  # ty: ignore[unresolved-import]

doctor_lib.require_python((3, 11), "board", "/techne:setup")


ITEM_LIMIT = "1000"
LIST_TIMEOUT = 60.0
RUN_SECONDS = 120.0
SYNC_SECONDS = 1200.0
OTHER = "No status"
COLORS = {"Idea": "GRAY", "Issue": "BLUE", "In PR": "YELLOW", "Merged": "PURPLE", "Live": "GREEN"}
DESCRIPTIONS = {
    "Idea": "Not filed yet",
    "Issue": "Filed as an issue",
    "In PR": "A pull request is open",
    "Merged": "Merged or closed",
    "Live": "Deployed",
}
DEFAULT_OPTIONS = {"Todo", "In Progress", "Done"}  # a new project's Status options
UPDATE_STATUS = """
mutation($field: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]) {
  updateProjectV2Field(input: {fieldId: $field, singleSelectOptions: $options}) {
    projectV2Field { ... on ProjectV2SingleSelectField { options { id name } } }
  }
}
"""
WORKFLOWS = """\
Built-in workflows: GitHub's API cannot set them, so set two by hand. Open the board, then
the menu (...) at the top right, then Workflows. For each of these two, click it, click Edit,
set Status to Merged, then click Save and turn on workflow:
  - Item closed
  - Pull request merged"""


def board_items(board: pb.Board, budget: pb.Budget) -> list[dict]:
    data = pb.gh_json(
        ["project", "item-list", str(board.number), "--owner", board.owner, "--limit", ITEM_LIMIT],
        budget,
        cap=LIST_TIMEOUT,
    )
    items = data.get("items") if isinstance(data, dict) else None
    listed = [i for i in items or [] if isinstance(i, dict)]
    total = data.get("totalCount") if isinstance(data, dict) else None
    if isinstance(total, int) and total > len(listed):
        # an unlisted Live item would look absent, and sync would re-file it off Live
        raise pb.BoardError(
            f"the board has {total} items and gh listed {len(listed)}; archive finished items"
        )
    return listed


def label(item: dict, owner: str) -> str:
    content = item.get("content") or {}
    if content.get("type") in ("Issue", "PullRequest"):
        repo = str(content.get("repository") or "")
        if repo.lower().startswith(owner.lower() + "/"):
            repo = repo.split("/", 1)[1]
        return f"{repo}#{content.get('number')} {content.get('title') or ''}".rstrip()
    return str(content.get("title") or item.get("title") or "(untitled)")


def render(items: list[dict], owner: str) -> str:
    groups: dict[str, list[str]] = {s: [] for s in (*pb.STATUSES, OTHER)}
    for item in items:
        status = item.get("status")
        key = status if isinstance(status, str) and status in pb.STATUSES else OTHER
        groups[key].append(label(item, owner))
    lines: list[str] = []
    for status, entries in groups.items():
        if status == OTHER and not entries:
            continue
        lines.append(f"{status} ({len(entries)})")
        lines += [f"  {e}" for e in sorted(entries, key=str.lower)]
    return "\n".join(lines)


def plan_sync(
    items: list[dict], found: list[tuple[str, str, bool]]
) -> tuple[list[tuple[str, str, str | None]], dict[str, int]]:
    """Which of FOUND (url, status, add when missing) to add or move, given the board's ITEMS.

    Returns ([(url, status, item id or None to add)], counts). A Live item is never moved."""
    on_board: dict[str, tuple[str, str | None]] = {}
    for item in items:
        url = (item.get("content") or {}).get("url")
        if isinstance(url, str):
            on_board[url] = (str(item.get("id")), item.get("status"))
    counts = {"add": 0, "move": 0, "unchanged": 0, "live": 0}
    actions: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for url, status, add in found:
        if url in seen:
            continue
        seen.add(url)
        if url in on_board:
            item_id, current = on_board[url]
            if current == "Live" and status != "Live":
                counts["live"] += 1
            elif current == status:
                counts["unchanged"] += 1
            else:
                counts["move"] += 1
                actions.append((url, status, item_id))
        elif add:
            counts["add"] += 1
            actions.append((url, status, None))
    return actions, counts


def recent_repos(owner: str, days: int, now: dt.datetime, budget: pb.Budget) -> list[str]:
    out = pb.gh(
        [
            "repo", "list", owner, "--no-archived", "--limit", ITEM_LIMIT,
            "--json", "name,pushedAt",
        ],
        budget,
        cap=LIST_TIMEOUT,
    )  # fmt: skip
    cutoff = now - dt.timedelta(days=days)
    names = []
    for repo in json.loads(out or "[]"):
        pushed = repo.get("pushedAt")
        if not isinstance(pushed, str) or not pushed:
            continue
        when = dt.datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        if when >= cutoff:
            names.append(str(repo["name"]))
    return sorted(names)


def repo_found(slug: str, since: str, budget: pb.Budget) -> list[tuple[str, str, bool]]:
    """(url, status, add when missing) for one repo's open issues and PRs, PRs merged since
    SINCE, and issues closed since SINCE (moved to Merged only when already on the board)."""
    queries = [
        (["issue", "list", "--state", "open"], "Issue", True),
        (["pr", "list", "--state", "open"], "In PR", True),
        (["pr", "list", "--state", "merged", "--search", f"merged:>={since}"], "Merged", True),
        (["issue", "list", "--state", "closed", "--search", f"closed:>={since}"], "Merged", False),
    ]
    found = []
    for args, status, add in queries:
        out = pb.gh(
            [*args, "-R", slug, "--limit", ITEM_LIMIT, "--json", "url"], budget, cap=LIST_TIMEOUT
        )
        found += [(str(r["url"]), status, add) for r in json.loads(out or "[]")]
    return found


def cmd_show(board: pb.Board, _args: argparse.Namespace) -> int:
    print(render(board_items(board, pb.Budget(RUN_SECONDS)), board.owner))
    return 0


def cmd_sync(board: pb.Board, args: argparse.Namespace) -> int:
    budget = pb.Budget(SYNC_SECONDS)
    now = dt.datetime.now(dt.UTC)
    since = (now - dt.timedelta(days=args.days)).date().isoformat()
    repos = recent_repos(board.owner, args.days, now, budget)
    found: list[tuple[str, str, bool]] = []
    failures: list[str] = []
    for name in repos:
        try:
            found += repo_found(f"{board.owner}/{name}", since, budget)
        except (pb.BoardError, ValueError, KeyError) as exc:
            failures.append(f"{name}: {exc}")
    actions, counts = plan_sync(board_items(board, budget), found)
    for url, status, item_id in actions:
        try:
            if item_id is None:
                pb.file_item(board, url, status, budget)
            else:
                pb.set_status(board, item_id, status, budget)
        except pb.BoardError as exc:
            failures.append(f"{url}: {exc}")
    print(
        f"sync: {len(repos)} repo(s) pushed in the last {args.days} day(s); "
        f"added {counts['add']}, moved {counts['move']}, unchanged {counts['unchanged']}, "
        f"kept on Live {counts['live']}, failed {len(failures)}"
    )
    for line in failures:
        print(f"  failed {line}")
    return 1 if failures else 0


def cmd_idea(board: pb.Board, args: argparse.Namespace) -> int:
    budget = pb.Budget(RUN_SECONDS)
    create = ["project", "item-create", str(board.number), "--owner", board.owner]
    create += ["--title", args.title]
    if args.body:
        create += ["--body", args.body]
    item = pb.gh_json(create, budget)
    item_id = item.get("id") if isinstance(item, dict) else None
    if not isinstance(item_id, str):
        raise pb.BoardError("`gh project item-create` returned no item id")
    pb.set_status(board, item_id, "Idea", budget)
    print(f"idea: added '{args.title}' as Idea")
    return 0


def cmd_live(board: pb.Board, args: argparse.Namespace) -> int:
    if not pb.ITEM_URL.fullmatch(args.url):
        raise pb.BoardError(f"{args.url} is not a GitHub issue or pull request URL")
    pb.file_item(board, args.url, "Live", pb.Budget(RUN_SECONDS))
    print(f"live: {args.url} is Live")
    return 0


def status_plan(options: list[dict]) -> tuple[list[dict], list[str]] | None:
    """(the Status options to write, existing option names it drops), or None when the field
    already holds exactly STATUSES in order. An option whose name stays keeps its ID, so the
    items set to it keep their value."""
    names = [str(o.get("name")) for o in options]
    if tuple(names) == pb.STATUSES:
        return None
    ids = {str(o.get("name")): str(o.get("id")) for o in options}
    new = []
    for name in pb.STATUSES:
        option = {"name": name, "color": COLORS[name], "description": DESCRIPTIONS[name]}
        if name in ids:
            option = {"id": ids[name], **option}
        new.append(option)
    return new, [n for n in names if n not in pb.STATUSES]


def written_options(response: dict) -> tuple:
    """The option names an updateProjectV2Field response reports."""
    node = response.get("data") or {}
    for key in ("updateProjectV2Field", "projectV2Field"):
        node = node.get(key) or {}
    return tuple(o.get("name") for o in node.get("options") or [])


def configured_owner() -> str | None:
    try:
        board = pb.load_board()
    except pb.BoardError:
        board = None
    if board:
        return board.owner
    try:
        cfg = tc.load()
    except tc.ConfigError as exc:
        raise pb.BoardError(f"{exc}; fix it, or pass --owner") from exc
    return tc.github_user(cfg) if cfg else None


def cmd_init(args: argparse.Namespace) -> int:
    owner = args.owner or configured_owner()
    if not owner:
        raise pb.BoardError("pass --owner, or set github_user in ~/.claude/techne.toml")
    budget = pb.Budget(RUN_SECONDS)
    listed = pb.gh_json(["project", "list", "--owner", owner, "--limit", "100"], budget)
    same = [
        p
        for p in listed.get("projects") or []
        if isinstance(p, dict) and p.get("title") == args.title and not p.get("closed")
    ]
    if len(same) > 1:
        numbers = ", ".join(str(p.get("number")) for p in same)
        raise pb.BoardError(f"{owner} has several open projects titled {args.title}: {numbers}")
    if same:
        number = int(same[0]["number"])
        print(f"init: {owner} already has project {number}, {args.title}")
    else:
        made = pb.gh_json(["project", "create", "--owner", owner, "--title", args.title], budget)
        number = int(made["number"])
        print(f"init: created project {number}, {args.title}")
    board = pb.Board(owner, number)
    fields = pb.gh_json(["project", "field-list", str(number), "--owner", owner], budget)
    status = pb.status_field(fields)
    if status is None:
        raise pb.BoardError(f"project {number} has no {pb.STATUS_FIELD} field")
    plan = status_plan(list(status.get("options") or []))
    if plan is None:
        print(f"init: {pb.STATUS_FIELD} already holds {', '.join(pb.STATUSES)}")
    else:
        options, dropped = plan
        if dropped:
            in_use = [i for i in board_items(board, budget) if i.get("status") in dropped]
            if in_use:
                raise pb.BoardError(
                    f"{len(in_use)} item(s) have a {pb.STATUS_FIELD} that init would remove "
                    f"({', '.join(dropped)}); move them to one of {', '.join(pb.STATUSES)} first"
                )
        body = json.dumps(
            {"query": UPDATE_STATUS, "variables": {"field": status["id"], "options": options}}
        )
        out = json.loads(pb.gh(["api", "graphql", "--input", "-"], budget, stdin=body))
        if written_options(out) != pb.STATUSES:
            raise pb.BoardError(f"GitHub did not take the {pb.STATUS_FIELD} options: {out}")
        print(f"init: {pb.STATUS_FIELD} is now {', '.join(pb.STATUSES)}")
    pb.forget_ids(board)
    print(f'\nAdd to ~/.claude/techne.toml:\n\n[board]\nowner = "{owner}"\nnumber = {number}\n')
    print(WORKFLOWS)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="board.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="the board grouped by Status")
    sync = sub.add_parser("sync", help="add recent issues and PRs, move changed ones")
    sync.add_argument("--days", type=int, default=14)
    idea = sub.add_parser("idea", help="add a draft item with Status Idea")
    idea.add_argument("title")
    idea.add_argument("--body", default="")
    live = sub.add_parser("live", help="set an issue or PR to Live")
    live.add_argument("url")
    init = sub.add_parser("init", help="create the board and set its Status options")
    init.add_argument("--title", required=True)
    init.add_argument("--owner")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            return cmd_init(args)
        board = pb.load_board()
        if board is None:
            print(
                f"board: no [board] table in {tc.techne_toml()}; run init first",
                file=sys.stderr,
            )
            return 1
        commands = {"show": cmd_show, "sync": cmd_sync, "idea": cmd_idea, "live": cmd_live}
        return commands[args.command](board, args)
    except (pb.BoardError, ValueError, KeyError) as exc:
        print(f"board: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
