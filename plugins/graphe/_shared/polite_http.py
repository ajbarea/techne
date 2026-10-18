"""Polite HTTP for scholarly and search services. Standard library only, Python 3.11 or newer.

Every client in this repo that calls a scholarly or search host goes through `fetch`:

- One request at a time per host, across processes. A file lock in a per-user cache directory
  covers the wait, the send and the new stamp, so parallel scouts and a bibliography check
  queue behind one another instead of adding up.
- A minimum interval per host (see INTERVALS), taken from each service's published limits.
- On 429 and 503 (and 406 from export.arxiv.org, which is how arXiv throttles) the call waits
  for `Retry-After`, else GitHub's `x-ratelimit-reset`, else 5, 20 and 60 seconds, and retries
  at most three times. Then it raises. It never retries a 403 or any other 4xx: arXiv treats
  repeat requests after a 403 as an attack.
- An honest User-Agent that names the tool and links the repo, plus a mailto when the caller
  has an address. Never a browser User-Agent.
- robots.txt for page fetches (`page=True`). Documented API endpoints are governed by the
  API's own terms, so `needs_robots` is false for the hosts in API_HOSTS. The example is
  export.arxiv.org: its robots.txt is `Disallow: /`, while the API terms sanction
  `/api/query` at one request per three seconds. Parsing follows RFC 9309: a 4xx robots.txt
  allows everything, a 5xx, a 429 or an unreachable host disallows everything.

Redirects are paced and checked only for the URL asked for, not for the hosts they lead to.
"""

from __future__ import annotations

import contextlib
import email.utils
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from email.message import Message
from pathlib import Path

HOMEPAGE = "https://github.com/ajbarea/techne"
VERSION = "1.0"
TIMEOUT = 25
MAX_RETRIES = 3
BACKOFF = (5.0, 20.0, 60.0)
MAX_WAIT = 300.0
ARXIV_API_HOST = "export.arxiv.org"
RETRY_STATUSES = (429, 503)
# Statuses a caller can report as "the host is throttling" rather than "no such record".
THROTTLED_STATUSES = (406, 429, 503)

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
# Hosts whose endpoints are documented APIs: robots.txt is not consulted for them.
API_HOSTS = frozenset(h for h in INTERVALS if h != "arxiv.org")


class PoliteError(Exception):
    """Base class for what `fetch` raises."""


class HttpStatus(PoliteError):
    """The host answered with an HTTP error status, after any retries."""

    def __init__(self, status: int, host: str):
        super().__init__(f"http {status} from {host}")
        self.status = status
        self.host = host


class Unreachable(PoliteError):
    """The host did not answer: DNS, connection, TLS or timeout."""

    def __init__(self, host: str):
        super().__init__(f"unreachable: {host}")
        self.host = host


class RobotsDisallowed(PoliteError):
    """robots.txt forbids fetching the path, or could not be read."""

    def __init__(self, host: str, path: str, reason: str = "disallows"):
        super().__init__(f"not fetched: robots.txt {reason} {path}")
        self.host = host
        self.path = path


def user_agent(tool: str, mailto: str | None = None, version: str = VERSION) -> str:
    contact = f"; mailto:{mailto}" if mailto else ""
    return f"{tool}/{version} (+{HOMEPAGE}{contact})"


def needs_robots(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "").lower() not in API_HOSTS


