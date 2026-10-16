"""Lens and EPO adapters against hand-written responses in the documented shapes."""

from __future__ import annotations

from conftest import ROOT
from heuresis.sources import patents

FIX = ROOT / "tests" / "fixtures" / "heuresis"


def test_lens_unavailable_without_token(monkeypatch):
    monkeypatch.delenv("LENS_API_TOKEN", raising=False)
    ok, why = patents.Lens().available()
    assert not ok and "LENS_API_TOKEN" in why


def test_lens_search_parses_recorded_response(monkeypatch):
    seen = []
    monkeypatch.setenv("LENS_API_TOKEN", "L")

    def fake_post(url, body, headers=None):
        seen.append((url, body, headers))
        return (FIX / "lens_search.json").read_bytes()

    monkeypatch.setattr(patents.http, "post_json", fake_post)
    out = patents.Lens().search("idea triage", 2)
    url, body, headers = seen[0]
    assert url == "https://api.lens.org/patent/search"
    assert body["query"]["query_string"]["query"] == "idea triage"
    assert headers["Authorization"] == "Bearer L"
    assert (
        out
        and out[0].kind == "patent"
        and out[0].url.startswith("https://www.lens.org/lens/patent/")
    )
    assert out[0].evidence_url.startswith("lens:")
    assert out[0].title == "Idea triage by prior art search" and out[0].text.startswith("A method")
    assert out[0].date == "2012-07-04" and len(out) == 2


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
    assert out[0].evidence_url == "epo:EP2000001A1"
    assert out[0].text == "A method for triaging ideas by searching prior art in patent databases."
    assert len(out) == 2
