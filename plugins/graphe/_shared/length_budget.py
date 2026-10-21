#!/usr/bin/env python3
"""Read the length budget a document declares and compare its PDF with it.

A document declares its budget on one comment line of its source, before drafting:

    % budget: 4 pages                LaTeX
    <!-- budget: 1200 words -->      markdown
    % budget: 4 pages, 3000 words    both limits
    % budget: none                   no limit; the length is still reported

Pages count the whole PDF; `% budget: 8 pages before references` counts up to the page
the reference list starts on, for a venue whose limit excludes it. Words count the reading
text: the reference list is dropped (appendices after it are kept), and in markdown so are
code, link targets and comments. A comment whose text after `budget:` starts with neither a
digit nor `none` is an ordinary comment. The latex and pdf gates block a build over budget,
ask for a budget when none is declared, and ask for a look when a declared limit cannot be
measured.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import zlib
from typing import NamedTuple

import prose_check

# A declaration's spec opens with a digit or `none`; any other `budget:` comment is prose.
_SPEC = r"(?P<spec>(?:\d|none\b).*?)"
_TEX_LINE = re.compile(rf"^[ \t]*%+[ \t]*budget[ \t]*:[ \t]*{_SPEC}[ \t]*$", re.I | re.M)
_MD_LINE = re.compile(rf"^[ \t]*<!--[ \t]*budget[ \t]*:[ \t]*{_SPEC}-->[ \t]*$", re.I | re.M)
_MD_INDENTED = re.compile(r"^(?: {4}|\t).*$", re.M)
# Where a budget line is example text, not a declaration.
_TEX_VERBATIM = re.compile(
    r"\\begin\{(verbatim|[BL]?Verbatim|lstlisting|minted|comment|filecontents)\*?\}.*?\\end\{\1\*?\}",
    re.S,
)
_CODE_PART = re.compile(r"(?:[^%\\\n]|\\.)*")
_IFFALSE = re.compile(r"[ \t]*\\iffalse\b")
# Only these open a conditional inside skipped text; `\\newif` names (`\\ifdraft`) do not.
_IF = re.compile(
    r"\\(?:if|ifx|ifnum|ifdim|ifodd|ifcase|ifcat|ifdefined|ifcsname|iftrue|iffalse"
    r"|ifvmode|ifhmode|ifmmode|ifinner|ifvoid|ifhbox|ifvbox|ifeof|iffontchar|ifincsname)"
    r"(?![a-zA-Z@])"
)
_FI = re.compile(r"\\fi(?![a-zA-Z@])")
_COMMENT = re.compile(r"(?<!\\)%.*")
_INPUT = re.compile(r"\\(?:input|include)\s*\{(?P<name>[^{}]+)\}")
_NOTE = re.compile(r"\s*\([^()]*\)\s*$")
_NO_LIMIT = re.compile(r"^none$", re.I)
_ITEM = re.compile(
    r"^(?P<n>\d{1,3}(?:,\d{3})+|\d+)\s+(?P<unit>pages?|words?)(?P<scope>\s+before\s+references)?$",
    re.I,
)
_NUMERIC_LINE = re.compile(r"^[\W\d_]*$")
# A comma between digits is a thousands separator (3,000), not a list break.
_SEPARATOR = re.compile(r"\s*;\s*|,\s+|(?<=\D),|\s+and\s+", re.I)
_WORD = re.compile(r"[^\W_]")
_APPENDIX = re.compile(r"\\appendix\b|\\begin\{appendices\}")
_SECTION = re.compile(r"\\(?:chapter|section)\*?\s*(?:\[[^\]]*\])?\s*\{")
_TEXORPDF = re.compile(r"\\texorpdfstring\s*\{(?:[^{}]|\{[^{}]*\})*\}\s*\{")
_MATH = re.compile(r"\$[^$]*\$")
_MACRO = re.compile(r"\\[a-zA-Z@]+\*?")
_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![s\w])")
_PAGE_COUNT = re.compile(
    rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)(?!\s+\d+\s+R)"
    rb"|/Count\s+(\d+)(?!\s+\d+\s+R)[^>]*?/Type\s*/Pages\b"
)
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_OBJ_STREAM = re.compile(rb"/Type\s*/ObjStm\b")


class Budget(NamedTuple):
    pages: int | None
    words: int | None
    before_refs: bool = False


def read(source: str, markdown: bool = False) -> Budget | None:
    """The budget the source declares, or None. Raises ValueError on one it cannot read.

    LaTeX declares it in a `%` comment, markdown in an HTML comment, both outside code.
    `none` declares no limit: Budget(None, None). A trailing `(note)` is ignored.
    A comment after `budget:` that opens with neither a digit nor `none` is not a declaration.
    """
    if markdown:
        code_free = _MD_INDENTED.sub("", prose_check.MD_FENCE.sub("", source))
        lines = list(_MD_LINE.finditer(code_free))
    else:
        lines = list(_TEX_LINE.finditer(_strip_iffalse(_TEX_VERBATIM.sub("", source))))
    if not lines:
        return None
    if len(lines) > 1:
        raise ValueError(f"{len(lines)} budget lines; declare one")
    spec = _NOTE.sub("", lines[0]["spec"]).strip()
    if _NO_LIMIT.match(spec):
        return Budget(None, None)
    limits: dict[str, int] = {}
    before_refs = False
    for item in _SEPARATOR.split(spec):
        match = _ITEM.match(item.strip())
        if not match:
            raise ValueError(
                f"cannot read {item!r}; write `N pages`, `N pages before references`, "
                "`N words`, a pair, or `none`"
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


def _strip_iffalse(source: str) -> str:
    """Drop `\\iffalse ... \\fi` blocks opened at a line start, nested conditionals included."""
    kept, depth = [], 0
    for line in source.splitlines(keepends=True):
        match = _CODE_PART.match(line)
        code = match[0] if match else ""
        if depth == 0 and not _IFFALSE.match(code):
            kept.append(line)
            continue
        depth += len(_IF.findall(code)) - len(_FI.findall(code))
        depth = max(depth, 0)
    return "".join(kept)


def count_words(text: str, resume: tuple[str, ...] = ()) -> int:
    """Tokens holding a letter or digit, so table bars and bullets do not count.

    Lines of only numbers and punctuation (page numbers, axis ticks, table figures) are skipped.

    `resume` names the appendix titles that end a reference list; see appendix_titles.
    """
    lines = prose_check.body_of(text, resume).splitlines()
    kept = (line for line in lines if not _NUMERIC_LINE.match(line))
    return sum(1 for token in " ".join(kept).split() if _WORD.search(token))


def appendix_titles(tex_source: str) -> tuple[str, ...]:
    """Titles of the sections after `\\appendix`, which the PDF text prints after the references.

    Markup is dropped (`\\emph{main}` reads `main`); math is dropped, so a title that opens
    with math is not found and the appendix behind it goes uncounted.
    """
    source = _COMMENT.sub("", tex_source)
    match = _APPENDIX.search(source)
    if not match:
        return ()
    titles = []
    for section in _SECTION.finditer(source, match.end()):
        title = _braced(source, section.end())
        title = _TEXORPDF.sub("{", title)
        title = " ".join(
            _MACRO.sub(" ", _MATH.sub(" ", title)).replace("{", " ").replace("}", " ").split()
        )
        if title:
            titles.append(title)
    return tuple(titles)


def _braced(source: str, start: int) -> str:
    """The text from `start` up to the brace that closes the one just before it."""
    depth = 1
    for i in range(start, len(source)):
        depth += {"{": 1, "}": -1}.get(source[i], 0)
        if depth == 0:
            return source[start:i]
    return source[start:]


def expand_inputs(tex: pathlib.Path, depth: int = 0, root: pathlib.Path | None = None) -> str:
    """The root .tex with `\\input` and `\\include` files inlined, so an appendix there is seen.

    Commented-out inputs are not followed, and every path resolves against the root's folder,
    as LaTeX does.
    """
    root = tex.parent if root is None else root
    source = _COMMENT.sub("", tex.read_text(encoding="utf-8", errors="replace"))
    if depth >= 8:
        return source

    def inline(match: re.Match[str]) -> str:
        name = match["name"].strip()
        path = root / (name if name.endswith(".tex") else f"{name}.tex")
        return expand_inputs(path, depth + 1, root) if path.is_file() else match[0]

    return _INPUT.sub(inline, source)


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


def pages_before_references(reading: str) -> int | None:
    """Pages up to and including the one the reference list starts on, from `pdftotext` text
    (pages end in a form feed). None when the text holds no reference heading."""
    start = prose_check.references_start(reading)
    return None if start is None else reading.count("\f", 0, start) + 1


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


def _pages(n: int | str) -> str:
    return f"{n} page" if n == 1 else f"{n} pages"


def compare(budget: Budget, pages: int | None, words: int | None) -> Verdict:
    """Each limit the document is over, the measured length (`5 of 4 pages`), and whether
    a declared limit could not be measured. `pages` is the count the budget's scope asks for."""
    over = []
    scope = " before references" if budget.before_refs else ""
    shown = "?" if pages is None else pages
    if budget.pages is None:
        page_part = _pages(shown)
    else:
        page_part = f"{shown} of {_pages(budget.pages)}{scope}"
        if pages is not None and pages > budget.pages:
            over.append(f"{_pages(pages)}{scope}, budget {budget.pages}")
    shown_words = "?" if words is None else str(words)
    if budget.words is None:
        word_part = f"{shown_words} words"
    else:
        word_part = f"{shown_words} of {budget.words} words"
        if words is not None and words > budget.words:
            over.append(f"{words} words, budget {budget.words}")
    measured = f"{page_part}, {word_part}"
    if budget.pages is None and budget.words is None:
        measured += " (no limit declared)"
    unmeasured = (budget.pages is not None and pages is None) or (
        budget.words is not None and words is None
    )
    return Verdict(over, measured, unmeasured)


