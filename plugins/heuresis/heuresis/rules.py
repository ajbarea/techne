"""Rules a verdict must meet before it is recorded. They run in code so no prompt can skip them."""

from __future__ import annotations

import dataclasses
import datetime as dt

from heuresis.model import FACETS, PAPER_SOURCES, Verdict

# An idea parked for thin evidence is searched again after a quarter, long enough for new
# preprints, launches and patents to appear, short enough that it is still remembered.
REVISIT_AFTER_INSUFFICIENT = dt.timedelta(days=90)


def _do_problems(v: Verdict, closest: dict | None, closest_verified: bool) -> list[str]:
    problems = []
    if v.type is None:
        problems.append("type missing")
    if closest is None:
        problems.append("no closest rival named")
    else:
        if not closest_verified:
            problems.append("closest rival could not be verified")
        differs = closest.get("differs") or {}
        empty = [facet for facet in FACETS if not str(differs.get(facet, "")).strip()]
        if empty:
            problems.append("closest rival lacks a comparison on " + ", ".join(empty))
    if not any(c.source in PAPER_SOURCES and c.status == "ok" for c in v.coverage):
        problems.append("no paper source returned results")
    return problems


def enforce(
    v: Verdict,
    *,
    closest: dict | None,
    closest_verified: bool,
    known_ids: set[str],
    today: dt.date,
) -> Verdict:
    revisit = (today + REVISIT_AFTER_INSUFFICIENT).isoformat()
    if v.state == "merged" and v.duplicate_of not in known_ids:
        raise ValueError(f"merged verdict names duplicate_of {v.duplicate_of!r}, not an idea here")
    if v.state == "do":
        problems = _do_problems(v, closest, closest_verified)
        if problems:
            reason = f"insufficient evidence: {'; '.join(problems)}. Judge proposed do: {v.reason}"
            return dataclasses.replace(v, state="later", reason=reason, revisit=revisit)
    if v.state == "later" and not v.revisit:
        return dataclasses.replace(v, revisit=revisit)
    return v
