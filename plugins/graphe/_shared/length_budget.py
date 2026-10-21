#!/usr/bin/env python3
"""Read the length budget a document declares and compare its PDF with it.

A document declares its budget on one comment line of its source, before drafting:

    % budget: 4 pages                LaTeX
    <!-- budget: 1200 words -->      markdown
    % budget: 4 pages, 3000 words    both limits
    % budget: none                   no limit; the length is still reported

Pages count the whole PDF; `% budget: 8 pages before references` counts up to the page the
first bibliography entry, a line starting `[1]`, is on, for a venue whose limit
excludes the list. Words come from the source, not the PDF: LaTeX through
`texcount -inc -sum` (text, headers, `\\title` included, and captions, `\\input` followed,
bibliography left out, as Overleaf counts), markdown from the body
without code, comments, link targets or a References section, and without the title block.

A `budget:` comment is a declaration when its spec opens like one (a number or number word
before `page(s)`/`word(s)`, a `_` placeholder, or `none`/`unlimited`/`no limit` alone); it must
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
_QUALIFIER = r"(?:max(?:imum)?\.?|up\s+to|at\s+most|about|under|[~<≤≈]=?)"
_INTENT = re.compile(
    rf"^(?:(?:{_QUALIFIER}\s*)?(?:{_NUMBER})\s*(?:pages?\b|words?\b|pp\b)|_)", re.I
)
_NO_LIMIT = re.compile(r"^(?:none|unlimited|no\s+limit)[\s.,;:!]*$", re.I)
_MD_INDENTED = re.compile(r"^(?: {4}|\t).*$", re.M)
# Where a budget line is example text, not a declaration.
_TEX_VERBATIM = re.compile(
    r"\\begin\{(verbatim|[BL]?Verbatim|lstlisting|minted|comment|filecontents)\*?\}.*?\\end\{\1\*?\}",
    re.S,
)
_CODE_PART = re.compile(r"(?:[^%\\\n]|\\.)*")
_IFFALSE = re.compile(r"[ \t]*\\iffalse\b")
# `\ifthenelse{..}`, `\iftoggle{..}` and any `\if<name>{` are macros with no `\fi`.
_IF = re.compile(
    r"\\if(?:false|true)(?![a-zA-Z@])"
    r"|\\if(?!(?:thenelse|toggle|bool)(?![a-zA-Z@]))[a-zA-Z@]*(?![a-zA-Z@{])"
)
_NOT_FOLLOWED = re.compile(r"\\(subimport|import|subfile|includefrom|inputfrom)(?![a-zA-Z@])")
_NEWIF = re.compile(r"\\newif\s*\\[a-zA-Z@]+")
_FI = re.compile(r"\\fi(?![a-zA-Z@])")
_NOTE = re.compile(r"\s*\([^()]*\)[\s.]*$")
_ITEM = re.compile(
    r"^(?P<n>\d{1,3}(?:,\d{3})+|\d+)\s+(?P<unit>pages?|words?)(?P<scope>\s+before\s+references)?$",
    re.I,
)
# A comma between digits is a thousands separator (3,000), not a list break.
_SEPARATOR = re.compile(r"\s*;\s*|,\s+|(?<=\D),|\s+and\s+", re.I)
_WORD = re.compile(r"[^\W_]")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(?P<title>.*?)[ \t]*#*[ \t]*$", re.M)
_REFERENCES_TITLE = re.compile(
    rf"^(?:\d+(?:\.\d+)*\.?\s+)?(?:{prose_check.REFERENCES_TITLES})$", re.I
)
# The first bibliography entry; `\f` ends a page in pdftotext text, and `^` does not match after it.
_FIRST_ENTRY = re.compile(r"(?:^|(?<=\f))[ \t]*\[1\]\s", re.M)
_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![s\w])")
_PAGE_COUNT = re.compile(
    rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)(?!\s+\d+\s+R)"
    rb"|/Count\s+(\d+)(?!\s+\d+\s+R)[^>]*?/Type\s*/Pages\b"
)
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_OBJ_STREAM = re.compile(rb"/Type\s*/ObjStm\b")
_TEXCOUNT_TIMEOUT = 60


class Budget(NamedTuple):
    pages: int | None
    words: int | None
    before_refs: bool = False


def read(source: str, markdown: bool = False) -> Budget | None:
    """The budget the source declares, or None. Raises ValueError on one it cannot read.

    LaTeX declares it in a `%` comment, markdown in an HTML comment, both outside code.
    `none` declares no limit: Budget(None, None). A trailing `(note)` is ignored.
    A `budget:` comment whose spec does not open like a declaration is not one.
    """
    if markdown:
        found = _MD_LINE.finditer(_declaration_source(source))
    else:
        found = _TEX_LINE.finditer(_strip_iffalse(_TEX_VERBATIM.sub("", source)))
    specs = [spec for m in found if (spec := _spec(m["spec"])) and _declares(spec)]
    if not specs:
        return None
    if len(specs) > 1:
        raise ValueError(f"{len(specs)} budget lines; declare one")
    spec = specs[0]
    if _NO_LIMIT.match(spec):
        return Budget(None, None)
    limits: dict[str, int] = {}
    before_refs = False
    for item in _SEPARATOR.split(spec):
        match = _ITEM.match(item.strip())
        if not match:
            raise ValueError(
                f"cannot read {item!r}; write `4 pages`, `4 pages before references`, "
                "`1200 words`, a pair, or `none`"
            )
        unit = match["unit"].lower().rstrip("s")
        n = int(match["n"].replace(",", ""))
        if unit in limits:
            raise ValueError(f"two {unit} limits")
        if n < 1:
            raise ValueError(f"a budget of {n} {unit}s")
        if match["scope"]:
            if unit != "page":
                raise ValueError(f"`before references` follows a page limit, not {item.strip()!r}")
            before_refs = True
        limits[unit] = n
    return Budget(limits.get("page"), limits.get("word"), before_refs)


def _spec(raw: str) -> str:
    """The spec without a trailing `(note)` or full stop."""
    return _NOTE.sub("", raw).strip().rstrip(".").strip()


def _declares(spec: str) -> bool:
    return bool(_INTENT.match(spec) or _NO_LIMIT.match(spec))


def _strip_iffalse(source: str) -> str:
    """Drop `\\iffalse ... \\fi` blocks opened at a line start, nested conditionals included.

    Every `\\if<letters>` opens a conditional except the name a `\\newif` defines and the
    macros that take braces."""
    kept, depth = [], 0
    for line in source.splitlines(keepends=True):
        code = _code_of(line)
        if depth == 0 and not _IFFALSE.match(code):
            kept.append(line)
            continue
        depth += len(_IF.findall(_NEWIF.sub("", code))) - len(_FI.findall(code))
        depth = max(depth, 0)
    return "".join(kept)


def _declaration_source(source: str) -> str:
    """The source without fenced and indented code: where a declaration can sit. Words are
    counted with indented lines kept, since a nested list item is indented."""
    return _MD_INDENTED.sub("", prose_check.MD_FENCE.sub("", source))


def _drop_reference_sections(text: str) -> str:
    """Each References/Bibliography/Works Cited heading's section, up to the next heading of
    the same or a higher level."""
    kept, pos, skip_level = [], 0, 0
    for heading in _HEADING.finditer(text):
        level = len(heading[1])
        if skip_level:
            if level > skip_level:
                continue
            skip_level = 0
            pos = heading.start()
        if _REFERENCES_TITLE.match(heading["title"]):
            kept.append(text[pos : heading.start()])
            skip_level = level
    kept.append("" if skip_level else text[pos:])
    return "".join(kept)


def markdown_words(source: str) -> int:
    """Words of a markdown body: no code, comments, link targets or reference sections.

    Tokens holding a letter or digit, so table bars and bullets do not count."""
    text = _drop_reference_sections(prose_check.markdown_prose(source))
    return sum(1 for token in text.split() if _WORD.search(token))


def tex_words(tex: pathlib.Path) -> tuple[int | None, str]:
    """Words of the root .tex and what it inputs, as texcount counts them (text, headers
    including the title, and captions; bibliography left out), and why it could not be counted."""
    if not shutil.which("texcount"):
        return None, "texcount not found"
    try:
        proc = subprocess.run(
            ["texcount", "-inc", "-sum", "-1", tex.name],
            cwd=tex.parent,
            capture_output=True,
            text=True,
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


def pages_before_references(reading: str) -> int | None:
    """Pages up to and including the one the first bibliography entry, a line starting `[1]`,
    is on, from `pdftotext` text (pages end in a form feed). None when no line does, as with
    author-year styles."""
    match = _FIRST_ENTRY.search(reading)
    return None if match is None else reading.count("\f", 0, match.start()) + 1


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


class Verdict(NamedTuple):
    over: list[str]
    measured: str
    unmeasured: bool


def _plural(n: int | str, unit: str) -> str:
    return f"{n} {unit}" if str(n) == "1" else f"{n} {unit}s"


def compare(budget: Budget, pages: int | None, words: int | None) -> Verdict:
    """Each limit the document is over, the measured length (`5 of 4 pages`), and whether
    a declared limit could not be measured. `pages` is the count the budget's scope asks for."""
    over = []
    scope = " before references" if budget.before_refs else ""
    shown = "?" if pages is None else pages
    if budget.pages is None:
        page_part = _plural(shown, "page")
    else:
        page_part = f"{shown} of {_plural(budget.pages, 'page')}{scope}"
        if pages is not None and pages > budget.pages:
            over.append(f"{_plural(pages, 'page')}{scope}, budget {budget.pages}")
    shown_words = "?" if words is None else str(words)
    if budget.words is None:
        word_part = _plural(shown_words, "word")
    else:
        word_part = f"{shown_words} of {_plural(budget.words, 'word')}"
        if words is not None and words > budget.words:
            over.append(f"{_plural(words, 'word')}, budget {budget.words}")
    measured = f"{page_part}, {word_part}"
    if budget.pages is None and budget.words is None:
        measured += " (no limit declared)"
    unmeasured = (budget.pages is not None and pages is None) or (
        budget.words is not None and words is None
    )
    return Verdict(over, measured, unmeasured)


