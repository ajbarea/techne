"""Shared paper retrieval: OpenAlex, Semantic Scholar, arXiv."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ROOT, SCHOLARLY_SCRIPT, _load

FIX = ROOT / "tests" / "fixtures" / "heuresis"
s = _load("scholarly", SCHOLARLY_SCRIPT)


def fake(body: bytes, seen: list):
    def fetch(url, headers):
        seen.append((url, headers))
        return body

    return fetch


def test_reconstruct_abstract_orders_words_by_position():
    assert s.reconstruct_abstract({"world": [1], "hello": [0], "again": [2]}) == "hello world again"
    assert s.reconstruct_abstract(None) == ""


def test_openalex_search_uses_title_and_abstract_filter_and_key():
    seen: list = []
    body = (FIX / "openalex_works.json").read_bytes()
    out = s.openalex_search("federated agents", api_key="K", fetch=fake(body, seen))
    url, _ = seen[0]
    assert "filter=title_and_abstract.search:federated%20agents" in url
    assert "api_key=K" in url
    assert out and set(out[0]) == {"title", "url", "source", "date", "text", "evidence_url", "doi"}
    assert out[0]["source"] == "openalex"
    assert out[0]["evidence_url"].startswith("https://api.openalex.org/works/")


def test_openalex_semantic_mode_uses_search_semantic():
    seen: list = []
    s.openalex_search("q", semantic=True, fetch=fake(b'{"results": []}', seen))
    assert "search.semantic=q" in seen[0][0]


def test_s2_search_sends_key_header():
    seen: list = []
    body = (FIX / "s2_search.json").read_bytes()
    out = s.s2_search("federated agents", api_key="S", fetch=fake(body, seen))
    assert seen[0][1]["x-api-key"] == "S"
    assert out[0]["doi"] == "10.1234/fa.2025"
    assert out[0]["source"] == "semantic_scholar"


def test_arxiv_search_parses_atom(tmp_path: Path):
    seen: list = []
    body = (FIX / "arxiv_query.xml").read_bytes()
    out = s.arxiv_search("federated learning", fetch=fake(body, seen), throttle=tmp_path / "t")
    assert seen[0][0].startswith("https://export.arxiv.org/api/query?search_query=all:")
    assert out and out[0]["source"] == "arxiv"
    assert out[0]["evidence_url"].startswith("https://export.arxiv.org/api/query?id_list=")


def test_arxiv_throttle_waits_three_seconds(tmp_path: Path, monkeypatch):
    slept: list[float] = []
    clock = iter([100.0, 100.5])
    monkeypatch.setattr(s.time, "time", lambda: next(clock))
    monkeypatch.setattr(s.time, "sleep", slept.append)
    stamp = tmp_path / "t"
    stamp.write_text("98.5")
    s._throttle(stamp)
    assert slept == [pytest.approx(1.5)]


def test_malformed_json_raises_scholarly_error():
    with pytest.raises(s.ScholarlyError):
        s.openalex_search("q", fetch=fake(b"<html>", []))


def test_cli_prints_json_lines(capsys, monkeypatch):
    monkeypatch.setattr(s, "_get", lambda url, headers: (FIX / "openalex_works.json").read_bytes())
    assert s.main(["openalex", "federated agents", "--limit", "2"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert all(json.loads(line)["source"] == "openalex" for line in lines)
