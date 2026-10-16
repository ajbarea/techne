"""One HTTP helper for every source: identifying user agent, timeout, size cap, plain errors."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "heuresis (https://github.com/ajbarea/techne)"
TIMEOUT = 20
# Answers above 2 MB are not read whole; the quote check needs text, not media.
MAX_BYTES = 2_000_000


class SourceError(Exception):
    """A source could not answer: unreachable, an HTTP error, or an unusable body."""


def _open(req: urllib.request.Request) -> bytes:
    host = urllib.parse.urlsplit(req.full_url).netloc
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read(MAX_BYTES)
    except urllib.error.HTTPError as exc:
        raise SourceError(f"http {exc.code} from {host}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise SourceError(f"unreachable: {host}") from exc


def get(url: str, headers: dict[str, str] | None = None) -> bytes:
    return _open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}))


def post_json(url: str, body: dict, headers: dict[str, str] | None = None) -> bytes:
    data = json.dumps(body).encode()
    merged = {"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})}
    return _open(urllib.request.Request(url, data=data, headers=merged, method="POST"))