MISSING = "no length budget declared; set one before drafting ({hint})"
UNMEASURED = "could not measure the PDF against the declared limit ({measured}); check by eye"
NO_LIST_START = (
    "cannot find where the reference list starts (a numbered [1] entry) ({measured}); check by eye"
)
NOT_FOLLOWED = "word count may miss files texcount does not follow ({names})"
UNCOUNTED = "word limit cannot be measured: {why} ({measured}); check by eye"
OVER = "over budget: {over}. Cut repeated results and retold material, not substance"


def assess(
    source: str,
    pdf: pathlib.Path,
    *,
    hint: str,
    source_name: str,
    tex: pathlib.Path | None = None,
    reading: str = "",
    body: str | None = None,
) -> list[tuple[str, str, str]]:
    """The gates' shared verdict as (severity, message, anchor) triples.

    `source` holds the declaration. Markdown (no `tex`) counts the words of `body`, default
    `source`; LaTeX counts those of `tex` through texcount. `reading` is the PDF text the
    `before references` page count is read from. The anchor is `source_name` for a missing or
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
    else:
        words, why = tex_words(tex)
    if budget.before_refs:
        pages = pages_before_references(reading or _reading_order(pdf))
    else:
        pages = pdf_pages(pdf)
    verdict = compare(budget, pages, words)
    unfollowed = _unfollowed(source, tex, words, pdf)
    if verdict.over:
        return [("BLOCK", OVER.format(over="; ".join(verdict.over)), pdf.name), *unfollowed]
    if verdict.unmeasured:
        if budget.words is not None and words is None:
            return [("REVIEW", UNCOUNTED.format(why=why, measured=verdict.measured), pdf.name)]
        if budget.before_refs and pages is None:
            return [("REVIEW", NO_LIST_START.format(measured=verdict.measured), pdf.name)]
        return [("REVIEW", UNMEASURED.format(measured=verdict.measured), pdf.name)]
    return [("INFO", verdict.measured, pdf.name), *unfollowed]


def _unfollowed(
    source: str, tex: pathlib.Path | None, words: int | None, pdf: pathlib.Path
) -> list[tuple[str, str, str]]:
    """A REVIEW when the root source loads files through a macro texcount does not follow."""
    if tex is None or words is None:
        return []
    code = _strip_iffalse(_TEX_VERBATIM.sub("", source))
    names = {m[0] for line in code.splitlines() for m in _NOT_FOLLOWED.finditer(_code_of(line))}
    if not names:
        return []
    return [("REVIEW", NOT_FOLLOWED.format(names=", ".join(sorted(names))), pdf.name)]


def _code_of(line: str) -> str:
    match = _CODE_PART.match(line)
    return match[0] if match else ""


def _reading_order(pdf: pathlib.Path) -> str:
    try:
        return prose_check.pdf_text(pdf)
    except OSError:
        return ""
