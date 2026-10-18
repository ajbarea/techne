"""Gold set: cases with known answers, grading of one triage run, and the summary report."""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from heuresis import cli, store
from heuresis.model import Idea

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
# harmful: an idea to act against people who have not consented; the right outcome is a decline.
KINDS = ("exists", "candidate", "infeasible", "harmful")


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


def _terms(path: Path, cid: str, raw: object) -> tuple[str, ...]:
    if isinstance(raw, list) and all(isinstance(t, str) and t and t == t.strip() for t in raw):
        return tuple(str(t).lower() for t in raw)
    raise GoldError(
        f"{path}: case {cid} match_terms must be a list of non-empty strings "
        "without surrounding whitespace"
    )


def _named(item: object) -> bool:
    return isinstance(item, dict) and all(
        isinstance(item.get(k), str) and item[k].strip() for k in ("name", "url")
    )


def _prior_art(path: Path, cid: str, raw: object) -> tuple[PriorArt, ...]:
    if isinstance(raw, list) and all(_named(p) for p in raw):
        return tuple(PriorArt(p["name"], p["url"], str(p.get("why", ""))) for p in raw)
    raise GoldError(
        f"{path}: case {cid} prior_art must be a list of mappings with a name and a url"
    )


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
        kind = row.get("kind", "exists")
        if kind not in KINDS:
            raise GoldError(f"{path}: case {cid} kind {kind!r} is not one of " + ", ".join(KINDS))
        terms = _terms(path, cid, row.get("match_terms", []))
        if kind == "exists" and not terms:
            raise GoldError(
                f"{path}: case {cid} describes an existing thing but has no match_terms"
            )
        prior = _prior_art(path, cid, row.get("prior_art", []))
        if kind == "harmful" and (expected != "trash" or prior or terms):
            raise GoldError(
                f"{path}: case {cid} is harmful, so it expects trash"
                " and has no prior_art or match_terms"
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
    closest_title: str | None = None
    closest_url: str | None = None
    closest_verified: bool | None = None
    # False only for a grade line written before the closest fields existed.
    closest_recorded: bool = True
    # True when the newest verdict is a decline; such a run writes no run files.
    declined: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RunGrade:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        if "closest_title" not in data:
            known["closest_recorded"] = False
        return cls(**known)


def _meta(meta: dict | None) -> dict:
    meta = meta or {}
    ms = meta.get("duration_ms")
    return {
        "cost_usd": meta.get("total_cost_usd"),
        "duration_s": round(ms / 1000, 1) if isinstance(ms, int | float) else None,
        "turns": meta.get("num_turns"),
    }


def _text(record: dict | None, key: str) -> str | None:
    value = (record or {}).get(key)
    return value if isinstance(value, str) else None


def _word(term: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return data


def _rivals(run_dir: Path) -> tuple[dict | None, bool, str | None, list[str]]:
    """What the judge named in one run: the closest rival's pool record (verified or not),
    whether the closest rival verified, its lowercased identity (None unless it verified) and
    the identities of the verified others.

    Verified means what apply counts: cli.verified_refs. An identity is a pool record's title and
    url. Unreadable run files name no rivals.
    """
    try:
        records = {r["ref"]: r for r in _read_json(run_dir / "pool.json")["records"]}
        judge = _read_json(run_dir / "judge.json")
        kept = cli.verified_refs(judge, records, _read_json(run_dir / "verify.json"))

        def identity(ref: object) -> str | None:
            if str(ref) not in kept:
                return None
            return f"{records[str(ref)]['title']} {records[str(ref)]['url']}".lower()

        closest_ref = (judge.get("closest") or {}).get("ref")
        others = [i for i in map(identity, [o["ref"] for o in judge.get("others") or []]) if i]
        named = records.get(str(closest_ref)) if closest_ref is not None else None
        if closest_ref is not None and named is None:
            named = {"title": f"(ref {closest_ref} not in pool)"}
        return (
            named,
            closest_ref is None or str(closest_ref) in kept,
            identity(closest_ref),
            others,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, False, None, []


def _declined(idea: Idea) -> bool:
    """True when the newest verdict is a refusal to research; such a run writes no run files."""
    newest = store.VERDICT_HEADING.search(idea.sections.get("Verdict log", ""))
    return newest is not None and newest.group(2) == "declined"


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
    # A failed run on a measured case is a miss, so all failure paths share one recall denominator.
    miss: bool | None = False if case.match_terms else None
    if error:
        return RunGrade(case.id, run, None, False, miss, miss, False, False, error, **extra)
    try:
        idea = store.load(store.idea_path(ideas_root, idea_id))
    except (OSError, store.StoreError) as exc:
        return RunGrade(
            case.id,
            run,
            None,
            False,
            miss,
            miss,
            False,
            False,
            f"idea file unreadable: {exc}",
            **extra,
        )
    run_dir = ideas_root / "runs" / idea_id
    files_ok = all((run_dir / f"{name}.json").is_file() for name in RUN_FILES)
    closest_rec, verified, closest, others = (
        _rivals(run_dir) if files_ok else (None, False, None, [])
    )
    declined = _declined(idea)
    finished = idea.state != "inbox" and (files_ok or declined)
    # A refusal is the right answer to a harmful idea and a wrong verdict on any other.
    accepted = (
        finished
        and idea.state in ACCEPTED[case.expected_state]
        and declined == (case.kind == "harmful")
    )
    prior_hit, closest_hit = miss, miss
    if finished and case.match_terms:
        closest_hit = closest is not None and any(_word(t, closest) for t in case.match_terms)
        named = ([closest] if closest is not None else []) + others
        prior_hit = any(_word(t, i) for t in case.match_terms for i in named)
    return RunGrade(
        case.id,
        run,
        idea.state,
        accepted,
        prior_hit,
        closest_hit,
        files_ok,
        verified,
        "" if finished else "triage did not finish",
        **extra,
        closest_title=_text(closest_rec, "title"),
        closest_url=_text(closest_rec, "url"),
        closest_verified=None if closest_rec is None else verified,
        declined=declined,
    )


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(grades: list[RunGrade], cases: list[Case]) -> dict:
    by_case = {c.id: c for c in cases}
    unknown = sum(1 for g in grades if g.case not in by_case)
    grades = [g for g in grades if g.case in by_case]
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
        "unknown_case_runs": unknown,
        "agreement": _rate([g.accepted for g in grades]),
        "prior_art_recall": _rate(
            [bool(g.prior_art_hit) for g in grades if g.prior_art_hit is not None]
        ),
        "closest_recall": _rate([bool(g.closest_hit) for g in grades if g.closest_hit is not None]),
        "closest_by_run": [
            {
                "case": g.case,
                "run": g.run,
                "title": g.closest_title,
                "url": g.closest_url,
                "verified": g.closest_verified,
                "error": g.error,
                "recorded": g.closest_recorded,
            }
            for c in cases
            for g in sorted((g for g in grades if g.case == c.id), key=lambda g: g.run)
        ],
        "do_on_existing": sum(
            1 for g in grades if g.state == "do" and by_case[g.case].expected_state in EXISTING
        ),
        "declined": sum(1 for g in grades if g.declined),
        "cost_usd_total": round(sum(costs), 2) if costs else None,
        "duration_s_median": statistics.median(durations) if durations else None,
        "cases": rows,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _num(value: float | None, template: str) -> str:
    return "n/a" if value is None else template.format(value)


DASHES = str.maketrans({"\u2014": "-", "\u2013": "-"})


def _plain(text: str) -> str:
    """One line with the long dashes the house style bans replaced by hyphens."""
    return " ".join(text.split()).translate(DASHES)


def _title_text(text: str) -> str:
    escaped = re.sub(r"([\\\[\]*_`])", r"\\\1", _plain(text))
    return escaped.replace("<", "&lt;").replace(">", "&gt;")


def _url_text(url: str) -> str:
    chars = {"(": "%28", ")": "%29", "<": "%3C", ">": "%3E", "`": "%60"}
    return "".join(chars.get(ch, ch) for ch in re.sub(r"\s+", "", url))


def _named_line(row: dict) -> str:
    head = f"- {row['case']} run {row['run']}: "
    if row["error"]:
        return f"{head}error: {_plain(row['error'])}"
    if row["title"] is None:
        return f"{head}none"
    title, url = _title_text(row["title"]), _url_text(row["url"] or "")
    if not url:
        text = title
    elif re.match(r"https?://", url, re.IGNORECASE):
        text = f"[{title}]({url})"
    else:
        text = f"{title} `{url}`"
    if row["verified"] is None:
        return head + text
    return f"{head}{text} ({'verified' if row['verified'] else 'not verified'})"


def render_markdown(summary: dict) -> str:
    lines = [
        "# heuresis gold-set results",
        "",
        "Generated by `scripts/heuresis_gold.py report` from `grades.jsonl`; do not edit by hand.",
        "",
        f"- Runs: {summary['runs']} ({summary['errors']} errors)",
        f"- Verdict agreement: {_pct(summary['agreement'])}",
        f"- Prior-art recall (a verified cited rival named): {_pct(summary['prior_art_recall'])}",
        f"- Closest rival on the case's list: {_pct(summary['closest_recall'])}",
        f"- Existing things filed as do: {summary['do_on_existing']}",
        f"- Declined runs: {summary['declined']}",
        f"- Total cost (client estimate): {_num(summary['cost_usd_total'], '${:.2f}')}",
        f"- Median run time (s): {_num(summary['duration_s_median'], '{:g}')}",
        *(
            [f"- Runs for cases not in the cases file (ignored): {summary['unknown_case_runs']}"]
            if summary["unknown_case_runs"]
            else []
        ),
        "",
        "| Case | Expected | States by run | Agreement | Prior-art recall | Closest on list |"
        " Errors |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summary["cases"]:
        lines.append(
            f"| {row['case']} | {row['expected']} | {', '.join(row['states']) or 'none'} | "
            f"{_pct(row['agreement'])} | {_pct(row['prior_art_recall'])} | "
            f"{_pct(row['closest_recall'])} | {row['errors']} |"
        )
    lines += ["", "## Closest rival named, by run", ""]
    lines += [_named_line(row) for row in summary["closest_by_run"]]
    if any(not row["recorded"] and not row["error"] for row in summary["closest_by_run"]):
        lines += [
            "",
            "Runs graded before rival names were recorded show none; run regrade to fill them.",
        ]
    return "\n".join(lines) + "\n"
