"""Differential test: cleanup.py's Markdown scanner against a real CommonMark parser.

prune deletes the span from a done-log heading to the next heading of its level, so the scanner
must find exactly the headings CommonMark does. Generated documents mix ATX headings (0 to 3
spaces of indent, closing hashes), setext headings, fences with info strings and fence-like
lines inside them, list items with lazy continuations, thematic breaks, indented code and
paragraphs; any disagreement with markdown-it-py fails. Block quotes and HTML blocks are left
out on purpose: prune refuses a span that holds one.
"""

from __future__ import annotations

import importlib.util
import random

from conftest import CLEANUP_SCRIPT
from markdown_it import MarkdownIt

spec = importlib.util.spec_from_file_location("cleanup_md", CLEANUP_SCRIPT)
assert spec and spec.loader
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)

MD = MarkdownIt("commonmark")

PIECES = [
    "## Completed",
    "## Backlog",
    "# Roadmap",
    "### Done this week",
    " ## Indented one",
    "   ### Indented three",
    "    ## four spaces: code",
    "## Closing hashes ##",
    "#NoSpace",
    "Setext one\n==========",
    "Setext two\n----------",
    "para line\n---",
    "- item\n---",
    "- item\n  lazy continuation\n---",
    "1. numbered\n---",
    "***",
    "---",
    "```\n## not a heading\n```",
    "```js\n## not a heading\n```js\n## still code\n```",
    "~~~\n```\n## code\n~~~",
    "````\n```\n## code\n````",
    "```a`b\n## heading after a non-fence",
    "~~~py\n## code\n~~~",
    "plain paragraph",
    "two line\nparagraph",
    "",
    "    indented code\n    # not a heading",
    "- [ ] task\n- **x:** y",
    "- shipped:\n  ```sh\n  make run",  # a fence inside a list item
    "    ```\n    code",  # an indented fence-like line
    "</details>",
    "<details>",
    "> quoted\n> ## not a heading",
    "- x\u2028```",  # a line break CommonMark does not split on
    "  ```",  # a fence opened with indent
    "> q\n<!--",  # an HTML comment opened inside a quote, closed later
    "-->",
    "> q\n<pre>",
    "</pre>",
    "<kbd>k</kbd> text\n<?php",
    "?>",
    "> q\n<![CDATA[",
    "]]>",
]


def commonmark_heads(text: str) -> list[tuple[int, int]]:
    """Top-level headings only: one inside a list item is no section boundary."""
    return [
        (t.map[0], int(t.tag[1]))
        for t in MD.parse(text)
        if t.type == "heading_open" and t.map is not None and t.level == 0
    ]


def scanner_heads(text: str) -> list[tuple[int, int]]:
    return [(i, level) for i, level, _ in cleanup.Scan(text).heads]


def commonmark_sections(text: str) -> dict[int, int]:
    """First line -> last line, 1-based, of each top-level heading's section in CommonMark."""
    heads = commonmark_heads(text)
    n = len(text.splitlines())
    out: dict[int, int] = {}
    for k, (i, level) in enumerate(heads):
        end = next((j for j, lv in heads[k + 1 :] if lv <= level), n)
        out[i + 1] = end
    return out


def test_simple_pieces_alone_match_commonmark():
    for piece in PIECES:
        if any(cleanup.UNMODELLED.match(x) for x in piece.splitlines()):
            continue
        text = piece + "\n"
        assert scanner_heads(text) == commonmark_heads(text), repr(piece)


def test_every_span_prune_accepts_is_the_commonmark_section():
    """The property prune rests on: a done-log span it would cut is exactly the section a
    CommonMark reader sees, from the heading to the next one of its level or higher."""
    rng = random.Random(20261120)
    accepted = refused = 0
    for _ in range(10000):
        text = "\n".join(rng.choice(PIECES) for _ in range(rng.randint(1, 9))) + "\n"
        if cleanup.ODD_BREAKS.search(text):  # prune refuses the whole text
            refused += 1
            continue
        scan = cleanup.Scan(text)
        real = commonmark_sections(text)
        for a, b, _ in cleanup.done_sections(text, scan):
            if cleanup.span_hazard(scan, a, b):
                refused += 1
                continue
            accepted += 1
            assert real.get(a) == b, (repr(text), a, b, real)
    assert accepted > 500 and refused > 100  # both paths are exercised


def commonmark_titles(text: str) -> list[tuple[int, int, str]]:
    """(0-based line, level, inline text) of each top-level heading."""
    toks = MD.parse(text)
    return [
        (t.map[0], int(t.tag[1]), toks[k + 1].content)
        for k, t in enumerate(toks)
        if t.type == "heading_open" and t.map is not None and t.level == 0
    ]


def test_prune_keeps_every_heading_outside_the_cut():
    """What prune writes reads, to a CommonMark reader, as the same headings minus the cut ones:
    the edge rules never turn a break into an underline, a heading into a paragraph, or merge
    a line into a heading."""
    rng = random.Random(20261121)
    checked = 0
    for _ in range(10000):
        text = "\n".join(rng.choice(PIECES) for _ in range(rng.randint(1, 9))) + "\n"
        if cleanup.ODD_BREAKS.search(text):  # prune refuses the whole text
            continue
        scan = cleanup.Scan(text)
        spans = cleanup.done_sections(text, scan)
        if not spans or any(cleanup.span_hazard(scan, a, b) for a, b, _ in spans):
            continue
        checked += 1
        cut = {i for a, b, _ in spans for i in range(a - 1, b)}
        want = [(lv, t) for i, lv, t in commonmark_titles(text) if i not in cut]
        got = [(lv, t) for _, lv, t in commonmark_titles(cleanup.without(text, spans))]
        assert got == want, (repr(text), spans)
    assert checked > 300
