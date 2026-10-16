"""Pool: merge scout outputs, dedupe, cap per source, number records."""

from __future__ import annotations

import json
from pathlib import Path

from heuresis import pool


def scout(path: Path, group: str, records: list[dict], coverage: list[dict], queries: list[str]):
    path.write_text(
        json.dumps({"group": group, "queries": queries, "records": records, "coverage": coverage})
    )
    return path


def rec(url, source="openalex", doi=""):
    return {"title": url, "url": url, "source": source, "kind": "paper", "doi": doi}


def test_normalize_url_drops_scheme_www_slash_and_tracking():
    assert (
        pool.normalize_url("https://www.Example.com/a/?utm_source=x&id=2") == "example.com/a?id=2"
    )


def test_build_dedupes_by_url_and_doi_and_caps(tmp_path: Path):
    many = [rec(f"https://a.example/{i}") for i in range(15)]
    a = scout(
        tmp_path / "scout-papers.json",
        "papers",
        [
            *many,
            rec("http://www.a.example/1/"),
            rec("https://b.example/x", "arxiv", doi="10.1/x"),
            rec("https://c.example/y", "semantic_scholar", doi="10.1/X"),
        ],
        [{"source": "openalex", "status": "ok", "queries": 2, "hits": 15}],
        ["q1", "q2"],
    )
    out = pool.build([a])
    urls = [r["url"] for r in out["records"]]
    assert len([u for u in urls if "a.example" in u]) == pool.PER_SOURCE_CAP
    assert len([r for r in out["records"] if r["doi"].lower() == "10.1/x"]) == 1
    assert [r["ref"] for r in out["records"]] == [f"r{i}" for i in range(1, len(urls) + 1)]
    assert out["queries"] == {"papers": ["q1", "q2"]}
    assert out["coverage"][0]["source"] == "openalex"
