"""Quote verification: normalization, local evidence, network failures."""

from __future__ import annotations

from pathlib import Path

from heuresis import sources, verify
from heuresis.model import Record
from heuresis.sources import http

PAGE = """<html><head><script>var x = "decoy quote that is long enough";</script></head>
<body><p>We present &ldquo;IdeaScout&rdquo;&mdash;a tool that
triages   ideas against prior&nbsp;art.</p></body></html>"""


def web(url="https://p.example/x"):
    return Record(title="t", url=url, source="web", kind="web")


def test_normalize_folds_quotes_dashes_space_and_case():
    text = "“IdeaScout” — Triages\n  IDEAS"
    assert verify.normalize(text) == '"ideascout" - triages ideas'


def test_quote_across_entities_and_line_breaks_matches(monkeypatch):
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: PAGE.encode())
    quote = "“IdeaScout”—a tool that triages ideas against prior art"
    ok, why = verify.check(web(), quote, Path("."), Path("."))
    assert ok, why


def test_script_text_does_not_count(monkeypatch):
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: PAGE.encode())
    ok, why = verify.check(web(), "decoy quote that is long enough", Path("."), Path("."))
    assert (ok, why) == (False, "quote not found")


def test_short_quote_is_rejected_before_fetching(monkeypatch):
    monkeypatch.setattr(
        verify.http, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched"))
    )
    assert verify.check(web(), "prior art", Path("."), Path(".")) == (False, "quote too short")


def test_network_failure_is_a_reason_not_a_crash(monkeypatch):
    def boom(url, headers=None):
        raise http.SourceError("http 404 from p.example")

    monkeypatch.setattr(verify.http, "get", boom)
    assert verify.check(web(), "a tool that triages ideas against", Path("."), Path(".")) == (
        False,
        "http 404 from p.example",
    )


def test_js_only_page_drops_the_record(monkeypatch):
    monkeypatch.setattr(
        verify.http,
        "get",
        lambda url, headers=None: b"<html><body><div id=root></div></body></html>",
    )
    assert verify.check(web(), "a tool that triages ideas against", Path("."), Path(".")) == (
        False,
        "quote not found",
    )


def test_idea_and_context_records_read_local_files(tmp_path: Path):
    ideas, repos = tmp_path / "ideas-repo", tmp_path / "repos"
    (ideas / "ideas").mkdir(parents=True)
    (ideas / "ideas" / "2026-10-01-x.md").write_text(
        "---\nid: x\n---\nAn earlier idea about triaging ideas."
    )
    (repos / "papers").mkdir(parents=True)
    (repos / "papers" / "references.bib").write_text(
        "@article{k, title={Federated agents and source attribution}}"
    )
    idea = Record(title="x", url="idea:2026-10-01-x", source="ideas", kind="idea")
    ctx = Record(title="bib", url="repo:papers/references.bib", source="context", kind="context")
    assert verify.check(idea, "An earlier idea about triaging ideas", ideas, repos) == (True, "")
    assert verify.check(ctx, "Federated agents and source attribution", ideas, repos) == (True, "")


def test_missing_local_file_is_a_reason_not_a_crash(tmp_path: Path):
    idea = Record(title="x", url="idea:gone", source="ideas", kind="idea")
    ok, why = verify.check(idea, "An earlier idea about triaging ideas", tmp_path, tmp_path)
    assert not ok
    assert why.startswith("unreadable")


def test_json_evidence_joins_string_leaves(monkeypatch):
    monkeypatch.setattr(
        verify.http,
        "get",
        lambda url, headers=None: (
            b'{"full_name": "a/b", "description": "Triage your ideas against prior art quickly"}'
        ),
    )
    rec = Record(
        title="a/b",
        url="https://github.com/a/b",
        source="github",
        kind="repo",
        evidence_url="https://api.github.com/repos/a/b",
    )
    assert verify.check(rec, "Triage your ideas against prior art", Path("."), Path(".")) == (
        True,
        "",
    )


def test_json_string_leaves_are_de_tagged(monkeypatch):
    body = b'{"text": "<p>Triage your ideas&#x2F;notes against prior art</p><p>second para</p>"}'
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: body)
    rec = Record(
        title="hn",
        url="https://news.ycombinator.com/item?id=1",
        source="hacker_news",
        kind="product",
        evidence_url="https://hn.algolia.com/api/v1/items/1",
    )
    quote = "Triage your ideas/notes against prior art"
    assert verify.check(rec, quote, Path("."), Path(".")) == (True, "")


def test_a_sources_own_evidence_error_is_contained(monkeypatch):
    class Broken:
        name, group = "broken", "papers"

        def evidence(self, record):
            raise RuntimeError("api changed")

    monkeypatch.setattr(sources, "by_name", lambda name: Broken())
    rec = Record(title="t", url="https://p.example/x", source="broken", kind="paper")
    ok, why = verify.check(rec, "a tool that triages ideas against", Path("."), Path("."))
    assert (ok, why) == (False, "RuntimeError: api changed")
