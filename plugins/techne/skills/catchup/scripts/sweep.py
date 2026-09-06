#!/usr/bin/env python3
"""Collect every comment, review, and state change on one repo, as JSON.

One GraphQL call covers all four surfaces (issue comments, PR comments, review
verdicts, inline review threads) plus the state changes that carry no comment.
The per-PR REST loop this replaces cost two calls per open PR.

Usage:
    sweep.py <repo> [--since ISO8601] [--window-days N] [--prs N] [--issues N]

<repo> is "owner/name", or a bare name resolved against workspace_root in
~/.claude/techne.toml. Writes JSON to stdout; diagnostics to stderr.
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

TECHNE_TOML = Path.home() / ".claude" / "techne.toml"

# GitHub caps a GraphQL page at 100 nodes. These defaults cover months of
# activity on a working repo while keeping the query well under the 500k-node
# cost ceiling; raise with --prs/--issues for a backlog sweep.
DEFAULT_PRS = 50
DEFAULT_ISSUES = 50
NESTED_PAGE = 50

# No participation and no --since means there is no anchor to work from. Two
# weeks is long enough to cover a holiday and short enough to stay readable.
FALLBACK_WINDOW_DAYS = 14

# An anchor older than this stops being a catch-up and becomes a history dump.
MAX_WINDOW_DAYS = 30

# A busy repo can emit thousands of events. Conversational events carry the
# signal and are kept in full; bulk state changes are collapsed to counts past
# this many, because the report renders them as one collapsed line anyway.
MAX_STATE_EVENTS = 25

# Events that represent someone saying something, as opposed to a state flip.
SIGNAL_KINDS = {"comment", "review", "inline_comment", "pr_opened", "issue_opened"}

# Total events returned. A repo the user does not participate in can produce
# hundreds of unrelated comments; anything addressed to them is kept regardless
# of this cap, and the remainder is filled newest-first.
MAX_EVENTS = 80

QUERY = """
query($owner:String!, $name:String!, $prs:Int!, $issues:Int!, $nested:Int!) {
  repository(owner:$owner, name:$name) {
    viewerPermission
    pullRequests(first:$prs, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes {
        number title state isDraft url createdAt updatedAt mergedAt closedAt
        author { login }
        mergedBy { login }
        reviewDecision
        mergeable mergeStateStatus
        commits(last:1) { nodes { commit { statusCheckRollup { state } } } }
        reviewRequests(first:20) {
          nodes {
            requestedReviewer {
              __typename
              ... on User { login }
              ... on Team { slug }
            }
          }
        }
        comments(last:$nested) { nodes { createdAt author { login } body } }
        reviews(last:$nested) { nodes { submittedAt state author { login } body } }
        reviewThreads(last:$nested) {
          nodes {
            isResolved
            comments(first:$nested) {
              nodes { createdAt author { login } body path line }
            }
          }
        }
      }
    }
    issues(first:$issues, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes {
        number title state url createdAt updatedAt closedAt
        author { login }
        assignees(first:10) { nodes { login } }
        comments(last:$nested) { nodes { createdAt author { login } body } }
      }
    }
  }
}
"""


def run(cmd, **kw):
    """Run a command, returning stdout. Raises SystemExit with a usable message."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, **kw)
    except FileNotFoundError:
        sys.exit(f"catchup: {cmd[0]} not found on PATH")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        sys.exit(f"catchup: `{' '.join(cmd)}` failed: {err}")
    return proc.stdout.strip()


def workspace_root():
    """Read workspace_root from techne.toml, or fall back to the parent of cwd."""
    if TECHNE_TOML.exists():
        for line in TECHNE_TOML.read_text().splitlines():
            if line.strip().startswith("workspace_root"):
                return Path(line.split("=", 1)[1].strip().strip('"').strip("'"))
    return Path.cwd().parent


