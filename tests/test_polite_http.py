"""polite_http: per-host pacing across processes, retries, User-Agent and robots.txt."""

from __future__ import annotations

import email.message
import email.utils
import itertools
import subprocess
import sys
import textwrap
import urllib.error

import pytest
from conftest import ROOT
from conftest import polite_http as ph

SHARED = ROOT / "plugins" / "techne" / "_shared"


class Reply:
    def __init__(self, body: bytes = b"ok"):
        self.body = body

    def read(self, *_):
        return self.body


def http_error(url: str, code: int, **headers: str) -> urllib.error.HTTPError:
    msg = email.message.Message()
    for name, value in headers.items():
        msg[name.replace("_", "-")] = value
    return urllib.error.HTTPError(url, code, "x", msg, None)


def script(monkeypatch, *replies):
    """Make urlopen answer with each reply in turn (an exception is raised); record requests."""
    seen: list = []
    queue = list(replies)

    def urlopen(req, timeout=0):
        seen.append(req)
        item = queue.pop(0) if queue else Reply()
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(ph.urllib.request, "urlopen", urlopen)
    return seen


def test_two_processes_are_spaced_by_the_host_interval(tmp_path):
    code = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(SHARED)!r})
        import polite_http as ph
        ph.INTERVALS["fake.test"] = 0.5
        stamps = []
        class R:
            def read(self, *a):
                stamps.append(time.time())
                return b"ok"
        ph.urllib.request.urlopen = lambda req, timeout=0: R()
        for _ in range(3):
            ph.fetch("https://fake.test/x", tool="t")
        print(" ".join(map(repr, stamps)))
        """
    )
    env = {"TECHNE_POLITE_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"}
    procs = [
        subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    times = sorted(float(t) for p in procs for t in p.communicate()[0].split())
    assert len(times) == 6
    gaps = [b - a for a, b in itertools.pairwise(times)]
    assert min(gaps) >= 0.45, gaps


def test_consumers_in_different_plugins_share_one_arxiv_clock(monkeypatch, slept, tmp_path):
    """Pacing state is per user, not per plugin copy, so dokimasia and graphe share a clock."""
    import importlib.util

    def load(plugin: str, name: str):
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "plugins" / plugin / "_shared" / "polite_http.py"
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, mod)
        spec.loader.exec_module(mod)
        return mod

    a, b = load("dokimasia", "ph_dokimasia"), load("graphe", "ph_graphe")
    assert a is not b and a.state_dir() == b.state_dir() == ph.state_dir()
    assert str(tmp_path) in str(a.state_dir())
    for mod in (a, b):
        monkeypatch.setattr(mod, "_sleep", slept.append)
        monkeypatch.setattr(mod, "_now", lambda: 1_000_000.0)
        monkeypatch.setattr(mod.urllib.request, "urlopen", lambda req, timeout=0: Reply())
    a.fetch("https://export.arxiv.org/api/query", tool="dokimasia")
    b.fetch("https://export.arxiv.org/api/query", tool="techne-scholarly")
    assert slept == [pytest.approx(3.0)]


def test_the_state_dir_is_per_user_not_per_checkout(monkeypatch):
    monkeypatch.delenv("TECHNE_POLITE_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", "/home/u/.cache")
    assert str(ph.state_dir()) == "/home/u/.cache/techne/polite-http"


def test_the_interval_table_matches_the_published_limits():
    assert ph.interval("export.arxiv.org") == 3.0
    assert ph.interval("arxiv.org") == 15.0
    assert ph.interval("api.crossref.org") == 1.0
    assert ph.interval("api.crossref.org", mailto="a@example.org") == 0.34
    assert ph.interval("api.github.com") == 6.0
    assert ph.interval("api.github.com", token=True) == 2.0
    assert ph.interval("unlisted.example") == 1.0


def test_a_second_request_waits_out_the_interval(monkeypatch, slept):
    clock = [1000.0]
    monkeypatch.setattr(ph, "_now", lambda: clock[0])
    script(monkeypatch)
    ph.fetch("https://export.arxiv.org/api/query", tool="t")
    ph.fetch("https://export.arxiv.org/api/query", tool="t")
    assert slept == [pytest.approx(3.0)]


def test_retry_after_seconds_is_honored(monkeypatch, slept):
    url = "https://api.semanticscholar.org/graph"
    seen = script(monkeypatch, http_error(url, 429, Retry_After="7"))
    assert ph.fetch(url, tool="t") == b"ok"
    assert len(seen) == 2
    assert slept == [pytest.approx(7.0)]


def test_retry_after_http_date_is_honored(monkeypatch, slept):
    clock = [1_000_000.0]
    monkeypatch.setattr(ph, "_now", lambda: clock[0])
    url = "https://api.semanticscholar.org/graph"
    date = email.utils.formatdate(clock[0] + 42, usegmt=True)
    script(monkeypatch, http_error(url, 503, Retry_After=date))
    ph.fetch(url, tool="t")
    assert slept == [pytest.approx(42.0, abs=1.0)]


def test_retry_after_is_capped(monkeypatch, slept):
    url = "https://api.openalex.org/works"
    script(monkeypatch, http_error(url, 429, Retry_After="86400"))
    ph.fetch(url, tool="t")
    assert slept == [300.0]


def test_github_reset_is_used_when_the_budget_is_spent(monkeypatch, slept):
    clock = [5000.0]
    monkeypatch.setattr(ph, "_now", lambda: clock[0])
    url = "https://api.github.com/search/repositories"
    script(monkeypatch, http_error(url, 429, x_ratelimit_remaining="0", x_ratelimit_reset="5030"))
    ph.fetch(url, tool="t")
    assert slept == [pytest.approx(30.0)]


def test_without_a_header_the_backoff_is_5_20_60_then_it_raises(monkeypatch, slept):
    url = "https://api.openalex.org/works"
    seen = script(monkeypatch, *[http_error(url, 503) for _ in range(4)])
    with pytest.raises(ph.HttpStatus) as err:
        ph.fetch(url, tool="t")
    assert err.value.status == 503
    assert len(seen) == 4
    assert slept == [5.0, 20.0, 60.0]


def test_403_is_never_retried(monkeypatch, slept):
    url = "https://arxiv.org/abs/1"
    seen = script(monkeypatch, http_error(url, 403))
    with pytest.raises(ph.HttpStatus) as err:
        ph.fetch(url, tool="t")
    assert err.value.status == 403
    assert len(seen) == 1 and not slept


@pytest.mark.parametrize("code", [400, 401, 404, 410])
def test_other_4xx_are_not_retried(monkeypatch, code):
    seen = script(monkeypatch, http_error("https://api.openalex.org/w", code))
    with pytest.raises(ph.HttpStatus):
        ph.fetch("https://api.openalex.org/w", tool="t")
    assert len(seen) == 1


def test_406_is_a_throttle_only_on_the_arxiv_api(monkeypatch, slept):
    url = "https://export.arxiv.org/api/query"
    seen = script(monkeypatch, http_error(url, 406))
    assert ph.fetch(url, tool="t") == b"ok" and len(seen) == 2
    other = script(monkeypatch, http_error("https://api.openalex.org/w", 406))
    with pytest.raises(ph.HttpStatus):
        ph.fetch("https://api.openalex.org/w", tool="t")
    assert len(other) == 1


def test_an_unreachable_host_raises_without_retrying(monkeypatch):
    seen = script(monkeypatch, urllib.error.URLError("dns"))
    with pytest.raises(ph.Unreachable):
        ph.fetch("https://api.openalex.org/w", tool="t")
    assert len(seen) == 1


def test_user_agent_names_the_tool_and_never_looks_like_a_browser(monkeypatch):
    seen = script(monkeypatch)
    ph.fetch("https://api.openalex.org/w", tool="heuresis", mailto="me@example.org")
    ua = seen[0].get_header("User-agent")
    assert ua == "heuresis/1.0 (+https://github.com/ajbarea/techne; mailto:me@example.org)"
    assert "Mozilla" not in ua
    assert ph.user_agent("t") == "t/1.0 (+https://github.com/ajbarea/techne)"


# --- robots.txt --------------------------------------------------------------------------


def robots_script(monkeypatch, robots):
    seen: list = []

    def urlopen(req, timeout=0):
        seen.append(req.full_url)
        if req.full_url.endswith("/robots.txt"):
            if isinstance(robots, Exception):
                raise robots
            return Reply(robots.encode())
        return Reply(b"page")

    monkeypatch.setattr(ph.urllib.request, "urlopen", urlopen)
    return seen


def test_a_disallowed_page_raises_and_is_not_requested(monkeypatch):
    seen = robots_script(monkeypatch, "User-agent: *\nDisallow: /private\n")
    with pytest.raises(ph.RobotsDisallowed, match=r"robots\.txt disallows /private/x"):
        ph.fetch("https://site.test/private/x", tool="t", page=True)
    assert seen == ["https://site.test/robots.txt"]
    assert ph.fetch("https://site.test/open", tool="t", page=True) == b"page"


def test_robots_is_fetched_once_per_host(monkeypatch):
    seen = robots_script(monkeypatch, "User-agent: *\nAllow: /\n")
    ph.fetch("https://site.test/a", tool="t", page=True)
    ph.fetch("https://site.test/b", tool="t", page=True)
    assert seen.count("https://site.test/robots.txt") == 1


def test_a_404_robots_txt_allows_everything(monkeypatch):
    robots_script(monkeypatch, http_error("https://site.test/robots.txt", 404))
    assert ph.fetch("https://site.test/a", tool="t", page=True) == b"page"


def test_a_5xx_or_unreachable_robots_txt_disallows_everything(monkeypatch, slept):
    robots_script(monkeypatch, http_error("https://a.test/robots.txt", 500))
    with pytest.raises(ph.RobotsDisallowed):
        ph.fetch("https://a.test/a", tool="t", page=True)
    robots_script(monkeypatch, urllib.error.URLError("down"))
    with pytest.raises(ph.RobotsDisallowed):
        ph.fetch("https://b.test/a", tool="t", page=True)


def test_crawl_delay_raises_the_page_interval(monkeypatch, slept):
    clock = [10.0]
    monkeypatch.setattr(ph, "_now", lambda: clock[0])
    robots_script(monkeypatch, "User-agent: *\nCrawl-delay: 12\n")
    ph.fetch("https://slow.test/a", tool="t", page=True)
    ph.fetch("https://slow.test/b", tool="t", page=True)
    assert slept[-1] == pytest.approx(12.0)


def test_api_hosts_skip_robots(monkeypatch):
    seen = robots_script(monkeypatch, "User-agent: *\nDisallow: /\n")
    assert not ph.needs_robots("https://export.arxiv.org/api/query")
    assert ph.needs_robots("https://arxiv.org/abs/1")
    ph.fetch("https://export.arxiv.org/api/query", tool="t")
    assert seen == ["https://export.arxiv.org/api/query"]


# --- no browser identity anywhere ---------------------------------------------------------


def test_no_client_uses_a_browser_user_agent_or_a_headless_browser():
    clients = [
        *(ROOT / "plugins").glob("*/_shared/scholarly.py"),
        *(ROOT / "plugins").glob("*/_shared/polite_http.py"),
        *(ROOT / "plugins" / "heuresis" / "heuresis").rglob("*.py"),
        ROOT / "plugins" / "dokimasia" / "skills" / "check" / "scripts" / "dokimasia.py",
    ]
    assert len(clients) >= 8
    banned = ("Mozilla/", "Chrome/", "Safari/", "playwright", "selenium", "puppeteer")
    for path in clients:
        text = path.read_text().lower()
        for needle in banned:
            assert needle.lower() not in text, f"{path.relative_to(ROOT)} mentions {needle}"
