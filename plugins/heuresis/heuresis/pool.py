"""Merge the scouts' outputs into one numbered, deduplicated list for the judge."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from heuresis.model import Coverage, Record

# Ten records per source keeps the judge's input near 60 records across six to eight sources,
# enough to find the closest rival without burying it. The cap takes records round-robin across
# the queries that found them, so a narrow later query is not cut by a broad first one.
PER_SOURCE_CAP = 10
TRACKING_PREFIX = "utm_"
TRACKING_KEYS = ("ref", "fbclid", "gclid")


def normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = [
        (k, v)
        for k, v in sorted(urllib.parse.parse_qsl(parts.query))
        if not (k.startswith(TRACKING_PREFIX) or k in TRACKING_KEYS)
    ]
    path = parts.path.rstrip("/")
    tail = f"?{urllib.parse.urlencode(query)}" if query else ""
    return f"{host}{path}{tail}" if host else url.strip()


def _round_robin(raws: list[dict]) -> list[dict]:
    """Records grouped by source, each source's queries interleaved, first appearance first."""
    buckets: dict[str, dict[str, list[dict]]] = {}
    for raw in raws:
        by_query = buckets.setdefault(str(raw.get("source")), {})
        by_query.setdefault(str(raw.get("query", "")), []).append(raw)
    ordered = []
    for by_query in buckets.values():
        queues = list(by_query.values())
        for i in range(max(len(q) for q in queues)):
            ordered += [q[i] for q in queues if i < len(q)]
    return ordered


def build(scout_files: list[Path]) -> dict:
    seen: set[str] = set()
    per_source: dict[str, int] = {}
    records: list[dict] = []
    coverage: list[dict] = []
    queries: dict[str, list[str]] = {}
    for path in scout_files:
        data = json.loads(path.read_text())
        queries.setdefault(data["group"], []).extend(data.get("queries", []))
        coverage += [Coverage.from_dict(c).to_dict() for c in data.get("coverage", [])]
        for raw in _round_robin(data.get("records", [])):
            record = Record.from_dict(raw)
            keys = {normalize_url(record.url)} | (
                {f"doi:{record.doi.lower()}"} if record.doi else set()
            )
            if keys & seen or per_source.get(record.source, 0) >= PER_SOURCE_CAP:
                continue
            seen |= keys
            per_source[record.source] = per_source.get(record.source, 0) + 1
            records.append({**record.to_dict(), "ref": f"r{len(records) + 1}"})
    return {"records": records, "coverage": coverage, "queries": queries}
