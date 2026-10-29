#!/usr/bin/env python3
"""The machine-wide elenchus findings ledger: every reader's findings, for every author.

    ledger.py append --repo R --pr N --round K --severity Should-fix --class SLUG --line "..."
    ledger.py checklist [--days 7]
    ledger.py fold --catalog <bug-classes.md> [--since ISO] [--days 7]

`append` adds one finding to $XDG_STATE_HOME/elenchus/findings.jsonl (default
~/.local/state/elenchus/), append-only and locked, so concurrent readers never interleave.
`checklist` is the escalation ladder: each class seen in at least two PRs in the last DAYS
becomes an item the author walks before asking for review, and one seen in three or more is
marked as needing a mechanical check. `fold` turns the ledger since SINCE into the daily
catalog plan (JSON on stdout): incidents for classes the catalog holds, `new:` classes seen
in two or more PRs, and the ladder, deduplicated against the catalog's slugs. Pure standard
library; runs on python3 3.9 or newer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import pathlib
import re
import sys
from collections import defaultdict

SLUG = re.compile(r"^(?:[a-z0-9]+(?:-[a-z0-9]+)*|new: [a-z0-9]+(?:-[a-z0-9]+)*)$")
SEVERITIES = ("Blocking", "Should-fix")
CATALOG_SLUG = re.compile(r"^### (?:\d+\. )?([a-z0-9]+(?:-[a-z0-9]+)*): ", re.M)
RETIRED = re.compile(r"^- \*\*Retired:\*\*", re.M)
CHECKLIST_AT, MECHANICAL_AT = 2, 3
UTC = dt.timezone.utc  # noqa: UP017  # dt.UTC needs 3.11; this runs on 3.9


def ledger_path() -> pathlib.Path:
    state = os.environ.get("XDG_STATE_HOME") or str(pathlib.Path.home() / ".local" / "state")
    return pathlib.Path(state) / "elenchus" / "findings.jsonl"


def normalize_class(raw: str) -> str:
    raw = raw.strip().strip("`")
    if raw.lower().startswith("new:"):
        name = re.sub(r"[^a-z0-9]+", "-", raw[4:].strip().lower()).strip("-")
        return f"new: {name}"
    return raw.lower()


def append(args: argparse.Namespace) -> int:
    cls = normalize_class(args.cls)
    if not SLUG.match(cls):
        print(f"ledger: class {args.cls!r} is not a catalog slug or `new: <name>`", file=sys.stderr)
        return 2
    rec = {
        "ts": dt.datetime.now(UTC).isoformat(timespec="seconds"),
        "repo": args.repo.strip(),
        "pr": str(args.pr).lstrip("#"),
        "round": args.round,
        "severity": args.severity,
        "class": cls,
        "line": " ".join(args.line.split())[:300],
    }
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"ledger: recorded {cls} for {rec['repo']}#{rec['pr']} r{rec['round']}")
    return 0


def aware(when: dt.datetime) -> dt.datetime:
    """A time with no zone is UTC, so every comparison is between aware times."""
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def clean(rec: object) -> dict | None:
    """A record with every field present and of its type, normalized; None when it is not."""
    if not isinstance(rec, dict):
        return None
    try:
        when = aware(dt.datetime.fromisoformat(str(rec["ts"])))
        cls, repo = rec["class"], rec["repo"]
        if not (isinstance(cls, str) and SLUG.match(cls) and isinstance(repo, str) and repo):
            return None
        rnd = int(rec.get("round", 0))
    except (ValueError, KeyError, TypeError):
        return None
    return {
        "ts": when.isoformat(),
        "when": when,
        # owner/name and name are one repo; GitHub compares names without case.
        "repo": repo.strip().rsplit("/", 1)[-1].lower(),
        "pr": str(rec.get("pr", "")).lstrip("#"),
        "round": rnd,
        "class": cls,
        "line": str(rec.get("line", ""))[:300],
    }


def read(since: dt.datetime | None = None, until: dt.datetime | None = None) -> list[dict]:
    """Every well-formed record in [SINCE, UNTIL); a malformed line is skipped and counted."""
    path = ledger_path()
    if not path.exists():
        return []
    out, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = clean(json.loads(line))
        except ValueError:
            rec = None
        if rec is None:
            bad += 1
            continue
        if (since is None or rec["when"] >= aware(since)) and (
            until is None or rec["when"] < aware(until)
        ):
            out.append(rec)
    if bad:
        print(f"ledger: skipped {bad} malformed line(s) in {path}", file=sys.stderr)
    return out


def ladder(records: list[dict], only: set[str] | None = None) -> dict[str, dict]:
    """Per class: the numbered PRs it was found in, and its rung (checklist, mechanical).

    A record made before its PR existed (a branch name) is left out, so one change is never
    counted twice. With ONLY, classes outside it are left out too.
    """
    prs: dict[str, set[str]] = defaultdict(set)
    for r in records:
        if r["pr"].isdigit() and (only is None or r["class"] in only):
            prs[r["class"]].add(f"{r['repo']}#{r['pr']}")
    out = {}
    for cls, seen in sorted(prs.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(seen) >= CHECKLIST_AT:
            rung = "mechanical" if len(seen) >= MECHANICAL_AT else "checklist"
            out[cls] = {"prs": sorted(seen), "rung": rung}
    return out


def ago(days: float) -> dt.datetime:
    return dt.datetime.now(UTC) - dt.timedelta(days=days)


def checklist(args: argparse.Namespace) -> int:
    retired = set()
    if args.catalog and pathlib.Path(args.catalog).is_file():
        retired = retired_slugs(pathlib.Path(args.catalog).read_text(encoding="utf-8"))
    rungs = {c: v for c, v in ladder(read(ago(args.days))).items() if c not in retired}
    if not rungs:
        print(f"ledger: no class found in two or more PRs in the last {args.days:g} days")
        return 0
    print(f"Walk these first: classes reviewers found in two or more PRs in {args.days:g} days.")
    for cls, v in rungs.items():
        note = "  [three or more: needs a mechanical check]" if v["rung"] == "mechanical" else ""
        print(f"- {cls}: {len(v['prs'])} PRs ({', '.join(v['prs'])}){note}")
    return 0


def retired_slugs(text: str) -> set[str]:
    return {
        slug
        for slug, body in re.findall(
            r"^### (?:\d+\. )?([a-z0-9-]+): .*?\n(.*?)(?=^### |\Z)", text, re.M | re.S
        )
        if RETIRED.search(body)
    }


def fold(args: argparse.Namespace) -> int:
    text = pathlib.Path(args.catalog).read_text(encoding="utf-8")
    known = set(CATALOG_SLUG.findall(text))
    retired = retired_slugs(text)
    since = aware(dt.datetime.fromisoformat(args.since)) if args.since else ago(1)
    until = aware(dt.datetime.fromisoformat(args.until)) if args.until else None
    recent = read(since, until)
    incidents: dict[str, list[dict]] = defaultdict(list)
    new: dict[str, list[dict]] = defaultdict(list)
    unknown: dict[str, list[dict]] = defaultdict(list)
    for r in recent:
        item = {k: r[k] for k in ("repo", "pr", "round", "ts", "line")}
        if r["class"].startswith("new: "):
            new[r["class"][5:]].append(item)
        elif r["class"] in known:
            incidents[r["class"]].append(item)
        else:
            unknown[r["class"]].append(item)
    # A `new:` name already in the catalog is an incident of that class, not a new one.
    for name in [n for n in new if n in known]:
        incidents[name] += new.pop(name)
    week = read(ago(args.days), until)
    # A `new:` name counts PRs over the week, as the ladder does: two hits on different days
    # are still two PRs. Only names seen in today's window are listed.
    new_prs: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for r in week:
        if r["class"].startswith("new: ") and r["pr"].isdigit():
            new_prs[r["class"][5:]].add((r["repo"], r["pr"]))
    plan = {
        "since": since.isoformat(),
        "records": len(recent),
        "incidents": dict(sorted(incidents.items())),
        "new_classes": {n: v for n, v in sorted(new.items()) if len(new_prs[n]) >= 2},
        "new_seen_once": sorted(n for n in new if len(new_prs[n]) < 2),
        "unknown_slugs": dict(sorted(unknown.items())),
        # Only a catalogued, unretired slug escalates: a free-text `new:` name could carry a
        # private repo's name into a public issue title.
        "ladder": ladder(week, known - retired),
        "retired_but_found": sorted(set(incidents) & retired),
    }
    json.dump(plan, sys.stdout, indent=1, ensure_ascii=False)
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append", help="record one Blocking or Should-fix finding")
    a.add_argument("--repo", required=True, help="owner/name or name; a private repo is fine here")
    a.add_argument("--pr", required=True, help="PR number, or a branch name before a PR exists")
    a.add_argument("--round", type=int, required=True)
    a.add_argument("--severity", choices=SEVERITIES, required=True)
    a.add_argument("--class", dest="cls", required=True, help="catalog slug or `new: <name>`")
    a.add_argument("--line", required=True, help="the finding in one line")
    c = sub.add_parser("checklist", help="classes found in two or more PRs lately")
    c.add_argument("--days", type=float, default=7)
    c.add_argument("--catalog", help="bug-classes.md, so retired classes are left out")
    f = sub.add_parser("fold", help="the daily catalog plan, as JSON")
    f.add_argument("--catalog", required=True)
    f.add_argument("--since", help="ISO time; default 24 hours ago; no zone means UTC")
    f.add_argument("--until", help="ISO time the window ends (exclusive); default now")
    f.add_argument("--days", type=float, default=7)
    args = ap.parse_args(argv)
    return {"append": append, "checklist": checklist, "fold": fold}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