def resolve_repo(name):
    """Resolve a bare repo name to owner/name.

    Uses `gh repo view` inside the local clone rather than parsing the remote
    URL: remotes come in SSH and HTTPS forms with an optional .git suffix, and a
    parse that leaves the suffix attached yields owner/repo.git, which 404s on
    every later call.
    """
    if name and "/" in name:
        return name
    candidates = []
    if name:
        candidates.append(workspace_root() / name)
    candidates.append(Path.cwd())
    for path in candidates:
        if (path / ".git").exists():
            return run(
                ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=path
            )
    hint = f" (looked in {candidates[0]})" if name else ""
    sys.exit(
        f"catchup: cannot resolve repo {name!r}{hint}. "
        "Pass owner/name explicitly, or run from inside the clone."
    )


def graphql(owner, name, prs, issues):
    out = run(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"prs={prs}",
            "-F",
            f"issues={issues}",
            "-F",
            f"nested={NESTED_PAGE}",
        ]
    )
    payload = json.loads(out)
    if payload.get("errors"):
        sys.exit(
            "catchup: GraphQL error: " + "; ".join(e.get("message", "?") for e in payload["errors"])
        )
    repo = (payload.get("data") or {}).get("repository")
    if repo is None:
        sys.exit(f"catchup: repository {owner}/{name} not found or not visible to this token")
    return repo


def first_line(body, limit=200):
    text = (body or "").strip()
    if not text:
        return ""
    line = text.splitlines()[0].strip()
    return line[:limit] + ("…" if len(line) > limit else "")


def collect(repo, me):
    """Flatten the GraphQL payload into a timestamped event list."""
    events = []

    def add(ts, kind, item, actor, body="", **extra):
        if not ts:
            return
        events.append(
            {
                "ts": ts,
                "kind": kind,
                "actor": actor or "ghost",
                "number": item["number"],
                "title": item["title"],
                "url": item["url"],
                "state": item.get("state"),
                "is_self": (actor == me),
                "mentions_me": f"@{me}" in (body or ""),
                "body": first_line(body),
                **extra,
            }
        )

    for pr in repo["pullRequests"]["nodes"]:
        author = (pr.get("author") or {}).get("login")
        add(pr["createdAt"], "pr_opened", pr, author, pr["title"], item_type="pr")
        if pr.get("mergedAt"):
            add(
                pr["mergedAt"],
                "pr_merged",
                pr,
                (pr.get("mergedBy") or {}).get("login"),
                item_type="pr",
            )
        elif pr.get("closedAt"):
            # Closer is not exposed here; do not attribute it to the author.
            add(pr["closedAt"], "pr_closed", pr, None, item_type="pr")
        for c in pr["comments"]["nodes"]:
            add(
                c["createdAt"],
                "comment",
                pr,
                (c.get("author") or {}).get("login"),
                c.get("body"),
                item_type="pr",
            )
        for r in pr["reviews"]["nodes"]:
            add(
                r.get("submittedAt"),
                "review",
                pr,
                (r.get("author") or {}).get("login"),
                r.get("body"),
                item_type="pr",
                review_state=r.get("state"),
            )
        for thread in pr["reviewThreads"]["nodes"]:
            for c in thread["comments"]["nodes"]:
                add(
                    c["createdAt"],
                    "inline_comment",
                    pr,
                    (c.get("author") or {}).get("login"),
                    c.get("body"),
                    item_type="pr",
                    path=c.get("path"),
                    line=c.get("line"),
                    resolved=thread.get("isResolved"),
                )

    for issue in repo["issues"]["nodes"]:
        author = (issue.get("author") or {}).get("login")
        assignees = [a["login"] for a in issue["assignees"]["nodes"]]
        add(
            issue["createdAt"],
            "issue_opened",
            issue,
            author,
            issue["title"],
            item_type="issue",
            assignees=assignees,
        )
        if issue.get("closedAt"):
            # Usually an auto-close from someone else's merge. Attributing it to
            # the author would advance the anchor past their unread comments.
            add(
                issue["closedAt"],
                "issue_closed",
                issue,
                None,
                item_type="issue",
                assignees=assignees,
            )
        for c in issue["comments"]["nodes"]:
            add(
                c["createdAt"],
                "comment",
                issue,
                (c.get("author") or {}).get("login"),
                c.get("body"),
                item_type="issue",
                assignees=assignees,
            )

    events.sort(key=lambda e: e["ts"])
    return events


