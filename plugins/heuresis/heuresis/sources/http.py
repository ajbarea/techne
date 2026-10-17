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
    """A source could not answer: unreachable, an HTTP error, or an unusable body.

    `status` is the HTTP status code when the failure was an HTTP error, else None.
    """

    def __init__(self, message: str = "", status: int | None = None):
        super().__init__(message)
        self.status = status


WEB_SCHEMES = ("http", "https")
# Keys and tokens are meant for the host they were sent to, never one it redirects to.
CREDENTIAL_HEADERS = frozenset({"x-api-key", "authorization"})


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme not in WEB_SCHEMES:
            raise SourceError(f"redirect to unsupported scheme: {target.scheme or 'none'}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and target.hostname != urllib.parse.urlsplit(req.full_url).hostname:
            for name in [n for n in new.headers if n.lower() in CREDENTIAL_HEADERS]:
                del new.headers[name]
        return new


_OPENER = urllib.request.build_opener(_Redirect)


def _open(req: urllib.request.Request) -> bytes:
    parts = urllib.parse.urlsplit(req.full_url)
    if parts.scheme not in WEB_SCHEMES:
        raise SourceError(f"unsupported scheme: {parts.scheme}")
    host = parts.netloc
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
            return resp.read(MAX_BYTES)
    except urllib.error.HTTPError as exc:
        raise SourceError(f"http {exc.code} from {host}", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise SourceError(f"unreachable: {host}") from exc


def get(url: str, headers: dict[str, str] | None = None) -> bytes:
    return _open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}))


def post_json(url: str, body: dict, headers: dict[str, str] | None = None) -> bytes:
    data = json.dumps(body).encode()
    merged = {"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})}
    return _open(urllib.request.Request(url, data=data, headers=merged, method="POST"))


def post_form(url: str, fields: dict[str, str], headers: dict[str, str] | None = None) -> bytes:
    data = urllib.parse.urlencode(fields).encode()
    merged = {"User-Agent": USER_AGENT, **(headers or {})}
    return _open(urllib.request.Request(url, data=data, headers=merged, method="POST"))


def json_object(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise SourceError("response was not JSON") from exc
    if not isinstance(data, dict):
        raise SourceError("response JSON was not an object")
    return data
