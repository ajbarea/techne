"""Unit tests for techne:catchup's sweep.

The failure this skill cannot recover from is a false all-clear: reporting
"nothing to catch up on" while a blocking comment sits unread. Most of what
follows guards a path that would produce one quietly.
"""

from __future__ import annotations

import pytest

ME = "ajbarea"


def item(number=1, title="A PR", url="https://example/1", state="OPEN"):
    return {"number": number, "title": title, "url": url, "state": state}


# ----------------------------------------------------------- first_line --


def test_an_empty_body_yields_an_empty_string(sw):
    assert sw.first_line(None) == ""
    assert sw.first_line("   \n\n") == ""


def test_only_the_first_line_is_kept(sw):
    assert sw.first_line("Heading\nrest of the body\n") == "Heading"


def test_a_long_line_is_truncated_with_an_ellipsis(sw):
    assert sw.first_line("x" * 250) == "x" * 200 + "…"


def test_a_line_at_the_limit_is_not_marked_truncated(sw):
    assert sw.first_line("x" * 200) == "x" * 200


# --------------------------------------------------------- PR accessors --


def test_checks_state_is_none_when_nothing_has_run(sw):
    assert sw._checks_state({}) is None
    assert sw._checks_state({"commits": {"nodes": []}}) is None
    no_rollup = {"commits": {"nodes": [{"commit": {"statusCheckRollup": None}}]}}
    assert sw._checks_state(no_rollup) is None


