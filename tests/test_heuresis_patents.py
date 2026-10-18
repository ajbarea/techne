"""EPO adapter against hand-written responses in the documented shapes."""

from __future__ import annotations

import json
import urllib.parse

import pytest
from conftest import ROOT
from heuresis import sources
from heuresis.model import Record
from heuresis.sources import http, patents

FIX = ROOT / "tests" / "fixtures" / "heuresis"


def test_epo_unavailable_without_both_keys(monkeypatch):
    monkeypatch.setenv("EPO_OPS_KEY", "k")
    monkeypatch.delenv("EPO_OPS_SECRET", raising=False)
    assert not patents.Epo().available()[0]


def test_epo_search_parses_recorded_response(monkeypatch):
    monkeypatch.setattr(patents.Epo, "token", lambda self: "T")
    body = (FIX / "epo_search.xml").read_bytes()
    monkeypatch.setattr(patents.http, "get", lambda url, headers=None: body)
    out = patents.Epo().search("idea triage", 2)
    assert out and out[0].kind == "patent"
    assert out[0].url.startswith("https://worldwide.espacenet.com/patent/search?q=pn%3D")
    assert out[0].title == "Idea triage by prior art search"
    assert out[0].evidence_url == "epo:EP.2000001.A1"
    assert "pn%3DEP2000001A1" in out[0].url
    assert out[0].text == "A method for triaging ideas by searching prior art in patent databases."
    assert len(out) == 3


def test_epo_falls_back_to_first_language(monkeypatch):
    _epo_xml(monkeypatch)
    fr = patents.Epo().search("idea triage", 3)[2]
    assert fr.title.startswith("Triage") and fr.text.startswith("Procede")


def _epo_xml(monkeypatch, fake_get=None):
    monkeypatch.setattr(patents.Epo, "token", lambda self: "T")
    body = (FIX / "epo_search.xml").read_bytes()
    monkeypatch.setattr(patents.http, "get", fake_get or (lambda url, headers=None: body))


def _raise(exc):
    def fake(url, headers=None):
        raise exc

    return fake


def test_epo_no_hits_404_is_empty_not_failed(monkeypatch):
    _epo_xml(monkeypatch, _raise(http.SourceError("http 404 from ops.epo.org", status=404)))
    monkeypatch.setenv("EPO_OPS_KEY", "k")
    monkeypatch.setenv("EPO_OPS_SECRET", "s")
    assert patents.Epo().search("zzz", 5) == []
    _, coverage = sources.run_queries([patents.Epo()], ["a", "b"], limit=5)
    assert (coverage[0].status, coverage[0].queries) == ("empty", 2)


def test_epo_other_http_errors_still_fail(monkeypatch):
    _epo_xml(monkeypatch, _raise(http.SourceError("http 403", status=403)))
    with pytest.raises(http.SourceError):
        patents.Epo().search("q", 5)


def test_epo_non_xml_is_source_error(monkeypatch):
    _epo_xml(monkeypatch, lambda url, headers=None: b"not xml")
    with pytest.raises(http.SourceError):
        patents.Epo().search("q", 5)


def test_cql_strips_quotes_and_caps_terms(monkeypatch):
    urls = []
    body = (FIX / "epo_search.xml").read_bytes()
    _epo_xml(monkeypatch, lambda url, headers=None: urls.append(url) or body)
    patents.Epo().search('say "hi" ' + " ".join(f"w{i}" for i in range(20)), 5)
    cql = urllib.parse.parse_qs(urllib.parse.urlsplit(urls[0]).query)["q"][0]
    assert cql == 'ta all "say hi w0 w1 w2 w3 w4 w5 w6 w7"'


def test_epo_range_header_is_clamped(monkeypatch):
    seen = []
    body = (FIX / "epo_search.xml").read_bytes()
    _epo_xml(monkeypatch, lambda url, headers=None: seen.append((headers or {})["Range"]) or body)
    patents.Epo().search("q", 0)
    patents.Epo().search("q", 500)
    assert seen == ["1-1", "1-100"]


def test_epo_refreshes_expired_token_once(monkeypatch):
    calls, tokens = [], iter(["old", "new"])
    body = (FIX / "epo_search.xml").read_bytes()
    monkeypatch.setattr(patents.Epo, "_token", None)
    monkeypatch.setenv("EPO_OPS_KEY", "k")
    monkeypatch.setenv("EPO_OPS_SECRET", "s")
    monkeypatch.setattr(
        patents.http,
        "post_form",
        lambda url, fields, headers=None: json.dumps({"access_token": next(tokens)}).encode(),
    )

    def fake_get(url, headers=None):
        calls.append((headers or {})["Authorization"])
        if len(calls) == 1:
            raise http.SourceError("http 401", status=401)
        return body

    monkeypatch.setattr(patents.http, "get", fake_get)
    try:
        assert len(patents.Epo().search("q", 2)) == 3
        assert calls == ["Bearer old", "Bearer new"]
    finally:
        patents.Epo._token = None


def test_epo_second_401_propagates(monkeypatch):
    _epo_xml(monkeypatch, _raise(http.SourceError("http 401", status=401)))
    with pytest.raises(http.SourceError):
        patents.Epo().search("q", 2)


def test_epo_token_without_access_token(monkeypatch):
    monkeypatch.setattr(patents.Epo, "_token", None)
    monkeypatch.setenv("EPO_OPS_KEY", "k")
    monkeypatch.setenv("EPO_OPS_SECRET", "s")
    monkeypatch.setattr(patents.http, "post_form", lambda *a, **k: b'{"error": "x"}')
    with pytest.raises(http.SourceError, match="no access_token"):
        patents.Epo().token()
    monkeypatch.setattr(patents.http, "post_form", lambda *a, **k: b"<html>")
    with pytest.raises(http.SourceError):
        patents.Epo().token()
    assert patents.Epo._token is None


def test_epo_evidence_uses_docdb_dotted_input(monkeypatch):
    seen = []
    xml = (
        b'<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns="http://www.epo.org/exchange">'
        b'<exchange-documents><exchange-document><abstract lang="en"><p>An abstract.</p></abstract>'
        b"</exchange-document></exchange-documents></ops:world-patent-data>"
    )
    _epo_xml(monkeypatch, lambda url, headers=None: seen.append(url) or xml)
    record = Record(
        title="t", url="u", source="epo", kind="patent", evidence_url="epo:EP.2000001.A1"
    )
    assert patents.Epo().evidence(record) == "An abstract."
    assert seen[0].endswith("/publication/docdb/EP.2000001.A1/abstract")


def test_epo_evidence_bad_xml_is_source_error(monkeypatch):
    _epo_xml(monkeypatch, lambda url, headers=None: b"nope")
    record = Record(title="t", url="u", source="epo", kind="patent", evidence_url="epo:EP.1.A1")
    with pytest.raises(http.SourceError):
        patents.Epo().evidence(record)
