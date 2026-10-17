"""Markdown for the Closest work and Product evidence sections, from the judge's JSON."""

from __future__ import annotations

from heuresis.model import FACETS


def _link(record: dict) -> str:
    meta = ", ".join(b for b in (record.get("source"), record.get("date")) if b)
    return f"[{record['title']}]({record['url']})" + (f" ({meta})" if meta else "")


def closest_section(judge: dict, records: dict[str, dict], dropped: set[str]) -> str:
    closest = judge.get("closest") or {}
    ref = closest.get("ref")
    lines = []
    if ref in records and ref not in dropped:
        lines += [f"**Closest:** {_link(records[ref])}", "", f"> {closest.get('quote', '')}", ""]
        differs = closest.get("differs") or {}
        lines += [f"- {facet.capitalize()}: {differs.get(facet, '')}" for facet in FACETS]
    else:
        lines.append("**Closest:** none verified.")
    others = [
        o for o in judge.get("others", []) if o.get("ref") in records and o["ref"] not in dropped
    ]
    if others:
        lines += ["", "**Also:**", ""]
        lines += [f"- {_link(records[o['ref']])}: {o.get('differs', '')}" for o in others]
    return "\n".join(lines)


def product_section(judge: dict) -> str:
    evidence = judge.get("product_evidence") or {}
    if not evidence:
        return ""
    rivals = evidence.get("rivals") or []
    demand = evidence.get("demand") or []
    lines = ["**Paying rivals:**" + ("" if rivals else " unknown"), *[f"- {r}" for r in rivals]]
    lines += ["", "**Demand:**" + ("" if demand else " unknown"), *[f"- {d}" for d in demand]]
    lines += ["", f"**Riskiest assumption:** {evidence.get('riskiest_assumption') or 'unknown'}"]
    lines += [f"**Cheapest test:** {evidence.get('cheapest_test') or 'unknown'}"]
    return "\n".join(lines)