def test_checks_state_reads_the_head_commit_rollup(sw):
    pr = {"commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]}}
    assert sw._checks_state(pr) == "FAILURE"


def test_a_direct_review_request_is_recognised(sw):
    pr = {"reviewRequests": {"nodes": [{"requestedReviewer": {"__typename": "User", "login": ME}}]}}
    assert sw._review_request(pr, ME)["review_requested_from_me"] is True


def test_someone_elses_review_request_is_not_mine(sw):
    pr = {
        "reviewRequests": {
            "nodes": [{"requestedReviewer": {"__typename": "User", "login": "someone"}}]
        }
    }
    out = sw._review_request(pr, ME)
    assert out["review_requested_from_me"] is False
    assert out["review_requested_from_teams"] == []


def test_a_team_request_is_surfaced_by_slug(sw):
    pr = {
        "reviewRequests": {
            "nodes": [{"requestedReviewer": {"__typename": "Team", "slug": "reviewers"}}]
        }
    }
    assert sw._review_request(pr, ME)["review_requested_from_teams"] == ["reviewers"]


def test_a_missing_review_request_block_is_not_an_error(sw):
    assert sw._review_request({}, ME) == {
        "review_requested_from_me": False,
        "review_requested_from_teams": [],
    }


def test_viewer_reviews_counts_only_mine(sw):
    nodes = [
        {"reviews": {"nodes": [{"author": {"login": ME}}, {"author": {"login": "other"}}]}},
        {"reviews": {"nodes": [{"author": None}, {"author": {"login": ME}}]}},
    ]
    assert sw._viewer_reviews(nodes, ME) == 2


def test_states_are_tallied_so_a_scan_total_is_not_an_open_count(sw):
    nodes = [{"state": "OPEN"}, {"state": "MERGED"}, {"state": "OPEN"}]
    assert sw._tally_states(nodes) == {"OPEN": 2, "MERGED": 1}


# -------------------------------------------------------------- collect --


def base_repo(prs=None, issues=None):
    return {
        "pullRequests": {"nodes": prs or []},
        "issues": {"nodes": issues or []},
    }


def pr_node(**over):
    node = {
        **item(),
        "createdAt": "2026-09-01T00:00:00Z",
        "author": {"login": "someone"},
        "mergedAt": None,
        "closedAt": None,
        "mergedBy": None,
        "comments": {"nodes": []},
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "timelineItems": {"nodes": []},
    }
    node.update(over)
    return node


def kinds(events):
    return [e["kind"] for e in events]


def test_an_opened_pr_becomes_an_event(sw):
    events = sw.collect(base_repo(prs=[pr_node()]), ME)
    assert kinds(events) == ["pr_opened"]
    assert events[0]["actor"] == "someone"
    assert events[0]["is_self"] is False


def test_my_own_activity_is_flagged_as_mine(sw):
    events = sw.collect(base_repo(prs=[pr_node(author={"login": ME})]), ME)
    assert events[0]["is_self"] is True


def test_a_deleted_account_does_not_crash_the_sweep(sw):
    events = sw.collect(base_repo(prs=[pr_node(author=None)]), ME)
    assert events[0]["actor"] == "ghost"


def test_a_close_is_not_attributed_to_the_author(sw):
    """The closer is not in the payload. Naming the author would report the
    wrong person having closed someone's PR."""
    node = pr_node(closedAt="2026-09-02T00:00:00Z", state="CLOSED")
    closed = [e for e in sw.collect(base_repo(prs=[node]), ME) if e["kind"] == "pr_closed"]
    assert closed[0]["actor"] == "ghost"


def test_a_merge_is_attributed_to_whoever_merged_it(sw):
    node = pr_node(mergedAt="2026-09-03T00:00:00Z", mergedBy={"login": "maintainer"})
    merged = [e for e in sw.collect(base_repo(prs=[node]), ME) if e["kind"] == "pr_merged"]
    assert merged[0]["actor"] == "maintainer"


def test_a_merged_pr_does_not_also_report_as_closed(sw):
    node = pr_node(mergedAt="2026-09-03T00:00:00Z", closedAt="2026-09-03T00:00:00Z")
    assert "pr_closed" not in kinds(sw.collect(base_repo(prs=[node]), ME))


def test_a_comment_mentioning_me_is_marked(sw):
    node = pr_node(
        comments={
            "nodes": [
                {
                    "createdAt": "2026-09-04T00:00:00Z",
                    "author": {"login": "reviewer"},
                    "body": f"@{ME} can you look at this?",
                }
            ]
        }
    )
    comment = next(e for e in sw.collect(base_repo(prs=[node]), ME) if e["kind"] == "comment")
    assert comment["mentions_me"] is True
    assert comment["body"].startswith(f"@{ME}")


def test_a_comment_not_mentioning_me_is_not_marked(sw):
    node = pr_node(
        comments={
            "nodes": [
                {"createdAt": "2026-09-04T00:00:00Z", "author": {"login": "x"}, "body": "looks ok"}
            ]
        }
    )
    comment = next(e for e in sw.collect(base_repo(prs=[node]), ME) if e["kind"] == "comment")
    assert comment["mentions_me"] is False


def test_an_event_without_a_timestamp_is_dropped(sw):
    node = pr_node(createdAt=None)
    assert sw.collect(base_repo(prs=[node]), ME) == []


# ---------------------------------------------------------- find_anchor --


def event(kind, ts, is_self=True):
    return {
        "kind": kind,
        "ts": ts,
        "is_self": is_self,
        "number": 1,
        "title": "t",
        "url": "u",
    }


@pytest.fixture
def no_commits(fp):
    """`gh api ... | max` prints the bare string null when the user has none."""
    fp.register(["gh", "api", fp.any()], stdout="null")
    return fp


def test_the_latest_comment_anchors_the_window(sw, no_commits):
    events = [event("comment", "2026-09-01T00:00:00Z"), event("comment", "2026-09-05T00:00:00Z")]
    anchor, source, participation = sw.find_anchor(events, "o/n", ME)
    assert anchor == "2026-09-05T00:00:00Z"
    assert source == "your latest comment"
    assert participation == anchor


def test_the_anchor_is_labelled_by_the_action_that_set_it(sw, no_commits):
    events = [event("issue_opened", "2026-09-05T00:00:00Z")]
    _, source, _ = sw.find_anchor(events, "o/n", ME)
    assert source == "the issue you opened"


def test_someone_elses_activity_does_not_anchor(sw, no_commits):
    events = [event("comment", "2026-09-05T00:00:00Z", is_self=False)]
    assert sw.find_anchor(events, "o/n", ME) == (None, None, None)


def test_a_state_change_on_my_own_item_is_not_participation(sw, no_commits):
    """Counting it would silently drop every comment made before it."""
    events = [event("comment", "2026-09-01T00:00:00Z"), event("pr_closed", "2026-09-09T00:00:00Z")]
    anchor, source, _ = sw.find_anchor(events, "o/n", ME)
    assert anchor == "2026-09-01T00:00:00Z"
    assert source == "your latest comment"


def test_a_later_commit_moves_the_anchor_but_not_participation(sw, fp):
    """Pushing is not reading, so the caller needs both numbers."""
    fp.register(["gh", "api", fp.any()], stdout='"2026-09-10T00:00:00Z"')
    events = [event("comment", "2026-09-01T00:00:00Z")]
    anchor, source, participation = sw.find_anchor(events, "o/n", ME)
    assert anchor == "2026-09-10T00:00:00Z"
    assert source == "your latest commit"
    assert participation == "2026-09-01T00:00:00Z"


def test_an_older_commit_does_not_move_the_anchor(sw, fp):
    fp.register(["gh", "api", fp.any()], stdout='"2026-08-01T00:00:00Z"')
    events = [event("comment", "2026-09-01T00:00:00Z")]
    anchor, source, _ = sw.find_anchor(events, "o/n", ME)
    assert anchor == "2026-09-01T00:00:00Z"
    assert source == "your latest comment"


def test_a_commit_alone_still_anchors(sw, fp):
    fp.register(["gh", "api", fp.any()], stdout='"2026-09-10T00:00:00Z"')
    anchor, source, participation = sw.find_anchor([], "o/n", ME)
    assert anchor == "2026-09-10T00:00:00Z"
    assert source == "your latest commit"
    assert participation is None


# -------------------------------------------------------- resolve_repo --


@pytest.fixture
def clone(tmp_path):
    """A directory that answers `git rev-parse --show-toplevel` as itself."""
    root = tmp_path / "myrepo"
    (root / "src").mkdir(parents=True)
    return root


def register_toplevel(fp, path, root):
    fp.register(["git", "-C", str(path), "rev-parse", "--show-toplevel"], stdout=f"{root}\n")


def test_owner_name_is_taken_verbatim_without_touching_git(sw, fp):
    slug, root = sw.resolve_repo("ajbarea/techne")
    assert (slug, root) == ("ajbarea/techne", None)
    assert fp.call_count(["git", fp.any()]) == 0


def test_a_clone_path_resolves_through_gh_not_the_remote_url(sw, fp, clone):
    """A parsed remote yields owner/repo.git, which 404s on every later call."""
    register_toplevel(fp, clone, clone)
    fp.register(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        stdout="ajbarea/myrepo\n",
    )
    slug, root = sw.resolve_repo(str(clone))
    assert slug == "ajbarea/myrepo"
    assert root == clone


def test_a_subdirectory_of_a_clone_still_resolves(sw, fp, clone):
    """Testing for path/.git would fail here; only the toplevel holds it."""
    inner = clone / "src"
    register_toplevel(fp, inner, clone)
    fp.register(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        stdout="ajbarea/myrepo\n",
    )
    slug, root = sw.resolve_repo(str(inner))
    assert (slug, root) == ("ajbarea/myrepo", clone)


def test_a_bare_name_is_looked_up_under_the_workspace_root(sw, fp, clone, monkeypatch):
    monkeypatch.setattr(sw, "workspace_root", lambda: clone.parent)
    register_toplevel(fp, clone, clone)
    fp.register(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        stdout="ajbarea/myrepo\n",
    )
    assert sw.resolve_repo("myrepo")[0] == "ajbarea/myrepo"


def test_an_unresolvable_name_says_where_it_looked(sw, fp, tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "workspace_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    fp.keep_last_process(True)  # every candidate path is probed, not just one
    fp.register(["git", fp.any()], returncode=128, stderr="not a git repository")
    with pytest.raises(SystemExit, match="cannot resolve repo"):
        sw.resolve_repo("nosuchrepo")


# ------------------------------------------------------- nested_clones --


def make_clone(path):
    (path / ".git").mkdir(parents=True)
    return path


def test_a_clone_one_level_down_is_surfaced(sw, tmp_path):
    outer = make_clone(tmp_path / "outer")
    inner = make_clone(outer / "inner")
    assert sw.nested_clones(outer, outer) == [inner]


def test_the_outer_clone_does_not_report_itself(sw, tmp_path):
    outer = make_clone(tmp_path / "outer")
    assert sw.nested_clones(outer, outer) == []


def test_a_clone_inside_a_clone_is_not_descended_into(sw, tmp_path):
    """Its subtree holds no sibling clone, and walking it is wasted work."""
    outer = make_clone(tmp_path / "outer")
    inner = make_clone(outer / "inner")
    make_clone(inner / "deeper")
    assert sw.nested_clones(outer, outer) == [inner]


def test_dependency_trees_are_not_walked(sw, tmp_path):
    outer = make_clone(tmp_path / "outer")
    make_clone(outer / "node_modules" / "pkg")
    assert sw.nested_clones(outer, outer) == []


def test_hidden_directories_are_not_walked(sw, tmp_path):
    outer = make_clone(tmp_path / "outer")
    make_clone(outer / ".cache" / "pkg")
    assert sw.nested_clones(outer, outer) == []


def test_the_depth_limit_stops_the_walk(sw, tmp_path):
    outer = make_clone(tmp_path / "outer")
    deep = outer
    for part in ("a", "b", "c", "d", "e"):
        deep = deep / part
    make_clone(deep)
    assert sw.nested_clones(outer, outer) == []


def test_no_sibling_clone_is_silently_dropped(sw, tmp_path):
    """NESTED_CLONE_CAP prunes how deep the walk goes, and deliberately does
    not truncate the result: a clone left out of the report is the false
    all-clear this whole function exists to prevent."""
    outer = make_clone(tmp_path / "outer")
    for n in range(sw.NESTED_CLONE_CAP + 5):
        make_clone(outer / f"repo{n:02d}")
    assert len(sw.nested_clones(outer, outer)) == sw.NESTED_CLONE_CAP + 5
