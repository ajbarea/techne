#!/usr/bin/env python3
"""Read the length budget a document declares and compare its PDF with it.

A document declares its budget on one comment line of its source, before drafting:

    % budget: 4 pages                LaTeX
    <!-- budget: 1200 words -->      markdown
    % budget: 4 pages, 3000 words    both limits
    % budget: 7 pages, 6 body pages  6 pages before the references, 7 in all
    % budget: none                   no limit; the length is still reported

Pages count the whole PDF. Body pages are those before the references, read from the PDF's
text through pdftotext: the body runs past N pages when the first references heading (a line
of its own: References, Bibliography, Works Cited, Literature Cited) falls after the first line
of page N + 1, the first-line rule of ACL's pubcheck (`check_page_num` in
https://github.com/acl-org/aclpubcheck, read 2026-10), which also ends the body at
Limitations, Acknowledgments or an ethics heading where this gate ends it at the references
alone; appendices placed before the references count as body. The real heading is the
earliest heading-like line or a later one, so the earliest alone may BLOCK, and the gate
passes a body only when the PDF shows one such line or fits whole; several ask for a look
(`references_starts`). A head the gate cannot confirm stays a line and can push a heading off
line 1, a loud error the BLOCK message locates. Folios and running heads and feet are not
lines (`references_start`). A venue that counts only the pages before the references declares
body pages alone.
Words come from the source, not the PDF: LaTeX through `texcount -inc -sum` (text, headers,
`\\title` included, and captions, `\\input` followed, bibliography left out, as Overleaf
counts; text in `\\iffalse` or `comment` blocks of the root and its `\\input`/`\\include`
files is left out too, while files the import or subfiles packages load keep it), markdown
from the body without code, comments, link targets or a References section, and without the
title block.

A `budget:` comment is a declaration when its spec opens with a number, a number word before
`page(s)`/`word(s)`, a `_` placeholder, or `none`/`unlimited`/`no limit` alone; it must
then parse. Any other `budget:` comment is prose. The latex and pdf gates block a build over
budget or with an unreadable line, ask for a budget when none is declared, and ask for a look
when a declared limit cannot be measured.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import zlib
from typing import NamedTuple

import prose_check

_NUMBER_WORDS = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen"
    "|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy"
    "|eighty|ninety|hundred|thousand"
)
_TEX_LINE = re.compile(r"^[ \t]*%+[ \t]*budget[ \t]*:[ \t]*(?P<spec>.*?)[ \t]*$", re.I | re.M)
_MD_LINE = re.compile(r"^[ \t]*<!--[ \t]*budget[ \t]*:[ \t]*(?P<spec>.*?)-->[ \t]*$", re.I | re.M)
# What a declaration opens with; `none` is handled by _NO_LIMIT, which needs it standing alone.
_NUMBER = rf"\d[\d,]*(?:\.\d+)?|(?:{_NUMBER_WORDS})(?:[ -]+(?:{_NUMBER_WORDS}))*"
# A qualifier before the number (`max 4 pages`, `~1200 words`) or `pp` still intends a limit.
# A leading digit always does, whatever follows (`4 sheets`, `1200 wrods`).
_QUALIFIER = r"(?:max(?:imum)?\.?|up\s+to|at\s+most|about|under|[~<≤≈]=?)"
_INTENT = re.compile(
    rf"^(?:(?:{_QUALIFIER}\s*)?(?:\d|(?:{_NUMBER})\s*(?:(?:body\s+)?pages?\b|words?\b|pp\b))|_)",
    re.I,
)
_NO_LIMIT = re.compile(r"^(?:none|unlimited|no\s+limit)[\s.,;:!]*$", re.I)
_MD_INDENTED = re.compile(r"^(?: {4}|\t).*$", re.M)
# Where a budget line is example text, not a declaration.
_TEX_BEGIN = re.compile(
    r"\\begin\{(verbatim|[BL]?Verbatim|lstlisting|minted|comment|filecontents)\*?\}"
)
_CODE_PART = re.compile(r"(?:[^%\\\n]|\\.)*")
_IFFALSE = re.compile(r"[ \t]*\\iffalse\b")
# `\ifthenelse{..}`, `\iftoggle{..}` and any `\if<name>{` are macros with no `\fi`.
_IF = re.compile(
    r"\\if(?:false|true)(?![a-zA-Z@])"
    r"|\\if(?!(?:thenelse|toggle|bool)(?![a-zA-Z@]))[a-zA-Z@]*(?![a-zA-Z@{])"
)
_ELSE = re.compile(r"\\else(?![a-zA-Z@])")
_NEWIF = re.compile(r"\\newif\s*\\[a-zA-Z@]+")
_FI = re.compile(r"\\fi(?![a-zA-Z@])")
_NOTE = re.compile(r"\s*\([^()]*\)[\s.]*$")
_ITEM = re.compile(r"^(?P<n>\d{1,3}(?:,\d{3})+|\d+)\s+(?P<unit>(?:body\s+)?pages?|words?)$", re.I)
# A comma between digits is a thousands separator (3,000), not a list break.
_SEPARATOR = re.compile(r"\s*;\s*|,\s+|(?<=\D),|\s+and\s+", re.I)
_WORD = re.compile(r"[^\W_]")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(?P<title>.*?)[ \t]*#*[ \t]*$", re.M)
_REFERENCES_TITLE = re.compile(
    rf"^(?:\d+(?:\.\d+)*\.?\s+)?(?:{prose_check.REFERENCES_TITLES})$", re.I
)
_SETEXT = re.compile(r"^(?P<title>[^\n#][^\n]*)\n(?P<bar>=+|-+)[ \t]*$", re.M)
_INPUT = re.compile(r"\\(?:input|include)(?![a-zA-Z@])\s*(?:\{([^{}]+)\}|([^\s{}\\%]+))")
_MAX_INPUT_DEPTH = 20
_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![s\w])")
_PAGE_COUNT = re.compile(
    rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)(?!\s+\d+\s+R)"
    rb"|/Count\s+(\d+)(?!\s+\d+\s+R)[^>]*?/Type\s*/Pages\b"
)
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_OBJ_STREAM = re.compile(rb"/Type\s*/ObjStm\b")
_TEXCOUNT_TIMEOUT = 60
# A references heading as pdftotext prints it: alone on its line, perhaps numbered.
# A title that opens with a capital, any case after it, so a wrapped lowercase "references"
# is not a heading.
_REFERENCES_LINE = re.compile(
    rf"^(?:(?:\d+(?:\.\d+)*|[IVXLC]+)\.?\s+)?(?=[A-Z])(?i:{prose_check.REFERENCES_TITLES})$"
)
_CONTENTS_LINE = re.compile(r"^(?:(?=[A-Z])(?i:(?:table\s+of\s+)?c\s?ontents))$")
_LONE_NUMBER = re.compile(r"^\d{1,4}$")
_HAS_LETTER = re.compile(r"[^\W\d_]")
_FOLIO_IN_HEAD = re.compile(r"^\d+(?=\s)|(?<=\s)\d+$")
# Running heads and feet sit among a page's first or last lines.
_EDGE = 2
# A run of this many lines counting up by one marks a review copy's line-number ruler.
_RULER = 20


class Budget(NamedTuple):
    pages: int | None
    words: int | None
    body_pages: int | None = None


def read(source: str, markdown: bool = False) -> Budget | None:
    """The budget the source declares, or None. Raises ValueError on one it cannot read.

    LaTeX declares it in a `%` comment, markdown in an HTML comment, both outside code.
    `none` declares no limit: Budget(None, None). A trailing `(note)` is ignored.
    A `budget:` comment whose spec does not open like a declaration is not one.
    """
    source = source.removeprefix("\ufeff")
    if markdown:
        found = _MD_LINE.finditer(_declaration_source(source))
    else:
        found = _TEX_LINE.finditer(_tex_code(source))
    specs = [spec for m in found if (spec := _spec(m["spec"])) and _declares(spec)]
    if not specs:
        return None
    if len(specs) > 1:
        raise ValueError(f"{len(specs)} budget lines; declare one")
    spec = specs[0]
    if _NO_LIMIT.match(spec):
        return Budget(None, None)
    limits: dict[str, int] = {}
    for item in _SEPARATOR.split(spec):
        match = _ITEM.match(item.strip())
        if not match:
            raise ValueError(
                f"cannot read {item!r}; write `4 pages`, `1200 words`, `6 body pages`, a pair, "
                "or `none`"
            )
        unit = " ".join(match["unit"].lower().split()).rstrip("s")
        n = int(match["n"].replace(",", ""))
        if unit in limits:
            raise ValueError(f"two {unit} limits")
        if n < 1:
            raise ValueError(f"a budget of {n} {unit}s")
        limits[unit] = n
    body = limits.get("body page")
    if body is not None and "page" in limits and body > limits["page"]:
        raise ValueError(f"{body} body pages exceed the {limits['page']}-page limit")
    return Budget(limits.get("page"), limits.get("word"), body)


def _spec(raw: str) -> str:
    """The spec without a trailing `(note)` or full stop."""
    return _NOTE.sub("", raw).strip().rstrip(".").strip()


def _declares(spec: str) -> bool:
    return bool(_INTENT.match(spec) or _NO_LIMIT.match(spec))


def _tex_code(source: str) -> str:
    """The source LaTeX prints: without verbatim-like environments (`comment` included) and
    `\\iffalse ... \\fi` blocks."""
    return _strip_iffalse(_strip_verbatim(source))


def _strip_verbatim(source: str) -> str:
    """Drop verbatim-like environments whose `\\begin` sits in the code part of a line, up to
    the matching `\\end`; a commented-out `%\\begin{comment}` hides nothing."""
    out, pos = [], 0
    for match in _TEX_BEGIN.finditer(source):
        if match.start() < pos:
            continue
        start = source.rfind("\n", 0, match.start()) + 1
        if len(_code_of(source[start : match.start()])) < match.start() - start:
            continue
        env = re.escape(match[1])
        end = re.compile(rf"\\end\{{{env}\*?\}}").search(source, match.end())
        if not end:
            continue
        out.append(source[pos : match.start()])
        pos = end.end()
    out.append(source[pos:])
    return "".join(out)


def _strip_iffalse(source: str) -> str:
    """Drop `\\iffalse ... \\fi` blocks opened at a line start, nested conditionals included;
    the `\\else` branch of such a block is printed and kept.

    Every `\\if<letters>` opens a conditional except the name a `\\newif` defines and the
    macros that take braces."""
    kept: list[str] = []
    frames: list[list[bool]] = []  # per open conditional: [is \iffalse, still hiding]
    token = re.compile(f"{_IF.pattern}|{_FI.pattern}|{_ELSE.pattern}")
    for line in source.splitlines(keepends=True):
        code = _code_of(line)
        if not frames and not _IFFALSE.match(code):
            kept.append(line)
            continue
        code = _NEWIF.sub("", code)
        pos = 0
        for m in token.finditer(code):
            if not any(hiding for _, hiding in frames):
                kept.append(code[pos : m.start()])
            pos = m.end()
            if _FI.match(m[0]):
                if frames:
                    frames.pop()
            elif _ELSE.match(m[0]):
                if frames and frames[-1][0]:
                    frames[-1][1] = False
            else:
                is_false = m[0].startswith("\\iffalse")
                frames.append([is_false, is_false])
        if not any(hiding for _, hiding in frames):
            kept.append(code[pos:] + line[len(_code_of(line)) :])
    return "".join(kept)


def _declaration_source(source: str) -> str:
    """The source without fenced and indented code: where a declaration can sit. Words are
    counted with indented lines kept, since a nested list item is indented."""
    return _MD_INDENTED.sub("", prose_check.MD_FENCE.sub("", source))


class _Heading(NamedTuple):
    level: int
    title: str
    start: int


def _headings(text: str) -> list[_Heading]:
    """ATX (`## Title`) and setext (`Title` over `===` or `---`) headings, in order. A setext
    title is a one-line paragraph directly above the bar."""
    found = [_Heading(len(m[1]), m["title"], m.start()) for m in _HEADING.finditer(text)]
    found += [
        _Heading(1 if m["bar"][0] == "=" else 2, m["title"].strip(), m.start())
        for m in _SETEXT.finditer(text)
        if m.start() == 0 or text[: m.start()].endswith("\n\n")
    ]
    return sorted(found, key=lambda h: h.start)


def _drop_reference_sections(text: str) -> str:
    """Each References/Bibliography/Works Cited heading's section, up to the next heading of
    the same or a higher level."""
    kept, pos, skip_level = [], 0, 0
    for heading in _headings(text):
        level = heading.level
        if skip_level:
            if level > skip_level:
                continue
            skip_level = 0
            pos = heading.start
        if _REFERENCES_TITLE.match(heading.title):
            kept.append(text[pos : heading.start])
            skip_level = level
    kept.append("" if skip_level else text[pos:])
    return "".join(kept)


def markdown_words(source: str) -> int:
    """Words of a markdown body: no code, comments, link targets or reference sections.

    Tokens holding a letter or digit, so table bars and bullets do not count."""
    text = _drop_reference_sections(prose_check.markdown_prose(source))
    return sum(1 for token in text.split() if _WORD.search(token))


def _inline_inputs(code: str, folder: pathlib.Path, depth: int = 0) -> str:
    """`code` with each `\\input`/`\\include` of a file in `folder` replaced by that file's
    printed code, so texcount never sees a hidden block. A missing file stays a macro. One
    pass per line: inlined text is never rescanned by another substitution. Import and
    subfiles macros are left for texcount to follow."""

    def inline(match: re.Match[str]) -> str:
        name = (match[1] or match[2]).strip()
        for path in (folder / f"{name}.tex", folder / name):
            if depth < _MAX_INPUT_DEPTH and path.is_file():
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                return _inline_inputs(_tex_code(text), folder, depth + 1).rstrip("\n") + "\n"
        return match[0]

    lines = []
    for line in code.splitlines(keepends=True):
        head = _code_of(line)
        lines.append(_INPUT.sub(inline, head) + line[len(head) :])
    return "".join(lines)


def tex_words(tex: pathlib.Path) -> tuple[int | None, str]:
    """Words of the root .tex and what it inputs, as texcount counts them (text, headers
    including the title, and captions; bibliography, and `\\iffalse` and `comment` blocks in
    the root and its `\\input`/`\\include` files, left out; files the import or subfiles
    packages load keep theirs), and why it could not be counted."""
    if not shutil.which("texcount"):
        return None, "texcount not found"
    try:
        code = _tex_code(tex.read_text(encoding="utf-8-sig", errors="replace"))
        proc = subprocess.run(
            ["texcount", "-inc", "-sum", "-1", "-"],
            cwd=tex.parent,
            input=_inline_inputs(code, tex.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TEXCOUNT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"texcount failed: {exc}"
    lines = proc.stdout.split()
    if proc.returncode or not lines or not lines[0].isdigit() or "errors" in proc.stdout:
        detail = " ".join(proc.stdout.split()) or "no count printed"
        err = next((ln.strip() for ln in proc.stderr.splitlines() if ln.strip()), "")
        detail += f" ({err[:100]})" if err else ""
        return None, f"texcount could not read the document: {detail}"
    return int(lines[0]), ""


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
        head = data[max(data.rfind(b"obj", 0, stream.start()), 0) : stream.start()]
        if not _OBJ_STREAM.search(head):
            continue
        try:
            chunks.append(zlib.decompress(stream[1]))
        except zlib.error:
            continue
    counts = [int(a or b) for chunk in chunks for a, b in _PAGE_COUNT.findall(chunk)]
    if counts:
        return max(counts) or None
    return sum(len(_PAGE_OBJECT.findall(chunk)) for chunk in chunks) or None


def _counting_runs(lines: list[str]) -> list[int]:
    """The length of each run of consecutive lines that count up by one, as a ruler prints them."""
    runs, length = [], 0
    for i, line in enumerate(lines):
        if _LONE_NUMBER.match(line):
            prev = lines[i - 1] if i else ""
            follows = bool(_LONE_NUMBER.match(prev)) and int(line) == int(prev) + 1
            length = length + 1 if follows else 1
        else:
            length = 0
        runs.append(length)
    return runs


def page_texts(pdf: pathlib.Path, reading: str | None = None) -> list[str] | None:
    """Each page's text in reading order: `reading` when the caller already read it (empty for
    a read that failed), else `prose_check.reading_text`; None when the PDF cannot be read."""
    if reading is None:
        reading = prose_check.reading_text(pdf)
    if not reading or not reading.strip():
        return None
    pages = reading.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def references_starts(pages: list[str]) -> list[tuple[int, int]]:
    """Page and line, both from 1, of every line that reads as a references heading, in order.

    Lines are a page's non-blank lines without its folio, its running heads and feet, and a
    review copy's line-number ruler. A document with a run of `_RULER` lines counting up by
    one carries a ruler, and its lone numbers go from every page first, since a two-column
    ruler interleaves its counts (a numeric table in a review copy goes with them). Heads, feet and
    folios sit among the first or last `_EDGE` lines. A folio is a lone number equal to its
    page's, or offset from it as on two other pages (roman front matter, a set first page). A
    running line is one whose text, a leading or trailing number aside, also stands at the
    edge of another page of its parity, or of every page after the first, in a headed
    document: one whose every page after the first that has text shows such a line. Only the
    outermost line that is no folio at each edge can be a head; a deeper one must be on every
    page after the first, so body that repeats at two page edges stays. A line without letters
    and a heading-like line are never running. A heading on a page whose first lines name it
    Contents is a contents entry. Every other heading-like line is returned, so a caller can
    tell one heading from several (a section-name head, a contents list run on, a column).
    """
    content = [[line.strip() for line in page.splitlines() if line.strip()] for page in pages]
    if any(run >= _RULER for lines in content for run in _counting_runs(lines)):
        content = [[line for line in lines if not _LONE_NUMBER.match(line)] for lines in content]
    count = len(content)

    def edges(lines: list[str]) -> set[int]:
        return {i for i in range(len(lines)) if i < _EDGE or i >= len(lines) - _EDGE}

    def key(line: str) -> str:
        """The line with a folio-like number at its start or end set aside ("6 F. Author")."""
        return _FOLIO_IN_HEAD.sub("#", line)

    at_edge: dict[str, set[int]] = {}
    offsets: dict[int, set[int]] = {}
    for index, lines in enumerate(content):
        for i in edges(lines):
            if _LONE_NUMBER.match(lines[i]):
                offsets.setdefault(int(lines[i]) - index - 1, set()).add(index)
            elif _HAS_LETTER.search(lines[i]) and not _REFERENCES_LINE.match(lines[i]):
                at_edge.setdefault(key(lines[i]), set()).add(index)

    def folio(line: str, index: int) -> bool:
        if not _LONE_NUMBER.match(line):
            return False
        offset = int(line) - index - 1
        return offset == 0 or len(offsets.get(offset, set()) - {index}) >= 2

    after_first = set(range(1, count))

    def everywhere(line: str) -> bool:
        return len(after_first) >= 2 and at_edge.get(key(line), set()) >= after_first

    def recurs(line: str, index: int) -> bool:
        """At the edge of another page of this one's parity, or of every page after the first
        (two or more), by `key`. `at_edge` holds no line without letters and no heading."""
        pages_with = at_edge.get(key(line), set())
        same = pages_with & set(range(index % 2, count, 2)) - {index}
        return bool(same) or everywhere(line)

    # Heads are stripped only from a headed document: one where every page after the first
    # that has text shows a recurring edge line, so one repeated line cannot pass for a head.
    headed = all(
        any(recurs(lines[i], index) for i in edges(lines))
        for index, lines in enumerate(content)
        if index and lines
    )

    def stripped(lines: list[str], index: int) -> set[int]:
        """The folios, and the heads and feet: the outermost line that is no folio at each
        edge when it recurs, a deeper edge line only when it is on every page after the
        first. A deeper line that merely recurs is body that happens to repeat."""
        edge = edges(lines)
        folios = {i for i in edge if folio(lines[i], index)}
        rest = [i for i in range(len(lines)) if i not in folios]
        outer = {rest[0], rest[-1]} if rest else set()
        heads = {
            i
            for i in edge - folios
            if headed and (recurs(lines[i], index) if i in outer else everywhere(lines[i]))
        }
        return folios | heads

    found = []
    for index, lines in enumerate(content):
        if any(_CONTENTS_LINE.match(line) for line in lines[: _EDGE + 1]):
            continue
        drop = stripped(lines, index)
        kept = [line for i, line in enumerate(lines) if i not in drop]
        found += [(index + 1, n) for n, line in enumerate(kept, 1) if _REFERENCES_LINE.match(line)]
    return found


def references_start(pages: list[str]) -> tuple[int, int] | None:
    """The first of `references_starts`, or None."""
    found = references_starts(pages)
    return found[0] if found else None


class BodyReading(NamedTuple):
    body: int | None  # pages before the earliest heading-like line: the body is at least this
    where: str
    headings: int


def body_pages(pdf: pathlib.Path, reading: str | None = None) -> BodyReading:
    """The pages before the earliest references heading, where each heading-like line stands,
    and how many there are; (None, why, 0) when the PDF cannot be read or shows none."""
    pages = page_texts(pdf, reading)
    if pages is None:
        why = (
            "pdftotext could not read the PDF"
            if shutil.which("pdftotext")
            else ("pdftotext is not installed")
        )
        return BodyReading(None, why, 0)
    found = references_starts(pages)
    if not found:
        return BodyReading(None, "no references heading found", 0)
    page, line = found[0]
    if len(found) == 1:
        where = f"references start on page {page}, line {line}"
    else:
        shown = ", ".join(f"page {p} line {n}" for p, n in found[:4])
        where = f"{len(found)} references headings ({shown}{', ...' if len(found) > 4 else ''})"
    return BodyReading(page - 1 if line == 1 else page, where, len(found))


class Verdict(NamedTuple):
    over: list[str]
    measured: str
    unmeasured: bool


def _plural(n: int | str, unit: str) -> str:
    return f"{n} {unit}" if str(n) == "1" else f"{n} {unit}s"


def compare(
    budget: Budget, pages: int | None, words: int | None, body: int | None = None
) -> Verdict:
    """Each limit the document is over, the measured length (`5 of 4 pages`), and whether
    a declared limit could not be measured. `words` and `body` are None when not counted."""
    over = []
    shown = "?" if pages is None else pages
    if budget.pages is None:
        page_part = _plural(shown, "page")
    else:
        page_part = f"{shown} of {_plural(budget.pages, 'page')}"
        if pages is not None and pages > budget.pages:
            over.append(f"{_plural(pages, 'page')}, budget {budget.pages}")
    shown_words = "?" if words is None else str(words)
    if budget.words is None:
        word_part = _plural(shown_words, "word")
    else:
        word_part = f"{shown_words} of {_plural(budget.words, 'word')}"
        if words is not None and words > budget.words:
            over.append(f"{_plural(words, 'word')}, budget {budget.words}")
    measured = page_part if budget.words is None and words is None else f"{page_part}, {word_part}"
    if budget.body_pages is not None:
        shown_body = "?" if body is None else body
        measured += f", body {shown_body} of {_plural(budget.body_pages, 'page')}"
        if body is not None and body > budget.body_pages:
            over.append(f"body {_plural(body, 'page')}, budget {budget.body_pages}")
    if budget.pages is None and budget.words is None and budget.body_pages is None:
        measured += " (no limit declared)"
    unmeasured = (
        (budget.pages is not None and pages is None)
        or (budget.words is not None and words is None)
        or (budget.body_pages is not None and body is None)
    )
    return Verdict(over, measured, unmeasured)


MISSING = "no length budget declared; set one before drafting ({hint})"
UNMEASURED = "could not measure the PDF against the declared limit ({measured}); check by eye"
UNCOUNTED = "word limit cannot be measured: {why} ({measured}); check by eye"
UNREAD_BODY = "body pages cannot be measured: {why} ({measured}); check by eye"
UNSURE_BODY = (
    "body pages are at least the count shown: {why} ({measured}); check which one starts the"
    " references"
)
OVER = "over budget: {over}. Cut repeated results and retold material, not substance"


def assess(
    source: str,
    pdf: pathlib.Path,
    *,
    hint: str,
    source_name: str,
    tex: pathlib.Path | None = None,
    body: str | None = None,
    reading: str | None = None,
) -> list[tuple[str, str, str]]:
    """The gates' shared verdict as (severity, message, anchor) triples.

    `source` holds the declaration. Markdown (no `tex`) counts the words of `body`, default
    `source`; LaTeX counts those of `tex` through texcount, only for a word limit or no limit.
    `reading` is pdftotext's reading-order text of `pdf`, when the caller already has it.
    The anchor is `source_name` for a missing or
    unreadable budget and the PDF's name for a measurement. BLOCK is over budget or an
    unreadable line; REVIEW is no budget or a declared limit that could not be measured.
    """
    try:
        budget = read(source, markdown=tex is None)
    except ValueError as exc:
        return [("BLOCK", f"unreadable budget line: {exc}", source_name)]
    if budget is None:
        return [("REVIEW", MISSING.format(hint=hint), source_name)]
    if tex is None:
        words, why = markdown_words(source if body is None else body), ""
    elif budget.words is None and (budget.pages is not None or budget.body_pages is not None):
        words, why = None, ""
    else:
        words, why = tex_words(tex)
    pages = pdf_pages(pdf)
    body_count: int | None = None
    where, unsure = "", False
    if budget.body_pages is not None:
        body_count, where, headings = body_pages(pdf, reading)
        fits = pages is not None and pages <= budget.body_pages
        if body_count is None and fits:
            body_count, where = pages, f"{where}; the whole PDF fits"
        # The earliest heading gives the least body, so it can show an overrun on its own;
        # only one heading, or a PDF that fits whole, can show the body is inside.
        unsure = headings > 1 and not fits
    verdict = compare(budget, pages, words, body_count)
    if verdict.over:
        over = "; ".join(
            f"{item} ({where})" if item.startswith("body ") else item for item in verdict.over
        )
        return [("BLOCK", OVER.format(over=over), pdf.name)]
    reviews = []
    if unsure:
        reviews.append(UNSURE_BODY.format(why=where, measured=verdict.measured))
    if verdict.unmeasured:
        if budget.words is not None and words is None:
            reviews.append(UNCOUNTED.format(why=why, measured=verdict.measured))
        elif budget.body_pages is not None and body_count is None:
            reviews.append(UNREAD_BODY.format(why=where, measured=verdict.measured))
        else:
            reviews.append(UNMEASURED.format(measured=verdict.measured))
    if reviews:
        return [("REVIEW", message, pdf.name) for message in reviews]
    return [("INFO", verdict.measured, pdf.name)]


def _code_of(line: str) -> str:
    match = _CODE_PART.match(line)
    return match[0] if match else ""
