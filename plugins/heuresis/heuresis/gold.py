"""Gold set: cases with known answers, grading of one triage run, and the summary report."""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from heuresis import store

# The states a run may file for each expected label. An existing thing filed as trash or merged
# is right; "later" cases have close prior art with a plausible difference, so trash also agrees.
ACCEPTED: dict[str, frozenset[str]] = {
    "trash": frozenset({"trash", "merged"}),
    "later": frozenset({"later", "trash", "merged"}),
    "do_or_later": frozenset({"do", "later"}),
}
# Labels whose cases describe something that already exists; filing one as "do" is the failure
# the gold set measures first.
EXISTING = frozenset({"trash", "later"})
CASE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
RUN_FILES = ("restate", "pool", "judge", "verify")


class GoldError(Exception):
    """A cases file that cannot be used."""


@dataclass(frozen=True)
class PriorArt:
    name: str
    url: str
    why: str = ""


@dataclass(frozen=True)
class Case:
    id: str
    idea: str
    expected_state: str
    match_terms: tuple[str, ...]
    prior_art: tuple[PriorArt, ...] = ()
    kind: str = "exists"
    notes: str = ""


def load_cases(path: Path) -> list[Case]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise GoldError(f"{path}: no cases list")
    cases: list[Case] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise GoldError(f"{path}: case {row!r} is not a mapping")
        cid = str(row.get("id", ""))
        if not CASE_ID.fullmatch(cid):
            raise GoldError(f"{path}: case id {cid!r} is not lowercase kebab-case")
        if cid in seen:
            raise GoldError(f"{path}: duplicate case id {cid}")
        seen.add(cid)
        idea = str(row.get("idea") or "").strip()
        if not idea:
            raise GoldError(f"{path}: case {cid} has an empty idea")
        expected = str(row.get("expected_state", ""))
        if expected not in ACCEPTED:
            raise GoldError(
                f"{path}: case {cid} expected_state {expected!r} is not one of "
                + ", ".join(ACCEPTED)
            )
        kind = str(row.get("kind") or "exists")
        terms = tuple(str(t).lower() for t in row.get("match_terms") or [])
        if kind == "exists" and not terms:
            raise GoldError(
                f"{path}: case {cid} describes an existing thing but has no match_terms"
            )
        prior = tuple(
            PriorArt(str(p["name"]), str(p["url"]), str(p.get("why", "")))
            for p in row.get("prior_art") or []
        )
        cases.append(Case(cid, idea, expected, terms, prior, kind, str(row.get("notes", ""))))
    return cases


@dataclass
class RunGrade:
    case: str
    run: int
    state: str | None
    accepted: bool
    prior_art_hit: bool | None
    closest_hit: bool | None
    files_ok: bool
    verified_ok: bool
    error: str = ""
    cost_usd: float | None = None
    duration_s: float | None = None
    turns: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RunGrade:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def _meta(meta: dict | None) -> dict:
    meta = meta or {}
    ms = meta.get("duration_ms")
    return {
        "cost_usd": meta.get("total_cost_usd"),
        "duration_s": round(ms / 1000, 1) if isinstance(ms, int | float) else None,
        "turns": meta.get("num_turns"),
    }


