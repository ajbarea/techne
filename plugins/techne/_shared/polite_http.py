"""Polite HTTP for scholarly and search services. Standard library only, Python 3.11 or newer.

Every client in this repo that calls a scholarly or search host goes through `fetch`:

- Requests to one host are spaced by a minimum interval (INTERVALS), across processes. A short
  file lock in a per-user cache folder guards a per-host state file. A caller reserves its
  slot under the lock, releases it, sleeps, then sends, so a long backoff never blocks others.
- A host that refuses us stays refused, across processes. A 403, retries that ran out on 429
  or 503 (or 406 from the arXiv API), and a spent GitHub rate limit write a "stopped until"
  time. `fetch` then raises HostStopped at once instead of asking again.
- On 429 and 503 (and 406 from export.arxiv.org, which is how arXiv throttles) the call waits
  for `Retry-After`, else 5, 20 and 60 seconds, and retries at most three times. It never
  retries a 403 or any other 4xx. One call never waits longer than BUDGET seconds.
- Redirects are followed here, at most five hops. Every hop gets its own robots check and
  pacing, and credential headers are dropped when a hop leaves the host or drops to http.
- An honest User-Agent that names the tool and links the repo. It never carries an address
  and never looks like a browser. A contact address goes only to Crossref and OpenAlex, as the
  `mailto` query parameter their polite pools read.
- robots.txt for page fetches. A URL on a documented API endpoint (API_ENDPOINTS) is governed
  by the API's own terms and skips it; everything else is a page. Example: export.arxiv.org
  `/api/query` is sanctioned at one request per three seconds, while export.arxiv.org `/abs`
  is a page and robots.txt there says `Disallow: /`.
  Matching follows RFC 9309: the group for our product token, else `*`; the longest matching
  rule wins and Allow wins a tie; `*` and `$` are wildcards. A 404 or 410 robots.txt allows
  everything. A 5xx, a 429 or an unreachable host disallows everything. A 401 or 403 counts as
  the host refusing us and stops the host. That departs deliberately from RFC 9309, which
  treats every 4xx as "no rules": a server that answers its robots.txt with 403 is not
  inviting a crawler.
"""

from __future__ import annotations

import contextlib
import email.utils
import errno
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Generator, Mapping
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path

HOMEPAGE = "https://github.com/ajbarea/techne"
VERSION = "1.0"
TIMEOUT = 25
MAX_RETRIES = 3
MAX_HOPS = 5
BACKOFF = (5.0, 20.0, 60.0)
MAX_WAIT = 300.0
# No call waits longer than this in total; the heuresis CLI runs inside a 120 s Bash call.
BUDGET = 90.0
FORBIDDEN_STOP = 24 * 3600.0
EXHAUSTED_STOP = 3600.0
ARXIV_API_HOST = "export.arxiv.org"
RETRY_STATUSES = (429, 503)
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
# Statuses a caller can report as "the host is throttling" rather than "no such record".
THROTTLED_STATUSES = (406, 429, 503)
CREDENTIAL_HEADERS = frozenset({"x-api-key", "authorization", "cookie", "proxy-authorization"})

