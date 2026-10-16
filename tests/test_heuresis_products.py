"""GitHub and Hacker News adapters."""

from __future__ import annotations

import subprocess

from conftest import ROOT
from heuresis.sources import products

FIX = ROOT / "tests" / "fixtures" / "heuresis"


def test_github_search_builds_records_with_api_evidence(monkeypatch):
    seen = []
    monkeypatch.setattr(products, "github_token", lambda: "T")
    monkeypatch.setattr(
        products.http,
        "get",
        lambda url, headers=None: (
            seen.append((url, headers)) or (FIX / "github_repos.json").read_bytes()
        ),
    )
    out = products.GitHub().search("idea triage", 2)
    url, headers = seen[0]
    assert url.startswith("https://api.github.com/search/repositories?q=idea+triage")
    assert headers["Authorization"] == "Bearer T"
    assert out and out[0].kind == "repo" and out[0].url.startswith("https://github.com/")
    assert out[0].evidence_url.startswith("https://api.github.com/repos/")


def test_github_unavailable_without_token(monkeypatch):
    monkeypatch.setattr(products, "github_token", lambda: None)
    ok, why = products.GitHub().available()
    assert not ok and "GITHUB_TOKEN" in why


def test_hn_records_fall_back_to_item_page(monkeypatch):
    monkeypatch.setattr(
        products.http, "get", lambda url, headers=None: (FIX / "hn_search.json").read_bytes()
    )
    out = products.HackerNews().search("idea validation", 2)
    assert out and all(r.kind == "web" for r in out)
    assert all(r.url.startswith("http") for r in out)
    assert out[1].url == "https://news.ycombinator.com/item?id=5916181"
    assert out[0].evidence_url.startswith("https://hn.algolia.com/api/v1/items/")


def test_github_token_prefers_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "E")
    assert products.github_token() == "E"


def _no_env_gh(monkeypatch, run):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(products.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(products.subprocess, "run", run)


def test_github_token_from_gh(monkeypatch):
    _no_env_gh(
        monkeypatch, lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="tok\n", stderr="")
    )
    assert products.github_token() == "tok"


def test_github_token_none_when_gh_fails_or_empty(monkeypatch):
    _no_env_gh(
        monkeypatch, lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="tok", stderr="")
    )
    assert products.github_token() is None
    _no_env_gh(
        monkeypatch, lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="\n", stderr="")
    )
    assert products.github_token() is None


def test_github_token_none_when_gh_hangs_or_cannot_run(monkeypatch):
    def hang(*a, **k):
        raise subprocess.TimeoutExpired("gh", 10)

    def broken(*a, **k):
        raise OSError("exec format error")

    _no_env_gh(monkeypatch, hang)
    assert products.github_token() is None
    _no_env_gh(monkeypatch, broken)
    assert products.github_token() is None


def test_github_token_none_without_gh(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(products.shutil, "which", lambda name: None)
    assert products.github_token() is None