def grade_run(
    case: Case,
    run: int,
    ideas_root: Path,
    idea_id: str,
    *,
    error: str = "",
    meta: dict | None = None,
) -> RunGrade:
    extra = _meta(meta)
    if error:
        return RunGrade(case.id, run, None, False, None, None, False, False, error, **extra)
    try:
        idea = store.load(store.idea_path(ideas_root, idea_id))
    except (OSError, store.StoreError) as exc:
        return RunGrade(
            case.id,
            run,
            None,
            False,
            None,
            None,
            False,
            False,
            f"idea file unreadable: {exc}",
            **extra,
        )
    run_dir = ideas_root / "runs" / idea_id
    files_ok = all((run_dir / f"{name}.json").is_file() for name in RUN_FILES)
    closest = idea.sections.get("Closest work", "").lower()
    first = closest.split("**also:**", 1)[0]
    measured = bool(case.match_terms)
    prior_hit = any(t in closest for t in case.match_terms) if measured else None
    closest_hit = any(t in first for t in case.match_terms) if measured else None
    verified = False
    if files_ok:
        try:
            judge = json.loads((run_dir / "judge.json").read_text())
            checks = json.loads((run_dir / "verify.json").read_text())
            ref = (judge.get("closest") or {}).get("ref")
            verified = ref is None or (checks.get(ref) or {}).get("ok") is True
        except (OSError, ValueError, AttributeError):
            verified = False
    finished = idea.state != "inbox" and files_ok
    return RunGrade(
        case.id,
        run,
        idea.state,
        finished and idea.state in ACCEPTED[case.expected_state],
        prior_hit if finished else (False if measured else None),
        closest_hit if finished else (False if measured else None),
        files_ok,
        verified,
        "" if finished else "triage did not finish",
        **extra,
    )


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(grades: list[RunGrade], cases: list[Case]) -> dict:
    by_case = {c.id: c for c in cases}
    rows = []
    for case in cases:
        mine = [g for g in grades if g.case == case.id]
        states = [g.state or "error" for g in mine]
        rows.append(
            {
                "case": case.id,
                "expected": case.expected_state,
                "runs": len(mine),
                "states": states,
                "distinct_states": len(set(states)),
                "agreement": _rate([g.accepted for g in mine]),
                "prior_art_recall": _rate(
                    [bool(g.prior_art_hit) for g in mine if g.prior_art_hit is not None]
                ),
                "closest_recall": _rate(
                    [bool(g.closest_hit) for g in mine if g.closest_hit is not None]
                ),
                "errors": sum(1 for g in mine if g.error),
            }
        )
    costs = [g.cost_usd for g in grades if g.cost_usd is not None]
    durations = [g.duration_s for g in grades if g.duration_s is not None]
    return {
        "runs": len(grades),
        "errors": sum(1 for g in grades if g.error),
        "agreement": _rate([g.accepted for g in grades]),
        "prior_art_recall": _rate(
            [bool(g.prior_art_hit) for g in grades if g.prior_art_hit is not None]
        ),
        "closest_recall": _rate([bool(g.closest_hit) for g in grades if g.closest_hit is not None]),
        "do_on_existing": sum(
            1 for g in grades if g.state == "do" and by_case[g.case].expected_state in EXISTING
        ),
        "cost_usd_total": round(sum(costs), 2) if costs else None,
        "duration_s_median": statistics.median(durations) if durations else None,
        "cases": rows,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render_markdown(summary: dict) -> str:
    lines = [
        "# heuresis gold-set results",
        "",
        "Generated by `scripts/heuresis_gold.py report` from `grades.jsonl`; do not edit by hand.",
        "",
        f"- Runs: {summary['runs']} ({summary['errors']} errors)",
        f"- Verdict agreement: {_pct(summary['agreement'])}",
        f"- Prior-art recall (named anywhere in Closest work): {_pct(summary['prior_art_recall'])}",
        f"- Closest-rival recall (named as the closest): {_pct(summary['closest_recall'])}",
        f"- Existing things filed as do: {summary['do_on_existing']}",
        f"- Total cost (client estimate): {summary['cost_usd_total']}",
        f"- Median run time (s): {summary['duration_s_median']}",
        "",
        "| Case | Expected | States by run | Agreement | Prior-art recall | Closest recall |"
        " Errors |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summary["cases"]:
        lines.append(
            f"| {row['case']} | {row['expected']} | {', '.join(row['states']) or 'none'} | "
            f"{_pct(row['agreement'])} | {_pct(row['prior_art_recall'])} | "
            f"{_pct(row['closest_recall'])} | {row['errors']} |"
        )
    return "\n".join(lines) + "\n"
