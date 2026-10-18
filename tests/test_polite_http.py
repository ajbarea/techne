"""polite_http: per-host pacing across processes, retries, refusals, redirects, robots.txt."""

from __future__ import annotations

import email.message
import email.utils
import http.client
import itertools
import json
import ssl
import subprocess
import sys
import textwrap
import time
import types
import urllib.error

import pytest
from conftest import ROOT
from conftest import polite_http as ph

SHARED = ROOT / "plugins" / "techne" / "_shared"
ARXIV = "https://export.arxiv.org/api/query?id_list=1"
OPENALEX = "https://api.openalex.org/works"
S2 = "https://api.semanticscholar.org/graph/v1/paper/search"


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
    """Make the transport answer with each reply in turn (an exception is raised)."""
    seen: list = []
    queue = list(replies)

    def opened(req, timeout=0):
        seen.append(req)
        item = queue.pop(0) if queue else Reply()
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(ph, "_open", opened)
    return seen


def site(monkeypatch, routes: dict):
    """Answer by URL: a str/bytes body, an exception to raise, or a redirect (code, location)."""
    seen: list = []

    def opened(req, timeout=0):
        seen.append(req)
        item = routes.get(req.full_url, b"page")
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            raise http_error(req.full_url, item[0], Location=item[1])
        return Reply(item.encode() if isinstance(item, str) else item)

    monkeypatch.setattr(ph, "_open", opened)
    return seen


