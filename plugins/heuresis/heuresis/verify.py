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
from pathlib import Path

from heuresis import sources
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
    }
)


class _Text(HTMLParser):
    SKIP = ("script", "style", "noscript", "template")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def html_text(raw: str) -> str:
    parser = _Text()
    parser.feed(raw)
    parser.close()  # flushes trailing text the parser holds back while it waits for a tag
    return " ".join(parser.parts)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(FOLD)
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


def _decode(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            return " ".join(_strings(json.loads(text)))
        except ValueError:
            pass
    if stripped.startswith("<?xml") or stripped.startswith("<feed"):
        try:
            return " ".join(ET.fromstring(body).itertext())
        except ET.ParseError:
            pass
    return html_text(text)


def _headers(url: str) -> dict[str, str]:
    host = urllib.parse.urlsplit(url).netloc
    if host == "api.semanticscholar.org" and os.environ.get("S2_API_KEY"):
        return {"x-api-key": os.environ["S2_API_KEY"]}
    return {}


def evidence_text(record: Record, ideas_root: Path, repos_root: Path) -> str:
    if record.url.startswith("idea:"):
        return (ideas_root / "ideas" / f"{record.url.removeprefix('idea:')}.md").read_text()
    if record.url.startswith("repo:"):
        return (repos_root / record.url.removeprefix("repo:")).read_text(errors="replace")
    source = sources.by_name(record.source)
    if source is not None:
        own = source.evidence(record)
        if own is not None:
            return own
    url = record.evidence_url or record.url
    return _decode(http.get(url, _headers(url)))


def check(record: Record, quote: str, ideas_root: Path, repos_root: Path) -> tuple[bool, str]:
    wanted = normalize(quote)
    if len(wanted) < MIN_QUOTE:
        return False, "quote too short"
    try:
        text = evidence_text(record, ideas_root, repos_root)
    except http.SourceError as exc:
        return False, str(exc)
    except OSError as exc:
        return False, f"unreadable: {exc.strerror or exc}"
    except Exception as exc:  # a source's own evidence call failing must not stop the run
        return False, f"{type(exc).__name__}: {exc}"
    return (True, "") if wanted in normalize(text) else (False, "quote not found")
