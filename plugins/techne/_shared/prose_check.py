#!/usr/bin/env python3
"""Flag prose patterns from plain-prose.md in a document's text.

Run with ``python prose_check.py <file>`` on a .md, .txt or .pdf (needs poppler
for .pdf). The latex and pdf gates import it and report hits as REVIEW
findings. It never decides an exit code: a hit is a line to look at, not a
defect.

The patterns live in the ``prose-patterns`` block of plain-prose.md beside this
file, so the rubric a writer reads and the check a build runs cannot drift.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from typing import NamedTuple

RUBRIC = pathlib.Path(__file__).resolve().parent / "plain-prose.md"
LONG_SENTENCE_WORDS = 40

_BLOCK = re.compile(r"```prose-patterns\n(?P<body>.*?)```", re.S)
# The reference list is citations, not prose; everything after its heading is skipped.
_REFERENCES = re.compile(r"^\s*(?:R\s?EFERENCES|References|Bibliography)\s*$", re.M)
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
_ENDS_SENTENCE = re.compile(r"[.!?][\"'\u201d)\]]*$")
_MD_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_MD_LINK_URL = re.compile(r"\]\([^)]*\)")


class Hit(NamedTuple):
    name: str
    count: int
    example: str


def load_patterns(rubric: pathlib.Path = RUBRIC) -> list[tuple[str, re.Pattern[str]]]:
    match = _BLOCK.search(rubric.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"no prose-patterns block in {rubric}")
    patterns = []
    for line in match["body"].splitlines():
        if not line.strip():
            continue
        name, _, regex = line.partition("|")
        patterns.append((name.strip(), re.compile(regex.strip(), re.I)))
    return patterns


def body_of(text: str) -> str:
    """Drop the reference list and rejoin words hyphenated across a line break."""
    refs = list(_REFERENCES.finditer(text))
    if refs:
        text = text[: refs[-1].start()]
    return _HYPHEN_BREAK.sub(r"\1\2", text)


def markdown_prose(text: str) -> str:
    """Code and link targets are not prose."""
    return _MD_LINK_URL.sub("]", _MD_CODE.sub(" ", text))


def _snippet(text: str, start: int, end: int, pad: int = 30) -> str:
    return " ".join(text[max(0, start - pad) : end + pad].split())


def check(
    text: str,
    patterns: list[tuple[str, re.Pattern[str]]] | None = None,
    long_words: int = LONG_SENTENCE_WORDS,
) -> list[Hit]:
    patterns = load_patterns() if patterns is None else patterns
    text = body_of(text)
    hits = []
    for name, regex in patterns:
        found = list(regex.finditer(text))
        if found:
            first = found[0]
            hits.append(Hit(name, len(found), _snippet(text, first.start(), first.end())))

    # A title block, heading or table row has no full stop, so it is not a sentence.
    long = [
        sentence
        for paragraph in _PARAGRAPH.split(text)
        for sentence in _SENTENCE_END.split(" ".join(paragraph.split()))
        if len(sentence.split()) > long_words and _ENDS_SENTENCE.search(sentence)
    ]
    if long:
        words = long[0].split()
        hits.append(Hit("long-sentence", len(long), " ".join(words[:12]) + " ..."))
    return hits


def pdf_text(pdf: pathlib.Path) -> str:
    """Reading order, not -layout: two-column layout interleaves the sentences."""
    proc = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True)
    return proc.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", type=pathlib.Path, help="a .md, .txt or .pdf")
    args = ap.parse_args()

    if args.path.suffix == ".pdf":
        text = pdf_text(args.path)
    else:
        text = args.path.read_text(encoding="utf-8", errors="replace")
        if args.path.suffix == ".md":
            text = markdown_prose(text)

    hits = check(text)
    for hit in hits:
        print(f"REVIEW {hit.name:<16} {hit.count}x  “{hit.example}”")
    if not hits:
        print("no prose patterns found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
