#!/usr/bin/env python3
"""Read the length budget a document declares and compare its PDF with it.

A document declares its budget on one comment line of its source, before drafting:

    % budget: 4 pages                LaTeX
    <!-- budget: 1200 words -->      markdown
    % budget: 4 pages, 3000 words    both limits

Pages count the whole PDF. Words count the reading text: the reference list is
dropped, and in markdown so are code, link targets and comments. The latex and
pdf gates block a build over budget and ask for one when none is declared.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
from typing import NamedTuple

import prose_check

_TEX_LINE = re.compile(r"^[ \t]*%+[ \t]*budget[ \t]*:(?P<spec>.*?)[ \t]*$", re.I | re.M)
_MD_LINE = re.compile(r"^[ \t]*<!--[ \t]*budget[ \t]*:(?P<spec>.*?)-->[ \t]*$", re.I | re.M)
_MD_FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1", re.M | re.S)
_ITEM = re.compile(r"^(?P<n>\d+)\s+(?P<unit>pages?|words?)$", re.I)
_WORD = re.compile(r"[^\W_]")
_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![s\w])")


class Budget(NamedTuple):
    pages: int | None
    words: int | None


def read(source: str, markdown: bool = False) -> Budget | None:
    """The budget the source declares, or None. Raises ValueError on one it cannot read.

    LaTeX declares it in a `%` comment, markdown in an HTML comment outside fenced code.
    """
    if markdown:
        lines = list(_MD_LINE.finditer(_MD_FENCE.sub("", source)))
    else:
        lines = list(_TEX_LINE.finditer(source))
    if not lines:
        return None
    if len(lines) > 1:
        raise ValueError(f"{len(lines)} budget lines; declare one")
    limits: dict[str, int] = {}
    for item in re.split(r"\s*,\s*", lines[0]["spec"].strip()):
        match = _ITEM.match(item)
        if not match:
            raise ValueError(f"cannot read {item!r}; write `N pages`, `N words` or both")
        unit = match["unit"].lower().rstrip("s")
        if unit in limits:
            raise ValueError(f"two {unit} limits")
        if int(match["n"]) < 1:
            raise ValueError(f"a budget of {match['n']} {unit}s")
        limits[unit] = int(match["n"])
    return Budget(limits.get("page"), limits.get("word"))


def count_words(text: str) -> int:
    """Tokens holding a letter or digit, so table bars and bullets do not count."""
    return sum(1 for token in prose_check.body_of(text).split() if _WORD.search(token))


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
    found = len(_PAGE_OBJECT.findall(pdf.read_bytes()))
    return found or None


def compare(budget: Budget, pages: int | None, words: int) -> tuple[list[str], str]:
    """Each limit the document is over, and the measured length, e.g. `5 of 4 pages`."""
    over, measured = [], []
    if budget.pages is not None:
        shown = "?" if pages is None else str(pages)
        measured.append(f"{shown} of {budget.pages} pages")
        if pages is not None and pages > budget.pages:
            over.append(f"{pages} pages, budget {budget.pages}")
    if budget.words is not None:
        measured.append(f"{words} of {budget.words} words")
        if words > budget.words:
            over.append(f"{words} words, budget {budget.words}")
    return over, ", ".join(measured)


MISSING = "no length budget declared; set one before drafting ({hint})"
OVER = "over budget: {over}. Cut repeated results and retold material, not substance"