# research(2026-10): limits read from each service's own docs and robots.txt on 2026-10-18.
# arXiv API terms: one request per 3 s, one connection, all machines combined
#   (info.arxiv.org/help/api/tou.html). arxiv.org robots.txt: Crawl-delay 15.
# Semantic Scholar: keyed 1 rps, keyless shared pool (semanticscholar.org/product/api).
# OpenAlex: keyless 10 rps (help.openalex.org/api-reference/authentication).
# Crossref: public 1 rps for lists, 3 rps with a mailto (crossref.org announcement of the
#   2025 REST API rate limit changes).
# GitHub search: 10 per minute unauthenticated, 30 with a token (docs.github.com rate limits).
# Hacker News Algolia and EPO OPS state no per-second limit; EPO's fair-use page caps volume.
INTERVALS: dict[str, float] = {
    "export.arxiv.org": 3.0,
    "oaipmh.arxiv.org": 3.0,
    "arxiv.org": 15.0,
    "api.semanticscholar.org": 1.0,
    "api.openalex.org": 0.11,
    "api.crossref.org": 1.0,
    "api.github.com": 6.0,
    "hn.algolia.com": 1.0,
    "ops.epo.org": 1.0,
}
CROSSREF_POLITE_INTERVAL = 0.34
GITHUB_TOKEN_INTERVAL = 2.0
DEFAULT_INTERVAL = 1.0
# Documented API endpoints, by hostname (no port) and path prefix. Everything else is a page.
API_ENDPOINTS: dict[str, tuple[str, ...]] = {
    "export.arxiv.org": ("/api/",),
    "oaipmh.arxiv.org": ("/oai",),
    "api.openalex.org": ("/",),
    "api.semanticscholar.org": ("/graph/", "/recommendations/"),
    "api.crossref.org": ("/",),
    "api.github.com": ("/",),
    "hn.algolia.com": ("/api/",),
    "ops.epo.org": ("/3.2/",),
}
# Where a contact address is sent as `mailto=`.
MAILTO_HOSTS = frozenset({"api.crossref.org", "api.openalex.org"})


class PoliteError(Exception):
    """Base class for what `fetch` raises."""


class HttpStatus(PoliteError):
    """The host answered with an HTTP error status, after any retries."""

    def __init__(self, status: int, host: str):
        super().__init__(f"http {status} from {host}")
        self.status = status
        self.host = host


class Unreachable(PoliteError):
    """The host did not answer: DNS, connection, TLS, timeout or a broken body."""

    def __init__(self, host: str):
        super().__init__(f"unreachable: {host}")
        self.host = host


class HostStopped(PoliteError):
    """The host refused us earlier and is not asked again until `until` (epoch seconds)."""

    def __init__(self, host: str, until: float):
        stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(until))
        super().__init__(f"not checked: {host} refused until {stamp}")
        self.host = host
        self.until = until


class TooSlow(PoliteError):
    """The pacing would make this call wait longer than BUDGET seconds."""

    def __init__(self, host: str, wait: float):
        super().__init__(f"not checked: {host} would need a {wait:.0f} s wait")
        self.host = host


class RobotsDisallowed(PoliteError):
    """robots.txt forbids fetching the path, or could not be read."""

    def __init__(self, host: str, path: str, reason: str = "disallows"):
        super().__init__(f"not fetched: robots.txt {reason} {path}")
        self.host = host
        self.path = path


def user_agent(tool: str, version: str = VERSION) -> str:
    return f"{tool}/{version} (+{HOMEPAGE})"


