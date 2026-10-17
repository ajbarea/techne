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


def test_normalize_url_keeps_lookalike_params_and_ignores_order():
    assert pool.normalize_url("https://a.example/p?reference=1") != pool.normalize_url(
        "https://a.example/p?reference=2"
    )
    assert pool.normalize_url("https://a.example/p?b=2&a=1&ref=x") == pool.normalize_url(
        "https://a.example/p?a=1&b=2"
    )


def test_build_dedupes_by_url_and_doi_and_caps(tmp_path: Path):
    many = [rec(f"https://a.example/{i}") for i in range(15)]
    a = scout(
        tmp_path / "scout-papers.json",
        "papers",
        [
            rec("https://a.example/0"),
            rec("http://www.a.example/0/"),
            *many,
            rec("https://b.example/x", "arxiv", doi="10.1/x"),
            rec("https://c.example/y", "semantic_scholar", doi="10.1/X"),
        ],
        [{"source": "openalex", "status": "ok", "queries": 2, "hits": 15}],
        ["q1", "q2"],
    )
    out = pool.build([a])
    urls = [r["url"] for r in out["records"]]
    assert urls.count("https://a.example/0") == 1
    assert "http://www.a.example/0/" not in urls
    assert len([u for u in urls if "a.example" in u]) == pool.PER_SOURCE_CAP
    assert len([r for r in out["records"] if r["doi"].lower() == "10.1/x"]) == 1
    assert [r["ref"] for r in out["records"]] == [f"r{i}" for i in range(1, len(urls) + 1)]
    assert out["queries"] == {"papers": ["q1", "q2"]}
    assert out["coverage"][0]["source"] == "openalex"


def test_build_accumulates_queries_for_a_repeated_group(tmp_path: Path):
    a = scout(tmp_path / "a.json", "papers", [], [], ["q1"])
    b = scout(tmp_path / "b.json", "papers", [], [], ["q2"])
    assert pool.build([a, b])["queries"] == {"papers": ["q1", "q2"]}


def test_cap_takes_records_round_robin_across_a_sources_queries(tmp_path: Path):
    records = [
        {**rec(f"https://{q}.example/{i}"), "query": q}
        for q in ("q1", "q2", "q3", "q4")
        for i in range(8)
    ]
    path = scout(tmp_path / "scout-papers.json", "papers", records, [], ["q1", "q2", "q3", "q4"])
    out = pool.build([path])
    hosts = [r["url"].split("/")[2] for r in out["records"]]
    assert len(hosts) == pool.PER_SOURCE_CAP
    counts = {q: hosts.count(f"{q}.example") for q in ("q1", "q2", "q3", "q4")}
    assert counts == {"q1": 3, "q2": 3, "q3": 2, "q4": 2}
    assert "query" not in out["records"][0]
