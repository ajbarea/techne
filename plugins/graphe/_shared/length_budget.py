#!/usr/bin/env python3
"""Read the length budget a document declares and compare its PDF with it.

A document declares its budget on one comment line of its source, before drafting:

    % budget: 4 pages                LaTeX
    <!-- budget: 1200 words -->      markdown
    % budget: 4 pages, 3000 words    both limits
    % budget: none                   no limit; the length is still reported

Pages count the whole PDF. Words count the reading text: the reference list is
dropped (appendices after it are kept), and in markdown so are code, link targets
and comments. The latex and pdf gates block a build over budget, ask for a budget
when none is declared, and ask for a look when a declared page limit cannot be counted.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import zlib
from typing import NamedTuple

import prose_check

_TEX_LINE = re.compile(r"^[ \t]*%+[ \t]*budget[ \t]*:(?P<spec>.*?)[ \t]*$", re.I | re.M)
_MD_LINE = re.compile(r"^[ \t]*<!--[ \t]*budget[ \t]*:(?P<spec>.*?)-->[ \t]*$", re.I | re.M)
# Where a budget line is example text, not a declaration.
_TEX_QUOTED = re.compile(
    r"\\begin\{(verbatim|lstlisting|minted|comment)\*?\}.*?\\end\{\1\*?\}"
    r"|\\iffalse\b.*?\\fi\b",
    re.S,
)
_NOTE = re.compile(r"\s*\([^()]*\)\s*$")
_NO_LIMIT = re.compile(r"^(?:none|unlimited|no limit)$", re.I)
_ITEM = re.compile(r"^(?P<n>\d{1,3}(?:,\d{3})+|\d+)\s+(?P<unit>pages?|words?)$", re.I)
# A comma between digits is a thousands separator (3,000), not a list break.
_SEPARATOR = re.compile(r"\s*;\s*|,\s+|(?<=\D),|\s+and\s+", re.I)
_WORD = re.compile(r"[^\W_]")
_APPENDIX = re.compile(r"\\appendix\b(?P<rest>.*)", re.S)
_SECTION_TITLE = re.compile(r"\\(?:chapter|section)\*?\s*(?:\[[^\]]*\])?\s*\{(?P<title>[^{}]+)\}")
_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![s\w])")
_PAGE_COUNT = re.compile(
    rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)|/Count\s+(\d+)[^>]*?/Type\s*/Pages\b"
)
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)


class Budget(NamedTuple):
    pages: int | None
    words: int | None


def read(source: str, markdown: bool = False) -> Budget | None:
    """The budget the source declares, or None. Raises ValueError on one it cannot read.

    LaTeX declares it in a `%` comment, markdown in an HTML comment, both outside code.
    `none` declares no limit: Budget(None, None). A trailing `(note)` is ignored.
    """
    if markdown:
        lines = list(_MD_LINE.finditer(prose_check.MD_FENCE.sub("", source)))
    else:
        lines = list(_TEX_LINE.finditer(_TEX_QUOTED.sub("", source)))
    if not lines:
        return None
    if len(lines) > 1:
        raise ValueError(f"{len(lines)} budget lines; declare one")
    spec = _NOTE.sub("", lines[0]["spec"]).strip()
    if _NO_LIMIT.match(spec):
        return Budget(None, None)
    limits: dict[str, int] = {}
    for item in _SEPARATOR.split(spec):
        match = _ITEM.match(item.strip())
        if not match:
            raise ValueError(f"cannot read {item!r}; write `N pages`, `N words`, both, or `none`")
        unit = match["unit"].lower().rstrip("s")
        n = int(match["n"].replace(",", ""))
        if unit in limits:
            raise ValueError(f"two {unit} limits")
        if n < 1:
            raise ValueError(f"a budget of {n} {unit}s")
        limits[unit] = n
    return Budget(limits.get("page"), limits.get("word"))


def count_words(text: str, resume: tuple[str, ...] = ()) -> int:
    """Tokens holding a letter or digit, so table bars and bullets do not count.

    `resume` names the appendix titles that end a reference list; see appendix_titles.
    """
    return sum(1 for token in prose_check.body_of(text, resume).split() if _WORD.search(token))


def appendix_titles(tex_source: str) -> tuple[str, ...]:
    """Titles of the sections after `\\appendix`, which the PDF text prints after the references."""
    match = _APPENDIX.search(tex_source)
    if not match:
        return ()
    return tuple(m["title"].strip() for m in _SECTION_TITLE.finditer(match["rest"]))


def count_markdown_words(source: str) -> int:
    """Words of a markdown source, without code, link targets or comments."""
    return count_words(prose_check.markdown_prose(source))


def pdf_pages(pdf: pathlib.Path) -> int | None:
    if not pdf.is_file():
        return None
    if shutil.which("pdfinfo"):
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        match = re.search(r"^Pages:\s+(\d+)", info, re.M)
        if match:
            return int(match[1])
    return _count_pages(pdf.read_bytes())


def _count_pages(data: bytes) -> int | None:
    """The page tree's /Count, else page objects, looking inside compressed object streams.

    The largest /Count is the root's; it survives incremental updates that repeat page objects.
    """
    chunks = [data]
    for stream in _STREAM.finditer(data):
        try:
            chunks.append(zlib.decompress(stream[1]))
        except zlib.error:
            continue
    counts = [int(a or b) for chunk in chunks for a, b in _PAGE_COUNT.findall(chunk)]
    if counts:
        return max(counts) or None
    return sum(len(_PAGE_OBJECT.findall(chunk)) for chunk in chunks) or None


class Verdict(NamedTuple):
    over: list[str]
    measured: str
    unmeasured: bool


def compare(budget: Budget, pages: int | None, words: int) -> Verdict:
    """Each limit the document is over, the measured length (`5 of 4 pages`), and whether
    a declared page limit could not be counted."""
    over = []
    shown = "?" if pages is None else str(pages)
    if budget.pages is None:
        page_part = f"{shown} pages"
    else:
        page_part = f"{shown} of {budget.pages} pages"
        if pages is not None and pages > budget.pages:
            over.append(f"{pages} pages, budget {budget.pages}")
    if budget.words is None:
        word_part = f"{words} words"
    else:
        word_part = f"{words} of {budget.words} words"
        if words > budget.words:
            over.append(f"{words} words, budget {budget.words}")
    measured = f"{page_part}, {word_part}"
    if budget == Budget(None, None):
        measured += " (no limit declared)"
    return Verdict(over, measured, budget.pages is not None and pages is None)


MISSING = "no length budget declared; set one before drafting ({hint})"
UNMEASURED = "could not count the PDF's pages against the page limit ({measured}); check by eye"
OVER = "over budget: {over}. Cut repeated results and retold material, not substance"
