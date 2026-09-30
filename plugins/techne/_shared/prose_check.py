#!/usr/bin/env python3
"""Flag prose patterns from plain-prose.md and hate-words.md in a document's text.

Run with ``python prose_check.py <file>`` on a .md, .txt or .pdf (needs poppler
for .pdf). The latex and pdf gates import it and report hits as REVIEW
findings. It never decides an exit code: a hit is a line to look at, not a
defect.

Patterns come from the ``prose-patterns`` block of plain-prose.md and the
"Modern LLM tells" section of hate-words.md, both beside this file, so the
rubric a writer reads and the check a build runs cannot drift.
"""

from __future__ import annotations

import argparse
import functools
import pathlib
import re
import subprocess
import sys
from typing import NamedTuple

HERE = pathlib.Path(__file__).resolve().parent
RUBRIC = HERE / "plain-prose.md"
GLOSSARY = HERE / "hate-words.md"
GLOSSARY_SECTION = "Modern LLM tells"
LONG_SENTENCE_WORDS = 40

Patterns = list[tuple[str, re.Pattern[str]]]

_BLOCK = re.compile(r"```prose-patterns\n(?P<body>.*?)```", re.S)
_BACKTICKED = re.compile(r"`([^`]+)`")
# A reference list is citations, not prose. It ends at the next heading (an appendix) or the end.
_REFERENCES = re.compile(r"^\s*(?:#{1,6}\s*)?(?:R\s?EFERENCES|References|Bibliography)\s*$", re.M)
_NEXT_HEADING = re.compile(r"^\s*(?:#{1,6}\s+\S|(?:A\s?PPENDIX|Appendix)\b)", re.M)
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
# Paragraph breaks, and the start of a list item or table row: none of these ends in a full stop.
_BLOCK_BREAK = re.compile(r"\n\s*\n|\n(?=\s*(?:[-*+•]\s|\d+[.)]\s|\|))")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
_ENDS_SENTENCE = re.compile(r"[.!?][\"'”)\]]*$")
_MD_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_MD_LINK_URL = re.compile(r"\]\([^)]*\)")
# Between words only: a table separator row (| --- |) and a rule line are not dashes.
_MD_TRIPLE_DASH = re.compile(r"(?<=\w)[ \t]*---[ \t]*(?=\w)")


class Hit(NamedTuple):
    name: str
    count: int
    example: str


def _compile(name: str, regex: str, source: pathlib.Path) -> tuple[str, re.Pattern[str]]:
    if not name or not regex:
        raise ValueError(f"{source}: pattern line needs `name | regex`, got {name!r} | {regex!r}")
    return name, re.compile(regex, re.I)


def _glossary_terms(glossary: pathlib.Path) -> list[str]:
    section = re.search(
        rf"^## {re.escape(GLOSSARY_SECTION)}\n(?P<body>.*?)(?=^## |\Z)",
        glossary.read_text(encoding="utf-8"),
        re.M | re.S,
    )
    if not section:
        return []
    return [
        term
        for line in section["body"].splitlines()
        if line.startswith("- ")
        for term in _BACKTICKED.findall(line)
    ]


def load_patterns(
    rubric: pathlib.Path = RUBRIC, glossary: pathlib.Path | None = GLOSSARY
) -> Patterns:
    """Raises ValueError or re.error on a malformed file; callers stay advisory."""
    match = _BLOCK.search(rubric.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"no prose-patterns block in {rubric}")
    patterns = []
    for line in match["body"].splitlines():
        if not line.strip():
            continue
        name, bar, regex = line.partition("|")
        if not bar:
            raise ValueError(f"{rubric}: pattern line without `|`: {line!r}")
        patterns.append(_compile(name.strip(), regex.strip(), rubric))

    if glossary is not None and glossary.exists():
        terms = _glossary_terms(glossary)
        if terms:
            joined = "|".join(rf"\b(?:{term})" for term in terms)
            patterns.append(_compile("llm-tell", joined, glossary))
    return patterns


@functools.cache
def default_patterns() -> Patterns:
    return load_patterns()


def report(text: str) -> tuple[list[Hit], str]:
    """The gates' entry point: hits, or why the check could not run. Never raises."""
    try:
        return check(text, default_patterns()), ""
    except (OSError, ValueError, re.error) as exc:
        return [], f"prose check skipped: {exc}"


def body_of(text: str) -> str:
    """Drop reference lists, keep appendices, and rejoin words hyphenated across a line."""
    while match := _REFERENCES.search(text):
        rest = text[match.end() :]
        nxt = _NEXT_HEADING.search(rest)
        text = text[: match.start()] + (rest[nxt.start() :] if nxt else "")
    return _HYPHEN_BREAK.sub(r"\1\2", text)


def markdown_prose(text: str) -> str:
    """Code and link targets are not prose. Typst's smart punctuation sets `---` as an em-dash."""
    text = _MD_LINK_URL.sub("]", _MD_CODE.sub(" ", text))
    return _MD_TRIPLE_DASH.sub("\u2014", text)


def _snippet(text: str, start: int, end: int, pad: int = 30) -> str:
    return " ".join(text[max(0, start - pad) : end + pad].split())


def check(
    text: str, patterns: Patterns | None = None, long_words: int = LONG_SENTENCE_WORDS
) -> list[Hit]:
    patterns = default_patterns() if patterns is None else patterns
    text = body_of(text)
    hits = []
    for name, regex in patterns:
        found = list(regex.finditer(text))
        if found:
            first = found[0]
            hits.append(Hit(name, len(found), _snippet(text, first.start(), first.end())))

    long = [
        sentence
        for block in _BLOCK_BREAK.split(text)
        for sentence in _SENTENCE_END.split(" ".join(block.split()))
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

    hits, skipped = report(text)
    if skipped:
        print(skipped, file=sys.stderr)
        return 1
    for hit in hits:
        print(f"REVIEW {hit.name:<16} {hit.count}x  “{hit.example}”")
    if not hits:
        print("no prose patterns found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
