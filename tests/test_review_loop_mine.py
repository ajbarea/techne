"""review_loop_mine reads review transcripts the way the fleet writes them."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import review_loop_mine as m  # ty: ignore[unresolved-import]

SLUGS = ["boundary-input", "claim-code-drift", "unmirrored-parallel-guard", "vacuous-guard"]
KNOWN = {"techne", "klepsydra"}


@pytest.mark.parametrize(
    ("report", "want"),
    [
        # A section heading, bold-led findings and their detail bullets.
        (
            "## Should-fix\n\n**S1. Drift** (claim-code drift)\n- detail\n- more\n"
            "**S2. Edge** [boundary-input]\n- detail\n## Nits\n- small",
            [("should-fix", "claim-code-drift"), ("should-fix", "boundary-input")],
        ),
        # Top-level bullets count when the section has no stronger leads.
        (
            "**Should-fix**\n- `a.py:1` [vacuous-guard]: x\n- `b.py:2` [boundary-input]: y\n"
            "**Nits**\n- z",
            [("should-fix", "vacuous-guard"), ("should-fix", "boundary-input")],
        ),
        # A numbered bold lead is a finding, not a section, so its detail is not counted.
        (
            "## Findings\n**1. Blocking: heads over-count**\n- **Class:** `boundary-input`\n"
            "- **Anchor:** x\n**2. Minor: other**\n- **Class:** `claim-code-drift`",
            [("blocking", "boundary-input")],
        ),
        # Negations and summaries open nothing.
        (
            "**Blocking:** none.\nNo Should-fix findings.\n"
            "**Round 2 is not clean.** One should-fix is open.\n**Should-fix:** none.",
            [],
        ),
        # A `new:` tag, and an untagged finding.
        (
            "1. **Should-fix** `new: retry bypasses confirm` x\n2. **Blocking** no tag here",
            [("should-fix", "new: retry-bypasses-confirm"), ("blocking", "")],
        ),
        # A whole bold line naming its severity is a finding, and its field bullets are not.
        (
            "**[Should-fix] boundary-input `a.py:230`: crash on empty**\n- **Verdict:** x\n"
            "- **Fix:** y\n**[Should-fix] claim-code-drift `b.py:1`: stale docstring**\n"
            "- **Verdict:** z\n**[Minor] vacuous-guard `c.py:3`: nit**\n- detail",
            [("should-fix", "boundary-input"), ("should-fix", "claim-code-drift")],
        ),
        # A verify round's status of an earlier finding is not a new finding.
        (
            "**Round-1 findings**\n- **Copy branch (Should-fix 2): fixed.**\n"
            "1. **Should-fix** the retry is never addressed when locked [boundary-input]\n"
            "1. ✅ **Should-fix** resolved\n## New findings\n1. **Should-fix** [boundary-input] x",
            [("should-fix", "boundary-input"), ("should-fix", "boundary-input")],
        ),
        # A fixed finding written as a heading opens no section.
        (
            "### Finding 1 (Blocking): fixed, CONFIRMED\n- detail\n- more\n"
            "### New findings\n1. **Should-fix** [boundary-input] x",
            [("should-fix", "boundary-input")],
        ),
        # elenchus's own field format under a numbered heading counts once.
        (
            "### 1. Should-fix: stale claim\n- **Severity** — Should-fix\n"
            "- **Class** — `claim-code-drift`\n### 2. Minor: other\n- **Class** — `vacuous-guard`",
            [("should-fix", "claim-code-drift")],
        ),
        # JSON reports carry the class beside the severity.
        (
            '[{\n "class": "unmirrored-parallel-guard",\n "severity": "Should-fix",\n "x": 1\n}]',
            [("should-fix", "unmirrored-parallel-guard")],
        ),
    ],
)
def test_parse_findings(report: str, want: list[tuple[str, str]]) -> None:
    assert m.parse_findings(report, SLUGS) == want


@pytest.mark.parametrize(
    ("prompt", "want"),
    [
        ("Review https://github.com/ajbarea/techne/pull/214 now", ("ajbarea", "techne", "214")),
        ("independent reviewer for klepsydra PR #82, round 2", ("", "klepsydra", "82")),
        ("round 3 for techne#230", ("", "techne", "230")),
        # "of" is not a repo: the worktree path names it, and PR #90 the number.
        ("Review of PR #90 in /home/u/ajsoftworks/klepsydra/.claude/x", ("", "klepsydra", "90")),
        ("review this", ("", "", "")),
        # An explicit owner/name wins over the worktree the reviewer stands in.
        (
            "Review acme/other-tool PR #32 from /home/u/ajsoftworks/techne/.claude/wt",
            ("acme", "other-tool", "32"),
        ),
        ("Review Techne#5", ("", "techne", "5")),
        # Shapes seen in the fleet's prompts; each must yield its PR number.
        (
            "Review pull request #212 in the GitHub repo ajbarea/sphragis",
            ("ajbarea", "sphragis", "212"),
        ),
        ("PR: ajbarea/sphragis #204, round 2", ("ajbarea", "sphragis", "204")),
        ("klepsydra pull request #9: review it", ("", "klepsydra", "9")),
        (
            "Read /home/u/ajsoftworks/techne/plugins/techne/skills/elenchus/SKILL.md. "
            "Review PR #82 in /home/u/ajsoftworks/klepsydra/.claude/worktrees/x",
            ("", "klepsydra", "82"),
        ),
        # The repo the reviewer stands in wins over a PR only cited for context.
        (
            "Review PR #113 in /home/u/ajsoftworks/klepsydra/.claude/wt; see techne#217 for why",
            ("", "klepsydra", "113"),
        ),
    ],
)
def test_identify(prompt: str, want: tuple[str, str, str]) -> None:
    assert m.identify(prompt, KNOWN) == want


def test_stated_counts() -> None:
    assert m.stated_counts("No blocking findings; two Should-fix and one nit.") == {
        "blocking": 0,
        "should-fix": 2,
    }


def transcript(path: pathlib.Path, prompt: str, when: str, report: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    recs = [
        {"type": "user", "timestamp": when, "message": {"content": prompt}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": report}]}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return path


def test_mine_checks_the_catalog_as_it_stood(tmp_path: pathlib.Path) -> None:
    hist = [
        ("2026-10-22T00:00:00+00:00", ["boundary-input"]),
        ("2026-10-25T00:00:00+00:00", ["boundary-input", "vacuous-guard"]),
    ]
    sub = tmp_path / "projects" / "p" / "s" / "subagents"
    report = "## Should-fix\n1. x [boundary-input]\n2. y [vacuous-guard]\n3. z untagged"
    early = transcript(sub / "a.jsonl", "Review techne#1, round 1", "2026-10-23T00:00:00Z", report)
    late = transcript(sub / "b.jsonl", "Review techne#1, round 2", "2026-10-26T00:00:00Z", report)
    old = transcript(sub / "c.jsonl", "Review techne#2", "2026-10-01T00:00:00Z", report)
    rounds = m.mine([early, late, old], "2026-10-22T00:00:00+00:00", hist, KNOWN)
    assert [r.round for r in rounds] == [1, 2]
    assert [f.catalogued for f in rounds[0].findings] == [True, False, None]
    assert [f.catalogued for f in rounds[1].findings] == [True, True, None]
    s = m.summarize(rounds, {"techne"}, {"boundary-input", "vacuous-guard"})
    assert s["already_catalogued"] == 3
    assert s["not_yet_catalogued"] == 1
    assert s["untagged"] == 2
    assert s["before_catalog"] == 0
    assert s["rounds_per_pr_by_repo"] == {"techne": {"prs": 1, "median_rounds": 2, "max_rounds": 2}}


def test_private_repos_fold_into_one_row(tmp_path: pathlib.Path) -> None:
    sub = tmp_path / "projects" / "p" / "s" / "subagents"
    a = transcript(sub / "a.jsonl", "Review klepsydra#5", "2026-10-23T00:00:00Z", "fine")
    b = transcript(sub / "b.jsonl", "Review techne#6", "2026-10-23T00:00:00Z", "fine")
    rounds = m.mine([a, b], "2026-10-22T00:00:00+00:00", [], KNOWN)
    rows = m.summarize(rounds, {"techne"}, set())["rounds_per_pr_by_repo"]
    assert set(rows) == {"techne", "private repos"}
    assert "klepsydra" not in m.to_markdown(m.summarize(rounds, {"techne"}, set()), "2026-10-22")


def test_rounds_before_the_catalog_are_counted_apart(tmp_path: pathlib.Path) -> None:
    hist = [("2026-10-25T00:00:00+00:00", ["boundary-input"])]
    sub = tmp_path / "projects" / "p" / "s" / "subagents"
    report = "## Should-fix\n1. x [boundary-input]"
    a = transcript(sub / "a.jsonl", "Review techne#1", "2026-10-23T00:00:00Z", report)
    rounds = m.mine([a], "2026-10-22T00:00:00+00:00", hist, KNOWN)
    s = m.summarize(rounds, {"techne"}, {"boundary-input"})
    assert (s["before_catalog"], s["tagged"], s["already_catalogued"]) == (1, 0, 0)


def test_repeated_new_classes_never_name_a_private_repo(tmp_path: pathlib.Path) -> None:
    sub = tmp_path / "projects" / "p" / "s" / "subagents"
    report = "## Should-fix\n1. x `new: lost lock`"
    rs = [
        transcript(sub / f"{n}.jsonl", f"Review klepsydra#{n}", "2026-10-23T00:00:00Z", report)
        for n in (1, 2)
    ]
    hist = [("2026-10-22T00:00:00+00:00", ["boundary-input"])]
    s = m.summarize(m.mine(rs, "2026-10-22T00:00:00+00:00", hist, KNOWN), {"techne"}, set())
    assert s["repeated_new_never_added"] == {"new: lost-lock": ["a private repo", "a private repo"]}
    assert "klepsydra" not in m.to_markdown(s, "2026-10-22") + json.dumps(s)


@pytest.mark.parametrize(
    ("key", "want"),
    [
        ("techne#5", "techne#5"),
        ("Techne#5", "Techne#5"),
        ("techne@0f3a-uuid", "techne (no PR number)"),
        ("klepsydra#5", "a private repo"),
    ],
)
def test_label_key(key: str, want: str) -> None:
    assert m.label_key(key, {"techne"}) == want


@pytest.mark.parametrize(
    "prompt",
    ["You implement review fixes on klepsydra PR #91", "Fix round 4 for techne#5 after review"],
)
def test_implementers_are_not_review_rounds(tmp_path: pathlib.Path, prompt: str) -> None:
    a = transcript(tmp_path / "a.jsonl", prompt, "2026-10-23T00:00:00Z", "done")
    assert m.mine([a], "2026-10-22T00:00:00+00:00", [], KNOWN) == []
