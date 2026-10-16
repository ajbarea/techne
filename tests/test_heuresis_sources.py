"""Source protocol: failures become coverage lines, never crashes."""

from __future__ import annotations

from heuresis import sources
from heuresis.model import Record
from heuresis.sources import http, papers


class Fake:
    group = "papers"

    def __init__(self, name, results=None, error=None, available=(True, "")):
        self.name, self._results, self._error, self._available = (
            name,
            results or [],
            error,
            available,
        )

    def available(self):
        return self._available

    def search(self, query, limit):
        if self._error:
            raise self._error
        return self._results[:limit]

    def evidence(self, record):
        return None


R = Record(title="T", url="https://a.example/1", source="openalex", kind="paper", text="abstract")


def test_run_queries_collects_records_and_coverage():
    ok = Fake("openalex", [R])
    empty = Fake("arxiv")
    broken = Fake(
        "semantic_scholar", error=http.SourceError("http 429 from api.semanticscholar.org")
    )
    off = Fake("lens", available=(False, "no LENS_API_TOKEN"))
    records, coverage = sources.run_queries([ok, empty, broken, off], ["q1", "q2"], limit=5)
    assert records == [R, R]
    lines = {c.source: (c.status, c.queries, c.hits, c.note) for c in coverage}
    assert lines["openalex"] == ("ok", 2, 2, "")
    assert lines["arxiv"] == ("empty", 2, 0, "")
    assert lines["semantic_scholar"][0] == "failed" and "429" in lines["semantic_scholar"][3]
    assert lines["lens"] == ("skipped", 0, 0, "no LENS_API_TOKEN")


def test_unexpected_exception_is_a_failed_line_not_a_crash():
    weird = Fake("openalex", error=KeyError("results"))
    _, coverage = sources.run_queries([weird], ["q"], limit=5)
    assert coverage[0].status == "failed" and "KeyError" in coverage[0].note


def test_paper_sources_register_in_order():
    assert [s.name for s in sources.REGISTRY["papers"]] == [
        "openalex",
        "semantic_scholar",
        "arxiv",
    ]


def test_semantic_scholar_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("S2_API_KEY", raising=False)
    ok, why = papers.SemanticScholar().available()
    assert not ok and "S2_API_KEY" in why


def test_openalex_converts_records(monkeypatch):
    rows = [
        {
            "title": "T",
            "url": "https://doi.org/10.1/x",
            "source": "openalex",
            "date": "2025",
            "text": "abs",
            "evidence_url": "https://api.openalex.org/works/W1?select=title,abstract_inverted_index",
            "doi": "10.1/x",
        }
    ]
    monkeypatch.setattr(papers.S, "openalex_search", lambda q, **kw: rows)
    out = papers.OpenAlex().search("q", 3)
    assert out[0].kind == "paper" and out[0].doi == "10.1/x"


def test_openalex_evidence_reconstructs_abstract(monkeypatch):
    monkeypatch.setattr(
        papers.S,
        "openalex_work",
        lambda wid, **kw: {"title": "T", "abstract_inverted_index": {"hello": [0], "world": [1]}},
    )
    rec = Record(
        title="T",
        url="u",
        source="openalex",
        kind="paper",
        evidence_url="https://api.openalex.org/works/W1?select=x",
    )
    assert papers.OpenAlex().evidence(rec) == "T hello world"


def test_available_raising_is_a_failed_line_and_the_run_continues():
    class Boom(Fake):
        def available(self):
            raise RuntimeError("gh exploded")

    good = Fake("openalex", [R])
    records, coverage = sources.run_queries([Boom("github"), good], ["q"], limit=5)
    assert records == [R]
    assert coverage[0].source == "github" and coverage[0].status == "failed"
    assert coverage[0].note == "RuntimeError: gh exploded"
    assert coverage[1].status == "ok"


def test_coverage_counts_queries_actually_attempted():
    class FailsSecond(Fake):
        def search(self, query, limit):
            if query == "q2":
                raise http.SourceError("http 500 from x")
            return self._results

    _, coverage = sources.run_queries([FailsSecond("openalex", [R])], ["q1", "q2", "q3"], limit=5)
    assert (coverage[0].status, coverage[0].queries, coverage[0].hits) == ("failed", 2, 1)