MISSING = "no length budget declared; set one before drafting ({hint})"
UNMEASURED = "could not measure the PDF against the declared limit ({measured}); check by eye"
OVER = "over budget: {over}. Cut repeated results and retold material, not substance"


def assess(
    source: str,
    pdf: pathlib.Path,
    *,
    hint: str,
    tex: pathlib.Path | None = None,
    reading: str = "",
    body: str | None = None,
) -> list[tuple[str, str]]:
    """The gates' shared verdict as (severity, message) pairs.

    `source` holds the declaration. Markdown (no `tex`) counts the words of `body`, default
    `source`; LaTeX counts those of `reading`, the PDF in reading order, with appendix titles
    read through `tex`'s inputs. BLOCK is over budget or an unreadable line; REVIEW is no
    budget or a declared limit that could not be measured.
    """
    markdown = tex is None
    try:
        budget = read(source, markdown=markdown)
    except ValueError as exc:
        return [("BLOCK", f"unreadable budget line: {exc}")]
    if budget is None:
        return [("REVIEW", MISSING.format(hint=hint))]
    if tex is None:
        words = count_markdown_words(source if body is None else body)
    else:
        titles = appendix_titles(expand_inputs(tex))
        words = count_words(reading, titles) if reading.strip() else None
    if budget.before_refs:
        pages = pages_before_references(reading or _reading_order(pdf))
    else:
        pages = pdf_pages(pdf)
    verdict = compare(budget, pages, words)
    if verdict.over:
        return [("BLOCK", OVER.format(over="; ".join(verdict.over)))]
    if verdict.unmeasured:
        return [("REVIEW", UNMEASURED.format(measured=verdict.measured))]
    return [("INFO", verdict.measured)]


def _reading_order(pdf: pathlib.Path) -> str:
    try:
        return prose_check.pdf_text(pdf)
    except OSError:
        return ""