def hostname(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def is_api(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    prefixes = API_ENDPOINTS.get(hostname(url), ())
    return any((parts.path or "/").startswith(p) for p in prefixes)


def needs_robots(url: str) -> bool:
    return not is_api(url)


def interval(host: str, *, mailto: bool = False, token: bool = False) -> float:
    if host == "api.crossref.org" and mailto:
        return CROSSREF_POLITE_INTERVAL
    if host == "api.github.com" and token:
        return GITHUB_TOKEN_INTERVAL
    return INTERVALS.get(host, DEFAULT_INTERVAL)


# --- clock and shared state --------------------------------------------------------------


def _now() -> float:
    return time.time()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def state_dir() -> Path:
    """One folder per user, so every plugin and every checkout shares one clock per host."""
    override = os.environ.get("TECHNE_POLITE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "techne" / "polite-http"


LOCK_TRIES = 60


def _lock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        for _ in range(LOCK_TRIES):  # LK_LOCK itself waits about ten seconds per try
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EDEADLK):
                    raise
        raise PoliteError("could not lock the pacing state")
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


@dataclass
class _State:
    """Per-host state: the earliest next send, and the time before which the host is stopped."""

    next: float = 0.0
    stopped_until: float = 0.0
    last_send: float = 0.0


class _Store:
    def __init__(self, stamp: Path):
        self.stamp = stamp

    def load(self) -> _State:
        try:
            data = json.loads(self.stamp.read_text())
            return _State(
                float(data.get("next", 0.0)),
                float(data.get("stopped_until", 0.0)),
                float(data.get("last_send", 0.0)),
            )
        except (OSError, ValueError, AttributeError, TypeError):
            return _State()

    def save(self, state: _State) -> None:
        try:
            self.stamp.write_text(
                json.dumps(
                    {
                        "next": state.next,
                        "stopped_until": state.stopped_until,
                        "last_send": state.last_send,
                    }
                )
            )
        except OSError as exc:
            raise PoliteError(f"cannot write pacing state {self.stamp}: {exc.strerror}") from exc


@contextlib.contextmanager
def _locked(host: str) -> Generator[_Store]:
    name = "".join(c if c.isalnum() or c in ".-" else "_" for c in host)
    try:
        directory = state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(directory / f"{name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise PoliteError(f"cannot keep pacing state in {state_dir()}: {exc.strerror}") from exc
    try:
        _lock(fd)
        try:
            yield _Store(directory / f"{name}.stamp")
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def _reserve(host: str, gap: float, started: float, budget: float) -> None:
    """Take the next free slot for `host`, wait for it, and return. Holds the lock only briefly.

    The slot orders callers. The send time is then confirmed under the lock: if the previous
    send (by any process) was less than `gap` ago, because a sender ran late, wait out the rest.
    """
    with _locked(host) as store:
        state = store.load()
        now = _now()
        if state.stopped_until > now:
            raise HostStopped(host, state.stopped_until)
        slot = max(now, state.next)
        if slot - started > budget:
            raise TooSlow(host, slot - now)
        state.next = slot + gap
        store.save(state)
    if slot > now:
        _sleep(slot - now)
    while True:
        with _locked(host) as store:
            state = store.load()
            now = _now()
            if state.stopped_until > now:
                raise HostStopped(host, state.stopped_until)
            wait = state.last_send + gap - now
            if wait <= 0:
                state.last_send = now
                store.save(state)
                return
            if now + wait - started > budget:
                raise TooSlow(host, wait)
        _sleep(wait)


def _settle(host: str, gap: float, *, wait: float = 0.0, stop_for: float = 0.0) -> None:
    """Record the outcome: the next send is at least `gap` (or `wait`) after now."""
    with _locked(host) as store:
        state = store.load()
        now = _now()
        state.next = max(state.next, now + max(gap, wait))
        if stop_for:
            state.stopped_until = max(state.stopped_until, now + stop_for)
        store.save(state)


# --- retries -----------------------------------------------------------------------------


def _parse_retry_after(value: str, now: float) -> float | None:
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - now)


def _lowered(headers: Mapping[str, str] | Message) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in headers.items()}


def _is_throttle(host: str, url: str, status: int) -> bool:
    return status in RETRY_STATUSES or (status == 406 and host == ARXIV_API_HOST and is_api(url))


def _github_reset(host: str, status: int, headers: dict[str, str], now: float) -> float | None:
    """Seconds until a spent GitHub rate limit resets, or None when this is not that case."""
    if host != "api.github.com" or status not in (403, 429):
        return None
    if headers.get("x-ratelimit-remaining", "").strip() != "0":
        return None
    reset = headers.get("x-ratelimit-reset", "").strip()
    return max(0.0, float(reset) - now) if reset.isdigit() else EXHAUSTED_STOP


# --- sending -----------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are followed in `fetch`, so each hop is robots-checked and paced."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(req: urllib.request.Request, timeout: float):
    return _OPENER.open(req, timeout=timeout)


def _send(req: urllib.request.Request, timeout: float, max_bytes: int | None) -> bytes:
    resp = _open(req, timeout)
    try:
        return resp.read(max_bytes) if max_bytes else resp.read()
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


@dataclass
class _Redirect:
    status: int
    location: str


def _hop(
    req: urllib.request.Request,
    *,
    host: str,
    gap: float,
    timeout: float,
    max_bytes: int | None,
    started: float,
    budget: float,
) -> bytes | _Redirect:
    url = req.full_url
    for attempt in range(MAX_RETRIES + 1):
        _reserve(host, gap, started, budget)
        try:
            body = _send(req, timeout, max_bytes)
        except urllib.error.HTTPError as exc:
            status = exc.code
            headers = _lowered(exc.headers or {})
            now = _now()
            if status in REDIRECT_STATUSES and headers.get("location"):
                _settle(host, gap)
                return _Redirect(status, headers["location"])
            reset = _github_reset(host, status, headers, now)
            if reset is not None:
                _settle(host, gap, stop_for=reset)
                raise HttpStatus(status, host) from exc
            if status == 403:
                _settle(host, gap, stop_for=FORBIDDEN_STOP)
                raise HttpStatus(status, host) from exc
            if not _is_throttle(host, url, status):
                _settle(host, gap)
                raise HttpStatus(status, host) from exc
            given = _parse_retry_after(headers.get("retry-after", ""), now)
            wait = BACKOFF[min(attempt, len(BACKOFF) - 1)] if given is None else given
            if given is not None and given > MAX_WAIT:
                _settle(host, gap, stop_for=given)
                raise HttpStatus(status, host) from exc
            if attempt == MAX_RETRIES:
                _settle(host, gap, stop_for=max(wait, EXHAUSTED_STOP))
                raise HttpStatus(status, host) from exc
            _settle(host, gap, wait=wait)
            continue
        except (OSError, http.client.HTTPException) as exc:
            # URLError, timeouts, connection resets, SSL errors and IncompleteRead while reading.
            _settle(host, gap)
            raise Unreachable(host) from exc
        _settle(host, gap)
        return body
    raise AssertionError("unreachable")


# --- robots.txt (RFC 9309) ----------------------------------------------------------------


@dataclass
class _Robots:
    """Parsed rules for one product token. `rules` is None when the host disallows all."""

    rules: list[tuple[bool, re.Pattern[str], int]] | None = field(default_factory=list)
    delay: float = 0.0
    reason: str = "disallows"

    def allows(self, path_and_query: str) -> bool:
        if self.rules is None:
            return False
        target = urllib.parse.unquote(path_and_query)
        best: tuple[int, bool] | None = None
        for allow, pattern, length in self.rules:
            if pattern.match(target) and (
                best is None or length > best[0] or (length == best[0] and allow)
            ):
                best = (length, allow)
        return True if best is None else best[1]


def _pattern(rule: str) -> re.Pattern[str]:
    rule = urllib.parse.unquote(rule)
    end = rule.endswith("$")
    body = rule[:-1] if end else rule
    regex = ".*".join(re.escape(piece) for piece in body.split("*"))
    return re.compile(regex + ("$" if end else ""), re.DOTALL)


def parse_robots(text: str, token: str) -> _Robots:
    """Rules that apply to `token`: its own groups if any, else the `*` groups."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        name, value = (part.strip() for part in line.split(":", 1))
        name = name.lower()
        if name == "user-agent":
            if in_rules:
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(value.lower())
        elif name in ("allow", "disallow", "crawl-delay"):
            in_rules = True
            rules.append((name, value))
    if agents:
        groups.append((agents, rules))
    token = token.lower()
    chosen = [g for g in groups if token in g[0]] or [g for g in groups if "*" in g[0]]
    result = _Robots()
    assert result.rules is not None
    for _, entries in chosen:
        for name, value in entries:
            if name == "crawl-delay":
                with contextlib.suppress(ValueError):
                    result.delay = max(result.delay, float(value))
            elif value:  # an empty Disallow allows everything
                result.rules.append((name == "allow", _pattern(value), len(value)))
    return result


_ROBOTS: dict[tuple[str, str], _Robots] = {}


def _robots_for(scheme: str, netloc: str, *, tool: str, timeout: float) -> _Robots:
    key = (scheme, netloc)
    if key in _ROBOTS:
        return _ROBOTS[key]
    url = f"{scheme}://{netloc}/robots.txt"
    try:
        raw = _fetch(url, tool=tool, timeout=timeout, max_bytes=512_000, robots=False)
    except HttpStatus as exc:
        if exc.status in (401, 403):
            if exc.status == 401:
                _settle(hostname(url), 0.0, stop_for=FORBIDDEN_STOP)
            # Not cached: the next call reaches the stop marker and raises HostStopped.
            return _Robots(None, 0.0, "refused us for")
        elif exc.status < 500 and exc.status != 429:  # 404, 410 and the other 4xx: no rules
            rules = _Robots()
        else:
            rules = _Robots(None, 0.0, "is unavailable for")
    except Unreachable:
        rules = _Robots(None, 0.0, "is unreachable for")
    else:
        rules = parse_robots(raw.decode("utf-8", errors="replace"), tool)
    _ROBOTS[key] = rules
    return rules


def check_robots(url: str, *, tool: str, timeout: float = TIMEOUT) -> float:
    """Raise RobotsDisallowed unless robots.txt lets this tool fetch the URL.

    Returns the host's Crawl-delay in seconds (0 when it sets none).
    """
    parts = urllib.parse.urlsplit(url)
    rules = _robots_for(parts.scheme, parts.netloc, tool=tool, timeout=timeout)
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    if not rules.allows(target):
        raise RobotsDisallowed(hostname(url), parts.path or "/", rules.reason)
    return rules.delay


# --- fetch -------------------------------------------------------------------------------


def _with_mailto(url: str, mailto: str | None) -> str:
    parts = urllib.parse.urlsplit(url)
    if not mailto or hostname(url) not in MAILTO_HOSTS or "mailto=" in parts.query:
        return url
    query = (parts.query + "&" if parts.query else "") + urllib.parse.urlencode({"mailto": mailto})
    return urllib.parse.urlunsplit(parts._replace(query=query))


def fetch(
    url: str,
    *,
    tool: str,
    headers: Mapping[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    mailto: str | None = None,
    timeout: float = TIMEOUT,
    max_bytes: int | None = None,
) -> bytes:
    """GET (or POST with `data`) one URL politely and return the body.

    Raises HttpStatus, Unreachable, HostStopped, TooSlow or RobotsDisallowed, all PoliteError.
    """
    return _fetch(
        _with_mailto(url, mailto),
        tool=tool,
        headers=headers,
        data=data,
        method=method,
        timeout=timeout,
        max_bytes=max_bytes,
        robots=True,
    )


def _fetch(
    url: str,
    *,
    tool: str,
    headers: Mapping[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float,
    max_bytes: int | None,
    robots: bool,
) -> bytes:
    sent = {"User-Agent": user_agent(tool), **(headers or {})}
    started = _now()
    for hop in range(MAX_HOPS + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise PoliteError(f"unsupported scheme: {parts.scheme or 'none'}")
        host = hostname(url)
        delay = 0.0
        if robots and not is_api(url):
            delay = check_robots(url, tool=tool, timeout=timeout)
        token = any(k.lower() == "authorization" for k in sent)
        gap = max(interval(host, mailto="mailto=" in parts.query, token=token), delay)
        req = urllib.request.Request(url, data=data, headers=sent, method=method)
        got = _hop(
            req,
            host=host,
            gap=gap,
            timeout=timeout,
            max_bytes=max_bytes,
            started=started,
            budget=BUDGET,
        )
        if isinstance(got, bytes):
            return got
        if hop == MAX_HOPS:
            break
        target = urllib.parse.urljoin(url, got.location)
        new = urllib.parse.urlsplit(target)
        if new.scheme not in ("http", "https"):
            raise PoliteError(f"redirect to unsupported scheme: {new.scheme or 'none'}")
        if (new.scheme, new.hostname) != (parts.scheme, parts.hostname):
            sent = {k: v for k, v in sent.items() if k.lower() not in CREDENTIAL_HEADERS}
        if got.status in (301, 302, 303):
            data, method = None, None
        url = target
    raise PoliteError(f"too many redirects from {hostname(url)}")