def _checks_state(pr):
    """SUCCESS/FAILURE/PENDING/None for the head commit's combined checks."""
    nodes = (pr.get("commits") or {}).get("nodes") or []
    if not nodes:
        return None
    rollup = (nodes[0].get("commit") or {}).get("statusCheckRollup")
    return rollup.get("state") if rollup else None


def _viewer_reviews(pr_nodes, me):
    """How many reviews the user has authored here, across the scanned PRs."""
    return sum(
        1
        for pr in pr_nodes
        for r in pr["reviews"]["nodes"]
        if (r.get("author") or {}).get("login") == me
    )


def _review_request(pr, me):
    """Who a review was explicitly asked of: the user, a team, or nobody.

    Being asked is the signal, and it is forward-looking -- a first review on a
    repo is still a review that was requested. Team requests are reported by
    slug rather than resolved, because membership needs a separate org call the
    token may not carry; a team ask is surfaced for the user to judge.
    """
    direct, teams = False, []
    for node in pr.get("reviewRequests", {}).get("nodes", []):
        r = node.get("requestedReviewer") or {}
        if r.get("__typename") == "User" and r.get("login") == me:
            direct = True
        elif r.get("__typename") == "Team":
            teams.append(r.get("slug"))
    return {
        "review_requested_from_me": direct,
        "review_requested_from_teams": teams,
    }


def _tally_states(nodes):
    """Count nodes by state, so a scan total is never read as an open count."""
    tally = {}
    for n in nodes:
        tally[n["state"]] = tally.get(n["state"], 0) + 1
    return tally


