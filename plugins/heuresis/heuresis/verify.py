"""Check that every quoted passage appears in its source. Code, not a second model."""

from __future__ import annotations

import html
import json
import os
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from heuresis import sources, store
from heuresis.model import Record
from heuresis.sources import http

# Under 20 characters a phrase like "federated learning" matches almost any page in the field.
MIN_QUOTE = 20
FOLD = str.maketrans(
    {
        "\N{LEFT SINGLE QUOTATION MARK}": "'",
        "\N{RIGHT SINGLE QUOTATION MARK}": "'",
        "\N{LEFT DOUBLE QUOTATION MARK}": '"',
        "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
        "\N{EN DASH}": "-",
        "\N{EM DASH}": "-",
        "\N{NO-BREAK SPACE}": " ",
        "\N{HYPHEN}": "-",
        "\N{NON-BREAKING HYPHEN}": "-",
    }
)
# Soft hyphens and zero-width characters are invisible in a rendered page but split words in source.
INVISIBLE = dict.fromkeys(
    map(ord, "\N{SOFT HYPHEN}\N{ZERO WIDTH SPACE}\N{ZERO WIDTH NON-JOINER}\N{ZERO WIDTH JOINER}")
)
# Every tag but these ends a word or line, so it becomes a space; an inline tag (a, em, span)
# must not split a word.
INLINE = frozenset("a abbr b cite code em i mark small span strong sub sup u".split())


class _Refused(Exception):
    """The record names evidence outside the places verify may read."""


class _Text(HTMLParser):
    SKIP = ("script", "style", "noscript", "template")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        self._gap(tag)

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        self._gap(tag)

    def _gap(self, tag):
        if tag not in INLINE and not self.depth:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def html_text(raw: str) -> str:
    parser = _Text()
    parser.feed(raw)
    parser.close()  # flushes trailing text the parser holds back while it waits for a tag
    return "".join(parser.parts)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(FOLD)
    text = text.translate(INVISIBLE)
    return re.sub(r"\s+", " ", text).strip().lower()


def _strings(value) -> list[str]:
    # Leaves can carry markup (Hacker News story_text), so each is de-tagged like a page.
    if isinstance(value, str):
        return [html_text(value)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _xml_text(node: ET.Element) -> str:
    local = node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""
    edge = "" if local in INLINE else " "
    inner = node.text or ""
    for child in node:
        inner += _xml_text(child) + (child.tail or "")
    return f"{edge}{inner}{edge}"


def _decode(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").removeprefix("\ufeff")
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            return " ".join(_strings(json.loads(text)))
        except ValueError:
            pass
    if stripped.startswith("<?xml") or stripped.startswith("<feed"):
        try:
            return _xml_text(ET.fromstring(body.removeprefix(b"\xef\xbb\xbf")))
        except ET.ParseError:
            pass
    return html_text(text)


def _headers(url: str) -> dict[str, str]:
    host = urllib.parse.urlsplit(url).netloc
    if host == "api.semanticscholar.org" and os.environ.get("S2_API_KEY"):
        return {"x-api-key": os.environ["S2_API_KEY"]}
    return {}


def _bad_repo_path(rel: PurePosixPath) -> bool:
    return rel.is_absolute() or ".." in rel.parts or not rel.parts


def _web_problem(url: str) -> str | None:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    return (
        None if scheme in ("http", "https") else f"url scheme {scheme or 'missing'!r} not allowed"
    )


def record_problem(record: Record) -> str | None:
    """Why the record's url cannot be read as evidence, or None when it can."""
    if record.url.startswith("idea:"):
        ok = store.IDEA_ID.fullmatch(record.url.removeprefix("idea:"))
        return None if ok else "invalid idea id"
    if record.url.startswith("repo:"):
        bad = _bad_repo_path(PurePosixPath(record.url.removeprefix("repo:")))
        return "repo path must be relative with no '..'" if bad else None
    return _web_problem(record.url) or (
        _web_problem(record.evidence_url) if record.evidence_url else None
    )


def evidence_text(record: Record, ideas_root: Path, repos_root: Path) -> str:
    if record.url.startswith("idea:"):
        idea_id = record.url.removeprefix("idea:")
        if not store.IDEA_ID.fullmatch(idea_id):
            raise _Refused("invalid idea id")
        return (ideas_root / "ideas" / f"{idea_id}.md").read_text()
    if record.url.startswith("repo:"):
        rel = PurePosixPath(record.url.removeprefix("repo:"))
        if _bad_repo_path(rel):
            raise _Refused("path outside repos root")
        return (repos_root / rel).read_text(errors="replace")
    source = sources.by_name(record.source)
    if source is not None:
        own = source.evidence(record)
        if own is not None:
            return own
    url = record.evidence_url or record.url
    return _decode(http.get(url, _headers(url)))


def check(record: Record, quote: str, ideas_root: Path, repos_root: Path) -> tuple[bool, str]:
    wanted = normalize(str(quote or ""))
    if len(wanted) < MIN_QUOTE:
        return False, "quote too short"
    try:
        text = evidence_text(record, ideas_root, repos_root)
    except http.SourceError as exc:
        return False, str(exc)
    except _Refused as exc:
        return False, str(exc)
    except OSError as exc:
        return False, f"unreadable: {exc.strerror or exc}"
    except Exception as exc:  # a source's own evidence call failing must not stop the run
        return False, f"{type(exc).__name__}: {exc}"
    return (True, "") if wanted in normalize(text) else (False, "quote not found")
