"""One HTTP helper for every source: size cap, plain errors, and polite_http underneath for the
per-host pacing across processes, Retry-After, the identifying User-Agent and robots.txt."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
import polite_http  # ty: ignore[unresolved-import]

TOOL = "heuresis"
TIMEOUT = 20
# Answers above 2 MB are not read whole; the quote check needs text, not media.
MAX_BYTES = 2_000_000


class SourceError(Exception):
    """A source could not answer: unreachable, an HTTP error, or an unusable body.

    `status` is the HTTP status code when the failure was an HTTP error, else None.
    """

    def __init__(self, message: str = "", status: int | None = None):
        super().__init__(message)
        self.status = status


WEB_SCHEMES = ("http", "https")
# Keys and tokens are meant for the host and scheme they were sent to, never a redirect elsewhere.
CREDENTIAL_HEADERS = frozenset({"x-api-key", "authorization"})


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme not in WEB_SCHEMES:
            raise SourceError(f"redirect to unsupported scheme: {target.scheme or 'none'}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        source = urllib.parse.urlsplit(req.full_url)
        # A downgrade to http would send the key in clear text, even to the same host.
        moved = (target.scheme, target.hostname) != (source.scheme, source.hostname)
        if new is not None and moved:
            for name in [n for n in new.headers if n.lower() in CREDENTIAL_HEADERS]:
                del new.headers[name]
        return new


_OPENER = urllib.request.build_opener(_Redirect)


RobotsDisallowed = polite_http.RobotsDisallowed


def _open(url: str, *, data: bytes | None, headers: dict[str, str] | None, page: bool) -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in WEB_SCHEMES:
        raise SourceError(f"unsupported scheme: {parts.scheme}")
    try:
        return polite_http.fetch(
            url,
            tool=TOOL,
            headers=headers,
            data=data,
            method="POST" if data is not None else None,
            mailto=os.environ.get("OPENALEX_MAILTO") or None,
            timeout=TIMEOUT,
            max_bytes=MAX_BYTES,
            opener=_OPENER,
            page=page,
        )
    except polite_http.HttpStatus as exc:
        raise SourceError(str(exc), status=exc.status) from exc
    except polite_http.Unreachable as exc:
        raise SourceError(str(exc)) from exc


def get(url: str, headers: dict[str, str] | None = None, *, page: bool = False) -> bytes:
    """GET `url`. `page=True` checks robots.txt first and may raise RobotsDisallowed."""
    return _open(url, data=None, headers=headers, page=page)


def post_form(url: str, fields: dict[str, str], headers: dict[str, str] | None = None) -> bytes:
    data = urllib.parse.urlencode(fields).encode()
    return _open(url, data=data, headers=headers, page=False)


def json_object(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise SourceError("response was not JSON") from exc
    if not isinstance(data, dict):
        raise SourceError("response JSON was not an object")
    return data