def find_anchor(events, repo_slug, me):
    """Latest moment the user participated: comment, review, or commit."""
    # Only deliberate actions anchor the window. A state change on an item the
    # user authored is not participation, and counting it silently drops every
    # comment made before it.
    ACTIONS = {"comment", "review", "inline_comment", "pr_opened", "issue_opened", "pr_merged"}
    # Label the anchor by the action that actually set it. Reporting an issue you
    # opened as "your latest comment/review" overstates the sweep: it implies you
    # read the thread, when you may only have filed it and walked away.
    LABELS = {
        "comment": "your latest comment",
        "review": "your latest review",
        "inline_comment": "your latest review comment",
        "pr_opened": "the PR you opened",
        "issue_opened": "the issue you opened",
        "pr_merged": "your latest merge",
    }
    mine = [e for e in events if e["is_self"] and e["kind"] in ACTIONS]
    latest = max(mine, key=lambda e: e["ts"]) if mine else None
    source = LABELS.get(latest["kind"], "your latest activity") if latest else None
    anchor = latest["ts"] if latest else None

    # `gh api --jq` prints a bare string, not JSON, so take it verbatim rather
    # than parsing it.
    commit_ts = run(
        [
            "gh",
            "api",
            f"repos/{repo_slug}/commits",
            "--jq",
            f'[.[] | select(.author.login == "{me}") | .commit.author.date] | max',
        ]
    ).strip('"')
    if commit_ts and commit_ts != "null":
        if anchor is None or commit_ts > anchor:
            anchor, source = commit_ts, "your latest commit"
    return anchor, source


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?", help="owner/name, or a bare repo name")
    ap.add_argument("--since", help="ISO8601 override for the anchor")
    ap.add_argument("--window-days", type=int, default=MAX_WINDOW_DAYS)
    ap.add_argument("--prs", type=int, default=DEFAULT_PRS)
    ap.add_argument("--issues", type=int, default=DEFAULT_ISSUES)
    ap.add_argument(
        "--max-events",
        type=int,
        default=MAX_EVENTS,
        help="cap on returned events; items addressed to you are always kept",
    )
    args = ap.parse_args()

    slug = resolve_repo(args.repo)
    owner, name = slug.split("/", 1)
    me = run(["gh", "api", "user", "--jq", ".login"])

    repo = graphql(owner, name, args.prs, args.issues)
    events = collect(repo, me)

    # Items the user opened: activity on these is relevant even without a mention.
    my_items = {
        e["number"] for e in events if e["is_self"] and e["kind"] in ("pr_opened", "issue_opened")
    }

    now = datetime.now(UTC)
    floor = (now - timedelta(days=args.window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    if args.since:
        anchor, source, capped = args.since, "--since override", False
    else:
        anchor, source = find_anchor(events, slug, me)
        capped = False
        if anchor is None:
            anchor = (now - timedelta(days=FALLBACK_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
            source = f"no participation found; last {FALLBACK_WINDOW_DAYS} days"
        elif anchor < floor:
            anchor, source, capped = floor, f"{source} (capped)", True

    # ISO8601 Z strings from the GitHub API are fixed-width UTC, so lexical
    # comparison is chronological. Do not mix in a differently formatted stamp.
    new_events = [e for e in events if e["ts"] > anchor]

    # Keep every conversational event; collapse bulk state flips so a busy repo
    # cannot flood the context with merge/close noise.
    signal = [e for e in new_events if e["kind"] in SIGNAL_KINDS]
    state = [e for e in new_events if e["kind"] not in SIGNAL_KINDS]
    state_collapsed = None
    if len(state) > MAX_STATE_EVENTS:
        by_kind = {}
        for e in state:
            by_kind.setdefault(e["kind"], []).append(e["number"])
        state_collapsed = {
            k: {"count": len(v), "numbers": sorted(set(v))} for k, v in by_kind.items()
        }
        state = state[-MAX_STATE_EVENTS:]
    candidates = sorted(signal + state, key=lambda e: e["ts"])

    # Anything aimed at the user survives the cap. Everything else competes on
    # recency, so a busy upstream repo cannot bury the one comment that matters.
    def addressed(e):
        return e["mentions_me"] or e["number"] in my_items

    if len(candidates) > args.max_events:
        keep = [e for e in candidates if addressed(e)]
        rest = [e for e in candidates if not addressed(e)]
        budget = max(0, args.max_events - len(keep))
        reported = sorted(keep + rest[-budget:], key=lambda e: e["ts"])
    else:
        reported = candidates
    omitted = len(candidates) - len(reported)

    pr_nodes = repo["pullRequests"]["nodes"]
    truncated = len(pr_nodes) >= args.prs or len(repo["issues"]["nodes"]) >= args.issues

    json.dump(
        {
            "repo": slug,
            "me": me,
            "anchor": anchor,
            "anchor_source": source,
            "window_capped": capped,
            "truncated": truncated,
            "counts": {
                "new_events": len(new_events),
                "reported": len(reported),
                "scanned_prs": len(pr_nodes),
                "scanned_prs_by_state": _tally_states(pr_nodes),
                "scanned_issues": len(repo["issues"]["nodes"]),
                "scanned_issues_by_state": _tally_states(repo["issues"]["nodes"]),
                "pr_cap": args.prs,
                "issue_cap": args.issues,
                "viewer_reviews_in_scan": _viewer_reviews(pr_nodes, me),
                "viewer_permission": repo.get("viewerPermission"),
            },
            "state_changes_collapsed": state_collapsed,
            "events_omitted": omitted,
            "open_prs": [
                {
                    "number": p["number"],
                    "title": p["title"],
                    "author": (p.get("author") or {}).get("login"),
                    "isDraft": p["isDraft"],
                    "reviewDecision": p.get("reviewDecision"),
                    "mergeable": p.get("mergeable"),
                    "mergeStateStatus": p.get("mergeStateStatus"),
                    "checks": _checks_state(p),
                    **_review_request(p, me),
                    "reviews": len(p["reviews"]["nodes"]),
                    "unresolved_threads": sum(
                        1 for t in p["reviewThreads"]["nodes"] if not t.get("isResolved")
                    ),
                    "updatedAt": p["updatedAt"],
                    "url": p["url"],
                }
                for p in pr_nodes
                if p["state"] == "OPEN"
            ],
            "open_issues": [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "author": (i.get("author") or {}).get("login"),
                    "assignees": [a["login"] for a in i["assignees"]["nodes"]],
                    "comments": len(i["comments"]["nodes"]),
                    "last_commenter": (
                        ((i["comments"]["nodes"][-1].get("author") or {}).get("login"))
                        if i["comments"]["nodes"]
                        else None
                    ),
                    "createdAt": i["createdAt"],
                    "updatedAt": i["updatedAt"],
                    "url": i["url"],
                }
                for i in repo["issues"]["nodes"]
                if i["state"] == "OPEN"
            ],
            "events": reported,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
