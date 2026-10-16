"""The verdict rules the judge cannot talk its way past."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from heuresis import rules
from heuresis.model import Coverage, Verdict

TODAY = dt.date(2026, 10, 15)
FULL = {"domain": "d", "purpose": "p", "mechanism": "m", "evaluation": "e"}
OK_PAPERS = [
    Coverage("openalex", "ok", 3, 8),
    Coverage("lens", "skipped", note="no LENS_API_TOKEN"),
]


def do(**kw: Any) -> Verdict:
    base: dict[str, Any] = {
        "date": "2026-10-15",
        "origin": "triage",
        "state": "do",
        "reason": "new",
        "type": "tool",
        "coverage": OK_PAPERS,
    }
    base.update(kw)
    return Verdict(**base)


def enforce(
    v: Verdict,
    closest: dict | None = None,
    verified: bool = True,
    known: frozenset[str] = frozenset(),
) -> Verdict:
    return rules.enforce(
        v, closest=closest, closest_verified=verified, known_ids=set(known), today=TODAY
    )


def test_do_with_verified_full_rival_and_paper_results_stands():
    out = enforce(do(), closest={"url": "u", "differs": FULL})
    assert out.state == "do"


@pytest.mark.parametrize(
    ("verdict", "closest", "verified", "problem"),
    [
        (do(), None, True, "no closest rival"),
        (do(), {"url": "u", "differs": FULL}, False, "closest rival could not be verified"),
        (do(), {"url": "u", "differs": {**FULL, "evaluation": ""}}, True, "evaluation"),
        (
            do(coverage=[Coverage("openalex", "failed", 3, 0, "http 503")]),
            {"url": "u", "differs": FULL},
            True,
            "no paper source",
        ),
        (do(type=None), {"url": "u", "differs": FULL}, True, "type"),
    ],
)
def test_do_without_evidence_is_demoted_to_later(verdict, closest, verified, problem):
    out = enforce(verdict, closest, verified)
    assert out.state == "later"
    assert out.reason.startswith("insufficient evidence:")
    assert problem in out.reason
    assert out.revisit == (TODAY + rules.REVISIT_AFTER_INSUFFICIENT).isoformat()
    assert out.type == verdict.type


def test_merged_needs_a_known_duplicate():
    with pytest.raises(ValueError, match="duplicate_of"):
        enforce(do(state="merged", duplicate_of="nope"))
    known = frozenset({"2026-10-01-x"})
    out = enforce(do(state="merged", duplicate_of="2026-10-01-x"), known=known)
    assert out.state == "merged"


def test_later_without_revisit_gets_the_default():
    out = enforce(do(state="later"))
    assert out.revisit == (TODAY + rules.REVISIT_AFTER_INSUFFICIENT).isoformat()


def test_trash_passes_through():
    assert enforce(do(state="trash", type=None)).state == "trash"
