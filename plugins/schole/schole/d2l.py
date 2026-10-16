"""Read a Brightspace (D2L) course site through its REST API: GET requests on an allowlist only.

The sweep never navigates into content, which would mark topics read and modules complete.
`get` is any callable that performs one GET on a site-relative path and returns the HTTP
status and body; the browser session supplies it, tests supply a fake.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from html.parser import HTMLParser
from urllib.parse import quote

Get = Callable[[str], tuple[int, str]]

LP = "/d2l/api/lp/1.30"
LE = "/d2l/api/le/1.30"
ENROLLMENTS = f"{LP}/enrollments/myenrollments/?orgUnitTypeId=3&pageSize=200"
DUE_AHEAD = timedelta(days=14)
TEXT_CAP = 90
BODY_CAP = 280
MAX_PAGES = 20

# Every request the sweep may make. A path outside these is refused before it is sent.
ALLOWED = (
    re.compile(
        r"/d2l/api/lp/1\.30/enrollments/myenrollments/\?orgUnitTypeId=3&pageSize=200(&bookmark=[A-Za-z0-9_.%-]+)?"
    ),
    re.compile(r"/d2l/api/le/1\.30/\d+/news/"),
    re.compile(r"/d2l/api/le/1\.30/\d+/content/toc"),
    re.compile(r"/d2l/api/le/1\.30/\d+/dropbox/folders/"),
    re.compile(r"/d2l/lms/dropbox/user/folders_list\.d2l\?ou=\d+"),
)


class NoSession(RuntimeError):
    """The site answered with its login page instead of data."""


class SiteError(RuntimeError):
    """The site failed in a way signing in again would not fix (5xx, 429, endless paging)."""


def allowed(path: str) -> bool:
    return any(p.fullmatch(path) for p in ALLOWED)


def guarded(get: Get) -> Get:
    def checked(path: str) -> tuple[int, str]:
        if not allowed(path):
            raise PermissionError(f"schole refuses to request {path!r}")
        return get(path)

    return checked


_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean(text: object, cap: int = TEXT_CAP) -> str:
    """One line, no control characters, capped."""
    s = _CONTROLS.sub(" ", str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= cap else s[: cap - 1] + "…"


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("br", "p", "div", "li", "tr"):
            self.out.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(html: str) -> str:
    parser = _Text()
    parser.feed(html or "")
    parser.close()
    return "".join(parser.out)


class _Rows(HTMLParser):
    """The text of each table row in the student Assignments page."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[str] = []
        self.cur: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cur = []
        elif tag in ("td", "th") and self.cur is not None:
            self.cur.append(" ")

    def handle_endtag(self, tag):
        if tag == "tr" and self.cur is not None:
            self.rows.append(re.sub(r"\s+", " ", "".join(self.cur)).strip())
            self.cur = None

    def handle_data(self, data):
        if self.cur is not None:
            self.cur.append(data)


def rows(html: str) -> list[str]:
    parser = _Rows()
    parser.feed(html or "")
    parser.close()
    return parser.rows