def interval(host: str, *, mailto: str | None = None, token: bool = False) -> float:
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
    override = os.environ.get("TECHNE_POLITE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "techne" / "polite-http"


def _lock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        while True:  # LK_LOCK gives up after ten tries; keep waiting
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError:
                continue
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


_MEMORY: dict[str, float] = {}


class _Pace:
    """The earliest time the next request to a host may go out, shared through a stamp file."""

    def __init__(self, name: str, stamp: Path | None):
        self.name = name
        self.stamp = stamp

    def get(self) -> float:
        if self.stamp is None:
            return _MEMORY.get(self.name, 0.0)
        try:
            return float(self.stamp.read_text())
        except (OSError, ValueError):
            return 0.0

    def put(self, not_before: float) -> None:
        if self.stamp is None:
            _MEMORY[self.name] = not_before
            return
        try:
            self.stamp.write_text(repr(not_before))
        except OSError:
            _MEMORY[self.name] = not_before

    def wait(self) -> None:
        now = _now()
        # A stamp far in the future is corrupt or from a skewed clock; never wait past the cap.
        remaining = min(self.get() - now, MAX_WAIT)
        if remaining > 0:
            _sleep(remaining)


@contextlib.contextmanager
def _host_lock(host: str) -> Generator[_Pace]:
    name = "".join(c if c.isalnum() or c in ".-" else "_" for c in host.lower())
    try:
        directory = state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(directory / f"{name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        # No writable cache: still pace within this process.
        yield _Pace(name, None)
        return
    try:
        _lock(fd)
        try:
            yield _Pace(name, directory / f"{name}.stamp")
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


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


def retry_wait(
    host: str, status: int, headers: Mapping[str, str] | Message, attempt: int
) -> float | None:
    """Seconds to wait before retrying, or None when the status must not be retried."""
    if status not in RETRY_STATUSES and not (status == 406 and host == ARXIV_API_HOST):
        return None
    lowered = {k.lower(): v for k, v in headers.items()}
    now = _now()
    if "retry-after" in lowered:
        parsed = _parse_retry_after(str(lowered["retry-after"]), now)
        if parsed is not None:
            return min(parsed, MAX_WAIT)
    if str(lowered.get("x-ratelimit-remaining", "")).strip() == "0":
        reset = str(lowered.get("x-ratelimit-reset", "")).strip()
        if reset.isdigit():
            return min(max(0.0, float(reset) - now), MAX_WAIT)
    return BACKOFF[min(attempt, len(BACKOFF) - 1)]


# --- sending -----------------------------------------------------------------------------


def _send(
    req: urllib.request.Request,
    timeout: float,
    max_bytes: int | None,
    opener: urllib.request.OpenerDirector | None,
) -> bytes:
    resp = (
        opener.open(req, timeout=timeout)
        if opener
        else urllib.request.urlopen(req, timeout=timeout)
    )
    try:
        return resp.read(max_bytes) if max_bytes else resp.read()
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


def _exchange(
    req: urllib.request.Request,
    *,
    host: str,
    gap: float,
    timeout: float,
    max_bytes: int | None,
    opener: urllib.request.OpenerDirector | None,
) -> bytes:
    with _host_lock(host) as pace:
        for attempt in range(MAX_RETRIES + 1):
            pace.wait()
            next_ok = gap
            try:
                body = _send(req, timeout, max_bytes, opener)
            except urllib.error.HTTPError as exc:
                wait = retry_wait(host, exc.code, exc.headers or {}, attempt)
                if wait is not None:
                    next_ok = wait
                if wait is None or attempt == MAX_RETRIES:
                    raise HttpStatus(exc.code, host) from exc
                continue
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                raise Unreachable(host) from exc
            else:
                return body
            finally:
                pace.put(_now() + next_ok)
    raise AssertionError("unreachable")


@dataclass
class _Rules:
    parser: urllib.robotparser.RobotFileParser | None  # None means disallow all
    delay: float
    reason: str = "disallows"


_ROBOTS: dict[tuple[str, str], _Rules] = {}


def _robots_rules(
    scheme: str, netloc: str, *, tool: str, mailto: str | None, timeout: float
) -> _Rules:
    key = (scheme, netloc)
    if key in _ROBOTS:
        return _ROBOTS[key]
    url = f"{scheme}://{netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    try:
        raw = fetch(url, tool=tool, mailto=mailto, timeout=timeout, max_bytes=512_000)
    except HttpStatus as exc:
        if exc.status < 500 and exc.status != 429:
            parser.parse([])  # RFC 9309: robots.txt unavailable with a 4xx means no rules
            rules = _Rules(parser, 0.0)
        else:
            rules = _Rules(None, 0.0, "is unavailable for")
    except Unreachable:
        rules = _Rules(None, 0.0, "is unreachable for")
    else:
        parser.parse(raw.decode("utf-8", errors="replace").splitlines())
        rules = _Rules(parser, float(parser.crawl_delay(user_agent(tool, mailto)) or 0))
    _ROBOTS[key] = rules
    return rules


def check_robots(
    url: str, *, tool: str, mailto: str | None = None, timeout: float = TIMEOUT
) -> float:
    """Raise RobotsDisallowed unless robots.txt lets this tool fetch the URL.

    Returns the host's Crawl-delay in seconds (0 when it sets none).
    """
    parts = urllib.parse.urlsplit(url)
    rules = _robots_rules(parts.scheme, parts.netloc, tool=tool, mailto=mailto, timeout=timeout)
    path = parts.path or "/"
    if rules.parser is None:
        raise RobotsDisallowed(parts.netloc, path, rules.reason)
    if not rules.parser.can_fetch(user_agent(tool, mailto), url):
        raise RobotsDisallowed(parts.netloc, path)
    return rules.delay


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
    opener: urllib.request.OpenerDirector | None = None,
    page: bool = False,
) -> bytes:
    """GET (or POST with `data`) one URL politely. Raises HttpStatus, Unreachable or
    RobotsDisallowed. Pass `page=True` for a page fetch to check robots.txt first."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.netloc or "").lower()
    delay = 0.0
    if page:
        delay = check_robots(url, tool=tool, mailto=mailto, timeout=timeout)
    merged = {"User-Agent": user_agent(tool, mailto), **(headers or {})}
    token = any(k.lower() == "authorization" for k in merged)
    gap = max(interval(host, mailto=mailto, token=token), delay)
    req = urllib.request.Request(url, data=data, headers=merged, method=method)
    return _exchange(req, host=host, gap=gap, timeout=timeout, max_bytes=max_bytes, opener=opener)