def test_two_processes_are_spaced_by_the_host_interval(tmp_path):
    code = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(SHARED)!r})
        import polite_http as ph
        ph.INTERVALS["fake.test"] = 0.5
        ph.API_ENDPOINTS["fake.test"] = ("/",)
        stamps = []
        class R:
            def read(self, *a):
                stamps.append(time.time())
                return b"ok"
        ph._open = lambda req, timeout=0: R()
        while time.time() < float(sys.argv[1]):  # start together so the lock is what orders them
            pass
        for _ in range(3):
            ph.fetch("https://fake.test/x", tool="t")
        print(" ".join(map(repr, stamps)))
        """
    )
    env = {"TECHNE_POLITE_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"}
    start = repr(time.time() + 1.0)
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, start], env=env, stdout=subprocess.PIPE, text=True
        )
        for _ in range(2)
    ]
    times = sorted(float(t) for p in procs for t in p.communicate()[0].split())
    assert len(times) == 6
    gaps = [b - a for a, b in itertools.pairwise(times)]
    # Slots are reserved on the clock, so one late send can eat into the next gap.
    assert times[-1] - times[0] >= 5 * 0.45 and min(gaps) >= 0.2, gaps


def test_the_host_lock_excludes_another_process(tmp_path):
    code = (
        f"import sys; sys.path.insert(0, {str(SHARED)!r}); import polite_http as ph\n"
        "with ph._locked('lock.test'): print('acquired', flush=True)\n"
    )
    env = {"TECHNE_POLITE_DIR": str(ph.state_dir()), "PATH": "/usr/bin:/bin"}
    with ph._locked("lock.test"):
        other = subprocess.Popen(
            [sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True
        )
        with pytest.raises(subprocess.TimeoutExpired):
            other.wait(timeout=1.5)
    assert other.communicate(timeout=20)[0].strip() == "acquired"


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
        monkeypatch.setattr(mod, "_sleep", ph._sleep)
        monkeypatch.setattr(mod, "_now", ph._now)
        monkeypatch.setattr(mod, "_open", lambda req, timeout=0: Reply())
    a.fetch(ARXIV, tool="dokimasia")
    b.fetch(ARXIV, tool="techne-scholarly")
    assert slept == [pytest.approx(3.0)]


def test_the_state_dir_is_per_user_not_per_checkout(monkeypatch):
    monkeypatch.delenv("TECHNE_POLITE_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", "/home/u/.cache")
    assert str(ph.state_dir()) == "/home/u/.cache/techne/polite-http"


def test_the_interval_table_matches_the_published_limits():
    assert ph.interval("export.arxiv.org") == 3.0
    assert ph.interval("arxiv.org") == 15.0
    assert ph.interval("api.crossref.org") == 1.0
    assert ph.interval("api.crossref.org", mailto=True) == 0.34
    assert ph.interval("api.github.com") == 6.0
    assert ph.interval("api.github.com", token=True) == 2.0
    assert ph.interval("unlisted.example") == 1.0


def test_a_second_request_waits_out_the_interval(monkeypatch, slept):
    script(monkeypatch)
    ph.fetch(ARXIV, tool="t")
    ph.fetch(ARXIV, tool="t")
    assert slept == [pytest.approx(3.0)]


def test_a_late_sender_does_not_shorten_the_gap(monkeypatch, slept):
    """The slot orders callers, but the real send time is checked against the last send."""
    ph.state_dir().mkdir(parents=True, exist_ok=True)
    stamp = ph.state_dir() / "export.arxiv.org.stamp"
    stamp.write_text(json.dumps({"next": 0.0, "last_send": slept.now - 1.0}))
    script(monkeypatch)
    ph.fetch(ARXIV, tool="t")
    assert slept == [pytest.approx(2.0)]


def test_the_lock_is_not_held_while_sleeping(monkeypatch, slept):
    """A backoff sleep must not block another process: the lock is free during _sleep."""
    held = []
    advance = ph._sleep

    def probe(seconds):
        with ph._locked("api.openalex.org"):  # would deadlock if fetch held it
            held.append(seconds)
        advance(seconds)

    monkeypatch.setattr(ph, "_sleep", probe)
    script(monkeypatch, http_error(OPENALEX, 503))
    ph.fetch(OPENALEX, tool="t")
    assert held == [5.0]


# --- retries -----------------------------------------------------------------------------


def test_retry_after_seconds_is_honored(monkeypatch, slept):
    seen = script(monkeypatch, http_error(S2, 429, Retry_After="7"))
    assert ph.fetch(S2, tool="t") == b"ok"
    assert len(seen) == 2
    assert slept == [pytest.approx(7.0)]


def test_retry_after_http_date_is_honored(monkeypatch, slept):
    date = email.utils.formatdate(1_000_000.0 + 42, usegmt=True)
    script(monkeypatch, http_error(S2, 503, Retry_After=date))
    ph.fetch(S2, tool="t")
    assert slept == [pytest.approx(42.0, abs=1.0)]


def test_retry_after_zero_never_beats_the_host_interval(monkeypatch, slept):
    script(monkeypatch, http_error(ARXIV, 503, Retry_After="0"))
    ph.fetch(ARXIV, tool="t")
    assert slept == [pytest.approx(3.0)]


def test_retry_after_above_the_cap_raises_and_stops_the_host(monkeypatch, slept):
    seen = script(monkeypatch, http_error(OPENALEX, 429, Retry_After="86400"))
    with pytest.raises(ph.HttpStatus):
        ph.fetch(OPENALEX, tool="t")
    assert len(seen) == 1 and not slept
    with pytest.raises(ph.HostStopped) as stopped:
        ph.fetch(OPENALEX, tool="t")
    assert stopped.value.until == pytest.approx(1_000_000.0 + 86400)
    assert len(seen) == 1


def test_without_a_header_the_backoff_is_5_20_60_then_it_raises_and_stops(monkeypatch, slept):
    seen = script(monkeypatch, *[http_error(OPENALEX, 503) for _ in range(4)])
    with pytest.raises(ph.HttpStatus) as err:
        ph.fetch(OPENALEX, tool="t")
    assert err.value.status == 503
    assert len(seen) == 4
    assert slept == [5.0, 20.0, 60.0]
    with pytest.raises(ph.HostStopped) as stopped:
        ph.fetch(OPENALEX, tool="t")
    assert stopped.value.until == pytest.approx(slept.now + 3600)
    assert "refused until" in str(stopped.value) and "api.openalex.org" in str(stopped.value)
    assert len(seen) == 4


def test_403_is_never_retried_and_stops_the_host_for_a_day(monkeypatch, slept):
    seen = script(monkeypatch, http_error(OPENALEX, 403))
    with pytest.raises(ph.HttpStatus) as err:
        ph.fetch(OPENALEX, tool="t")
    assert err.value.status == 403 and len(seen) == 1 and not slept
    with pytest.raises(ph.HostStopped) as stopped:
        ph.fetch(OPENALEX + "?x=1", tool="t")
    assert stopped.value.until == pytest.approx(1_000_000.0 + 86400)
    assert len(seen) == 1


def test_a_stop_is_shared_with_another_process(monkeypatch, tmp_path):
    script(monkeypatch, http_error(OPENALEX, 403))
    with pytest.raises(ph.HttpStatus):
        ph.fetch(OPENALEX, tool="t")
    code = (
        f"import sys; sys.path.insert(0, {str(SHARED)!r}); import polite_http as ph\n"
        "ph._now = lambda: 1_000_000.0\n"
        "try: ph.fetch('https://api.openalex.org/works', tool='t')\n"
        "except ph.HostStopped as e: print('stopped', e.until)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        env={"TECHNE_POLITE_DIR": str(ph.state_dir()), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert done.stdout.startswith("stopped"), done.stderr


def test_github_stops_until_the_reset_when_the_budget_is_spent(monkeypatch):
    url = "https://api.github.com/search/repositories"
    seen = script(
        monkeypatch, http_error(url, 403, x_ratelimit_remaining="0", x_ratelimit_reset="1000900")
    )
    with pytest.raises(ph.HttpStatus):
        ph.fetch(url, tool="t")
    with pytest.raises(ph.HostStopped) as stopped:
        ph.fetch(url, tool="t")
    assert stopped.value.until == pytest.approx(1_000_900.0)
    assert len(seen) == 1


@pytest.mark.parametrize("code", [400, 401, 404, 410])
def test_other_4xx_are_not_retried_and_do_not_stop_the_host(monkeypatch, code):
    seen = script(monkeypatch, http_error(OPENALEX, code))
    with pytest.raises(ph.HttpStatus):
        ph.fetch(OPENALEX, tool="t")
    assert ph.fetch(OPENALEX, tool="t") == b"ok"
    assert len(seen) == 2


def test_406_is_a_throttle_only_on_the_arxiv_api(monkeypatch, slept):
    seen = script(monkeypatch, http_error(ARXIV, 406))
    assert ph.fetch(ARXIV, tool="t") == b"ok" and len(seen) == 2
    other = script(monkeypatch, http_error(OPENALEX, 406))
    with pytest.raises(ph.HttpStatus):
        ph.fetch(OPENALEX, tool="t")
    assert len(other) == 1


def test_406_rule_ignores_the_port(monkeypatch):
    url = "https://export.arxiv.org:443/api/query?id_list=1"
    seen = script(monkeypatch, http_error(url, 406))
    assert ph.fetch(url, tool="t") == b"ok" and len(seen) == 2


def test_a_call_gives_up_instead_of_waiting_past_the_budget(monkeypatch, slept):
    script(monkeypatch, *[http_error(OPENALEX, 429, Retry_After="80") for _ in range(3)])
    with pytest.raises(ph.TooSlow, match="not checked"):
        ph.fetch(OPENALEX, tool="t")


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("dns"),
        http.client.IncompleteRead(b"x"),
        ssl.SSLError("bad"),
        ConnectionResetError(),
        TimeoutError(),
        http.client.RemoteDisconnected("gone"),
    ],
)
def test_transport_failures_become_unreachable(monkeypatch, error):
    seen = script(monkeypatch, error)
    with pytest.raises(ph.Unreachable):
        ph.fetch(OPENALEX, tool="t")
    assert len(seen) == 1


def test_a_body_that_breaks_mid_read_is_unreachable(monkeypatch):
    class Broken:
        def read(self, *_):
            raise http.client.IncompleteRead(b"par")

    script(monkeypatch, Broken())
    with pytest.raises(ph.Unreachable):
        ph.fetch(OPENALEX, tool="t")


def test_an_unwritable_state_dir_raises_instead_of_pacing_silently(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("TECHNE_POLITE_DIR", str(blocker / "sub"))
    seen = script(monkeypatch)
    with pytest.raises(ph.PoliteError, match="pacing state"):
        ph.fetch(OPENALEX, tool="t")
    assert not seen


def test_the_windows_lock_retries_only_on_contention(monkeypatch):
    import errno

    calls: list[int] = []

    def locking(fd, mode, nbytes):
        calls.append(mode)
        if len(calls) < 3:
            raise OSError(errno.EACCES, "busy")

    fake = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=0, locking=locking)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    ph._lock(0)
    assert len(calls) == 3

    def broken(fd, mode, nbytes):
        raise OSError(errno.EBADF, "bad")

    fake.locking = broken
    with pytest.raises(OSError, match="bad"):
        ph._lock(0)


# --- identity ----------------------------------------------------------------------------


def test_user_agent_names_the_tool_and_never_carries_an_address(monkeypatch):
    seen = script(monkeypatch)
    ph.fetch(OPENALEX, tool="heuresis", mailto="me@example.org")
    ua = seen[0].get_header("User-agent")
    assert ua == "heuresis/1.0 (+https://github.com/ajbarea/techne)"
    assert "Mozilla" not in ua and "@" not in ua


def test_mailto_goes_only_to_crossref_and_openalex_as_a_query_parameter(monkeypatch):
    seen = script(monkeypatch)
    for url in (OPENALEX + "?a=1", "https://api.crossref.org/works/10.1/x", ARXIV, S2):
        ph.fetch(url, tool="t", mailto="me@example.org")
    urls = [r.full_url for r in seen]
    assert urls[0] == OPENALEX + "?a=1&mailto=me%40example.org"
    assert urls[1] == "https://api.crossref.org/works/10.1/x?mailto=me%40example.org"
    assert urls[2:] == [ARXIV, S2]


def test_crossref_is_paced_faster_with_a_mailto(monkeypatch, slept):
    script(monkeypatch)
    url = "https://api.crossref.org/works/10.1/x"
    ph.fetch(url, tool="t", mailto="me@example.org")
    ph.fetch(url, tool="t", mailto="me@example.org")
    assert slept == [pytest.approx(0.34)]


# --- API versus page ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "api"),
    [
        ("https://export.arxiv.org/api/query?id_list=1", True),
        ("https://export.arxiv.org:443/api/query", True),
        ("https://export.arxiv.org/abs/2401.00001", False),
        ("https://arxiv.org/abs/2401.00001", False),
        ("https://oaipmh.arxiv.org/oai?verb=Identify", True),
        ("https://api.openalex.org/works", True),
        ("https://api.semanticscholar.org/graph/v1/paper/x", True),
        ("https://api.semanticscholar.org/recommendations/v1/papers", True),
        ("https://www.semanticscholar.org/paper/x", False),
        ("https://hn.algolia.com/api/v1/search?query=x", True),
        ("https://hn.algolia.com/", False),
        ("https://ops.epo.org/3.2/rest-services/published-data/search", True),
        ("https://ops.epo.org/3.2/auth/accesstoken", True),
        ("https://news.ycombinator.com/item?id=1", False),
    ],
)
def test_api_endpoints_are_told_from_pages_by_host_and_path(url, api):
    assert ph.is_api(url) is api
    assert ph.needs_robots(url) is (not api)


# --- redirects ---------------------------------------------------------------------------


def test_a_redirect_to_another_host_drops_credentials_and_is_checked_there(monkeypatch):
    seen = site(
        monkeypatch,
        {
            "https://api.example/start": (302, "https://other.example/end"),
            "https://api.example/robots.txt": "User-agent: *\nAllow: /\n",
            "https://other.example/robots.txt": "User-agent: *\nAllow: /\n",
            "https://other.example/end": b"done",
        },
    )
    body = ph.fetch(
        "https://api.example/start", tool="t", headers={"x-api-key": "K", "Authorization": "B"}
    )
    assert body == b"done"
    final = seen[-1]
    assert {k.lower() for k in final.headers} == {"user-agent"}
    first = next(r for r in seen if r.full_url == "https://api.example/start")
    assert {k.lower() for k in first.headers} == {"user-agent", "x-api-key", "authorization"}
    assert "https://other.example/robots.txt" in [r.full_url for r in seen]


def test_a_redirect_on_the_same_host_keeps_credentials(monkeypatch):
    seen = site(
        monkeypatch,
        {
            "https://api.example/robots.txt": http_error("u", 404),
            "https://api.example/a": (301, "/b"),
        },
    )
    ph.fetch("https://api.example/a", tool="t", headers={"x-api-key": "K"})
    assert "x-api-key" in {k.lower() for k in seen[-1].headers}


def test_https_to_http_on_the_same_host_drops_credentials(monkeypatch):
    seen = site(
        monkeypatch,
        {
            "https://api.example/robots.txt": http_error("u", 404),
            "http://api.example/robots.txt": http_error("u", 404),
            "https://api.example/a": (302, "http://api.example/b"),
        },
    )
    ph.fetch("https://api.example/a", tool="t", headers={"x-api-key": "K"})
    assert "x-api-key" not in {k.lower() for k in seen[-1].headers}


def test_an_api_host_redirecting_to_a_disallowed_page_is_refused(monkeypatch):
    seen = site(
        monkeypatch,
        {
            OPENALEX: (302, "https://pages.example/private/x"),
            "https://pages.example/robots.txt": "User-agent: *\nDisallow: /private\n",
        },
    )
    with pytest.raises(ph.RobotsDisallowed) as err:
        ph.fetch(OPENALEX, tool="t")
    assert err.value.host == "pages.example"
    assert "https://pages.example/private/x" not in [r.full_url for r in seen]


def test_each_hop_is_paced_by_its_own_host(monkeypatch, slept):
    site(
        monkeypatch,
        {
            "https://one.example/robots.txt": http_error("u", 404),
            "https://two.example/robots.txt": http_error("u", 404),
            "https://one.example/a": (302, "https://two.example/b"),
            "https://two.example/b": b"ok",
        },
    )
    ph.fetch("https://one.example/a", tool="t")
    for host in ("one.example", "two.example"):
        state = json.loads((ph.state_dir() / f"{host}.stamp").read_text())
        assert state["last_send"] > 0, host


def test_too_many_redirects_and_non_web_schemes_are_refused(monkeypatch):
    site(monkeypatch, {OPENALEX: (302, OPENALEX)})
    with pytest.raises(ph.PoliteError, match="too many redirects"):
        ph.fetch(OPENALEX, tool="t")
    site(monkeypatch, {OPENALEX: (302, "ftp://x.example/a")})
    with pytest.raises(ph.PoliteError, match="ftp"):
        ph.fetch(OPENALEX, tool="t")


# --- robots.txt --------------------------------------------------------------------------

DBLP = """User-agent: *
Crawl-delay: 4
Disallow: /search/publ
Disallow: /search/author
Disallow: /lookup
Disallow: /rec/bib
Disallow: /*.bib
Disallow: /*.xml
Disallow: /*.json
"""
RESEARCHR = """User-agent: *
Crawl-delay: 2
Disallow: /*?
Disallow: /signin
Disallow: /captcha-challenge*
"""
ARXIV_ROBOTS = """User-agent: *
Allow: /list
Allow: /abs
Allow: /pdf
Allow: /html
Allow: /catchup
Disallow: /search
Disallow: /api
Disallow: /oai2
Disallow: /e-print
Crawl-delay: 15
"""


def allowed(text: str, path: str, token: str = "t") -> bool:
    return ph.parse_robots(text, token).allows(path)


def test_wildcards_are_honored_where_the_stdlib_parser_ignores_them():
    assert not allowed(DBLP, "/pid/12/345.bib")
    assert not allowed(DBLP, "/db/conf/x/y.xml")
    assert allowed(DBLP, "/pid/12/345.html")
    assert not allowed(RESEARCHR, "/home/series/ICSE?x=1")
    assert allowed(RESEARCHR, "/home/series/ICSE")
    assert not allowed(RESEARCHR, "/captcha-challenge/x")


def test_the_longest_rule_wins_and_allow_wins_a_tie():
    text = "User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /c\nAllow: /c\n"
    assert allowed(text, "/a/b/x") and not allowed(text, "/a/x")
    assert allowed(text, "/c")
    # first match is not the winner: the longer Disallow beats the shorter Allow
    assert not allowed("User-agent: *\nAllow: /a\nDisallow: /a/b\n", "/a/b")


def test_dollar_anchors_the_end_and_encoding_is_normalized():
    text = "User-agent: *\nDisallow: /*.pdf$\nDisallow: /a b\n"
    assert not allowed(text, "/x.pdf") and allowed(text, "/x.pdf?dl=1")
    assert not allowed(text, "/a%20b")


def test_arxiv_pages_follow_the_live_rules():
    assert allowed(ARXIV_ROBOTS, "/abs/2401.00001") and allowed(ARXIV_ROBOTS, "/pdf/2401.00001")
    assert not allowed(ARXIV_ROBOTS, "/search/?query=x") and not allowed(ARXIV_ROBOTS, "/api/x")
    assert ph.parse_robots(ARXIV_ROBOTS, "t").delay == 15.0


def test_the_group_for_our_token_beats_the_star_group():
    text = "User-agent: *\nDisallow: /\n\nUser-agent: heuresis\nAllow: /\n"
    assert allowed(text, "/x", "heuresis") and not allowed(text, "/x", "other")


def test_an_empty_disallow_allows_everything():
    assert allowed("User-agent: *\nDisallow:\n", "/anything")


def test_a_disallowed_page_raises_and_is_not_requested(monkeypatch):
    seen = site(
        monkeypatch, {"https://site.test/robots.txt": "User-agent: *\nDisallow: /private\n"}
    )
    with pytest.raises(ph.RobotsDisallowed, match=r"robots\.txt disallows /private/x"):
        ph.fetch("https://site.test/private/x", tool="t")
    assert [r.full_url for r in seen] == ["https://site.test/robots.txt"]
    assert ph.fetch("https://site.test/open", tool="t") == b"page"


def test_export_arxiv_org_pages_are_refused_but_its_api_is_not(monkeypatch):
    seen = site(
        monkeypatch, {"https://export.arxiv.org/robots.txt": "User-agent: *\nDisallow: /\n"}
    )
    with pytest.raises(ph.RobotsDisallowed):
        ph.fetch("https://export.arxiv.org/abs/2401.00001", tool="t")
    assert ph.fetch(ARXIV, tool="t") == b"page"
    assert seen[-1].full_url == ARXIV


def test_robots_is_fetched_once_per_host(monkeypatch):
    seen = site(monkeypatch, {"https://site.test/robots.txt": "User-agent: *\nAllow: /\n"})
    ph.fetch("https://site.test/a", tool="t")
    ph.fetch("https://site.test/b", tool="t")
    assert [r.full_url for r in seen].count("https://site.test/robots.txt") == 1


@pytest.mark.parametrize("code", [404, 410])
def test_a_missing_robots_txt_allows_everything(monkeypatch, code):
    site(monkeypatch, {"https://site.test/robots.txt": http_error("u", code)})
    assert ph.fetch("https://site.test/a", tool="t") == b"page"


@pytest.mark.parametrize("code", [401, 403])
def test_a_refused_robots_txt_stops_the_host(monkeypatch, code):
    seen = site(monkeypatch, {"https://site.test/robots.txt": http_error("u", code)})
    with pytest.raises(ph.RobotsDisallowed, match="refused us"):
        ph.fetch("https://site.test/a", tool="t")
    with pytest.raises(ph.HostStopped):
        ph.fetch("https://site.test/b", tool="t")
    assert len(seen) == 1


def test_a_5xx_or_unreachable_robots_txt_disallows_everything(monkeypatch):
    site(monkeypatch, {"https://a.test/robots.txt": http_error("u", 500)})
    with pytest.raises(ph.RobotsDisallowed):
        ph.fetch("https://a.test/a", tool="t")
    site(monkeypatch, {"https://b.test/robots.txt": urllib.error.URLError("down")})
    with pytest.raises(ph.RobotsDisallowed):
        ph.fetch("https://b.test/a", tool="t")


def test_crawl_delay_raises_the_page_interval(monkeypatch, slept):
    site(monkeypatch, {"https://slow.test/robots.txt": "User-agent: *\nCrawl-delay: 12\n"})
    ph.fetch("https://slow.test/a", tool="t")
    ph.fetch("https://slow.test/b", tool="t")
    # Sends are at least the Crawl-delay apart: 1 s after robots.txt, 11 s more, then 12 s.
    assert slept == [pytest.approx(1.0), pytest.approx(11.0), pytest.approx(12.0)]


def test_api_urls_skip_robots(monkeypatch):
    seen = site(
        monkeypatch, {"https://api.openalex.org/robots.txt": "User-agent: *\nDisallow: /\n"}
    )
    ph.fetch(OPENALEX, tool="t")
    assert [r.full_url for r in seen] == [OPENALEX]


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