def parse_time(value: object) -> datetime | None:
    """An ISO time; one without a zone is UTC, as the D2L API means it."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Course:
    ou: int
    name: str
    code: str


def _json(status: int, body: str) -> object | None:
    if status != 200:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def courses(get: Get, term: str) -> list[Course]:
    """Every course enrollment whose code contains term. NoSession on a login page or a refusal,
    SiteError on a server failure or paging that does not end."""
    pattern = re.compile(re.escape(term)) if term else None
    found: list[Course] = []
    path = ENROLLMENTS
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        status, body = get(path)
        if 300 <= status < 400 or status in (401, 403):
            raise NoSession(f"enrollments returned HTTP {status}")
        if status != 200:
            raise SiteError(f"enrollments returned HTTP {status}")
        data = _json(status, body)
        if not isinstance(data, dict):
            raise NoSession("enrollments returned a page, not JSON")
        for item in data.get("Items") or []:
            unit = (item or {}).get("OrgUnit") or {}
            code, ou = str(unit.get("Code") or ""), unit.get("Id")
            if isinstance(ou, int) and (pattern is None or pattern.search(code)):
                found.append(Course(ou, str(unit.get("Name") or code), code))
        paging = data.get("PagingInfo") or {}
        mark = paging.get("Bookmark")
        if not paging.get("HasMoreItems") or not isinstance(mark, str) or not mark:
            return found
        if mark in seen:
            raise SiteError("enrollments repeated a page bookmark")
        seen.add(mark)
        path = f"{ENROLLMENTS}&bookmark={quote(mark, safe='')}"
    raise SiteError(f"enrollments did not finish within {MAX_PAGES} pages")


def _topics(modules: Iterable[dict]) -> list[dict]:
    out: list[dict] = []
    stack = list(modules)
    while stack:
        m = stack.pop()
        if not isinstance(m, dict):
            continue
        out.extend(t for t in m.get("Topics") or [] if isinstance(t, dict))
        stack.extend(m.get("Modules") or [])
    return out


def submission_state(listing: list[str] | None, name: str, status: int) -> str:
    """NOT SUBMITTED, '<n> submitted', or why it could not be checked."""
    if listing is None:
        return f"LISTFAIL {status}"
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return "NOROW"
    exact = [r for r in listing if re.match(re.escape(name) + r" ?Due on", r)]
    loose = [
        r for r in listing if r.startswith(name) and not r[len(name) : len(name) + 1].isdigit()
    ]
    row = (exact or loose or [None])[0]
    if row is None:
        return "NOROW"
    if "Not Submitted" in row:
        return "NOT SUBMITTED"
    m = re.search(r"(\d+) Submissions?", row)
    return f"{m.group(1)} submitted" if m else "state unknown"


def sweep(get: Get, term: str, since: datetime, now: datetime, tz: tzinfo) -> list[str]:
    """One status line per course (OK or APIFAIL) plus ANNOUNCE, CONTENT, DUE and PASTDUE
    lines for what changed since `since` or falls due in the next two weeks."""
    get = guarded(get)

    def fmt(moment: datetime) -> str:
        return moment.astimezone(tz).strftime("%a %b %d %H:%M %Z")

    lines: list[str] = []
    for c in courses(get, term):
        name = clean(c.name)
        results = {
            "news": get(f"{LE}/{c.ou}/news/"),
            "toc": get(f"{LE}/{c.ou}/content/toc"),
            "dbx": get(f"{LE}/{c.ou}/dropbox/folders/"),
        }
        data = {k: _json(*v) for k, v in results.items()}
        news = data["news"] if isinstance(data["news"], list) else None
        toc = data["toc"] if isinstance(data["toc"], dict) else None
        dbx = data["dbx"] if isinstance(data["dbx"], list) else None
        bad = [
            f"{k}:{results[k][0]}"
            for k, v in (("news", news), ("toc", toc), ("dbx", dbx))
            if v is None
        ]
        topics = _topics((toc or {}).get("Modules") or [])
        if bad:
            lines.append(f"APIFAIL {name} :: {' '.join(bad)}")
        else:
            lines.append(
                f"OK {name} :: news {len(news or [])} topics {len(topics)} dropbox {len(dbx or [])}"
            )
        for n in news or []:
            when = parse_time((n or {}).get("StartDate"))
            if when and when > since:
                body = clean(html_text(((n.get("Body") or {}).get("Html")) or ""), BODY_CAP)
                lines.append(
                    f"ANNOUNCE {name} :: {clean(n.get('Title'))} :: {fmt(when)}"
                    + (f" :: {body}" if body else "")
                )
        for t in topics:
            when = parse_time(t.get("LastModifiedDate"))
            if when and when > since:
                seen = "UNREAD" if t.get("Unread") else "seen"
                lines.append(f"CONTENT {name} :: {clean(t.get('Title'))} :: {fmt(when)} :: {seen}")
        past: list[tuple[str, datetime]] = []
        for d in dbx or []:
            due = parse_time((d or {}).get("DueDate"))
            if not due:
                continue
            if now < due <= now + DUE_AHEAD:
                lines.append(f"DUE {name} :: {clean(d.get('Name'))} :: {fmt(due)}")
            elif since < due <= now:
                past.append((str(d.get("Name") or ""), due))
        if past:
            status, body = get(f"/d2l/lms/dropbox/user/folders_list.d2l?ou={c.ou}")
            listing = rows(body) if status == 200 else None
            for folder, due in past:
                state = submission_state(listing, folder, status)
                lines.append(f"PASTDUE {name} :: {clean(folder)} :: {fmt(due)} :: {state}")
    return lines
