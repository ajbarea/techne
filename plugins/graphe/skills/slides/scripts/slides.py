#!/usr/bin/env python3
"""Gate a deck before it is presented, and render it through the app that will show it.

    python slides.py check  <deck/index.html|deck.pptx|deck.pdf> [--level AAA|AA] [--min-pt 14]
                            [--jargon a,b] [--backup-from N]
    python slides.py render <deck/index.html|deck.pptx|deck.pdf> <out-dir>
                            [--renderer auto|powerpoint|libreoffice] [--dpi 80]
    python slides.py script <deck/index.html|deck.pptx> [--wpm 140]

A reveal.js web deck (``.html``) is checked and rendered in Chromium through Playwright,
with axe-core for contrast and alt text; it needs ``playwright`` and
``axe-playwright-python`` (pinned in PLAYWRIGHT and AXE below) and, for contact sheets,
Pillow. ``script`` reads its HTML with no browser.

A PDF (a Typst or Beamer deck, say) gets the gates its text can answer: titles, density,
figures, em-dashes and jargon, read page by page with poppler's ``pdftotext``. Contrast, alt
text and speaker notes live in the source, so they are reported as not checked.

A ``.pptx`` or PDF needs no Python dependencies. ``render`` needs poppler's ``pdftoppm``
plus either PowerPoint (native Windows, or Windows from WSL) or LibreOffice; with Pillow
importable it also writes 2x2 contact sheets.

The XML is parsed, never grepped. pptxgenjs writes ``<p:ph>`` with its
attributes on separate lines, so a one-line pattern for ``type="title"`` finds
nothing on a deck where every slide has a title.
"""

from __future__ import annotations

import argparse
import glob
import os
import pathlib
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser

ERROR, BLOCK, WARN, REVIEW, INFO = "ERROR", "BLOCK", "WARN", "REVIEW", "INFO"
RANK = {ERROR: 0, BLOCK: 1, WARN: 2, REVIEW: 3, INFO: 4}

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_R_ID = f"{{{NS['r']}}}id"

# (normal, large) minimum ratios. Large = 18pt+, or 14pt+ bold (WCAG 2.x definition).
LEVELS = {"AAA": (7.0, 4.5), "AA": (4.5, 3.0)}

# Families that render in both PowerPoint and Google Slides without substitution.
PORTABLE_FONTS = {
    "arial",
    "calibri",
    "cambria",
    "consolas",
    "courier new",
    "georgia",
    "times new roman",
    "trebuchet ms",
    "verdana",
}

# A figure, as opposed to a label: percentages, ratios, decimals, "x of y", long numbers.
# A thousands-separated number is one figure, not two; a four-digit year is a label.
_FIGURE = re.compile(
    r"\d+(?:\.\d+)?\s?%|\b\d+\s?/\s?\d+\b|\b\d+\.\d+\b|\b\d+ of \d+\b"
    r"|\b\d{1,3}(?:,\d{3})+\b|(?<![\w,])(?!(?:19|20)\d\d\b)\d{3,}\b"
)
# Only a divider titled exactly like one; a talk about backups is not a divider.
_BACKUP_TITLE = re.compile(r"^\s*(?:backup|appendix)(?:\s+slides?)?\s*$", re.I)
_WORD = re.compile(r"[\w\u2019'-]+")
# A page counter in a PDF footer ("3 / 19"), never part of a slide's text.
_PAGE_COUNTER = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")


def jargon_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    """The listed terms that appear in the text as whole words, case-insensitively."""
    return [
        term for term in terms if re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text, re.I)
    ]


class Finding:
    __slots__ = ("gate", "message", "severity", "slide")

    def __init__(self, severity: str, gate: str, message: str, slide: int | None = None) -> None:
        self.severity = severity
        self.gate = gate
        self.message = message
        self.slide = slide

    def __str__(self) -> str:
        where = f"slide {self.slide:>2}  " if self.slide else ""
        return f"{self.severity:<6} {self.gate:<15} {where}{self.message}"


# ------------------------------------------------------------------ colour --


def luminance(hex6: str) -> float:
    out = []
    for i in (0, 2, 4):
        c = int(hex6[i : i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def is_large(size_pt: float | None, bold: bool) -> bool:
    if size_pt is None:
        return False
    return size_pt >= 18 or (bold and size_pt >= 14)


# ---------------------------------------------------------------- package --


class Package:
    """Read-only view of the parts a check needs. Slide order comes from sldIdLst."""

    def __init__(self, path: pathlib.Path) -> None:
        self.zip = zipfile.ZipFile(path)
        self.names = set(self.zip.namelist())
        self._xml: dict[str, ET.Element] = {}
        self._rels: dict[str, dict[str, tuple[str, str]]] = {}

    def xml(self, part: str) -> ET.Element:
        if part not in self._xml:
            self._xml[part] = ET.fromstring(self.zip.read(part))
        return self._xml[part]

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        """Relationship id -> (type suffix, absolute part name)."""
        if part in self._rels:
            return self._rels[part]
        folder, name = posixpath.split(part)
        rels_part = posixpath.join(folder, "_rels", name + ".rels")
        out: dict[str, tuple[str, str]] = {}
        if rels_part in self.names:
            for rel in self.xml(rels_part).findall("pr:Relationship", NS):
                if rel.get("TargetMode") == "External":
                    continue
                absolute = posixpath.normpath(posixpath.join(folder, rel.get("Target", "")))
                out[rel.get("Id", "")] = (rel.get("Type", "").rsplit("/", 1)[-1], absolute)
        self._rels[part] = out
        return out

    def related(self, part: str, kind: str) -> str | None:
        for rel_type, target in self.rels(part).values():
            if rel_type == kind:
                return target
        return None

    def slides(self) -> list[str]:
        pres = "ppt/presentation.xml"
        rels = self.rels(pres)
        order = self.xml(pres).findall("p:sldIdLst/p:sldId", NS)
        return [rels[s.get(_R_ID, "")][1] for s in order if s.get(_R_ID, "") in rels]

    def theme_fonts(self, slide: str) -> dict[str, str]:
        """`+mj-lt` / `+mn-lt` references resolved through the slide's master theme."""
        layout = self.related(slide, "slideLayout")
        master = self.related(layout, "slideMaster") if layout else None
        theme = self.related(master, "theme") if master else None
        if not theme or theme not in self.names:
            return {}
        scheme = self.xml(theme).find("a:themeElements/a:fontScheme", NS)
        out = {}
        for ref, role in (("+mj-lt", "majorFont"), ("+mn-lt", "minorFont")):
            latin = scheme.find(f"a:{role}/a:latin", NS) if scheme is not None else None
            if latin is not None and latin.get("typeface"):
                out[ref] = latin.get("typeface", "")
        return out


# A surface whose colour is not one opaque sRGB value: a picture, gradient,
# pattern, theme-styled or translucent fill. Text over it is not measured.
UNKNOWN = "?"
_PAINTS = ("a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill")


def solid_fill(parent: ET.Element | None) -> str | None:
    """Opaque sRGB solid fill of a run or cell property block, else None."""
    if parent is None:
        return None
    clr = parent.find("a:solidFill/a:srgbClr", NS)
    if clr is None or clr.find("a:alpha", NS) is not None:
        return None
    return clr.get("val", "").upper()


def fill_of(sppr: ET.Element | None, style: ET.Element | None = None) -> str | None:
    """Opaque sRGB fill, UNKNOWN for any other paint, None for no fill."""
    if sppr is not None:
        if sppr.find("a:noFill", NS) is not None:
            return None
        solid = sppr.find("a:solidFill", NS)
        if solid is not None:
            return solid_fill(sppr) or UNKNOWN
        if any(sppr.find(paint, NS) is not None for paint in _PAINTS):
            return UNKNOWN
    ref = style.find("a:fillRef", NS) if style is not None else None
    if ref is not None and ref.get("idx", "0") != "0":
        return UNKNOWN
    return None


def background(pkg: Package, slide: str) -> str | None:
    """The first level (slide, layout, master) that defines a background decides it.

    A theme-referenced (bgRef), picture or gradient background is not a colour
    this check can measure against, so it yields None rather than falling
    through to a solid colour further up that is not what the audience sees.
    """
    part: str | None = slide
    for next_kind in ("slideLayout", "slideMaster", None):
        if part is None:
            return None
        bg = pkg.xml(part).find("p:cSld/p:bg", NS)
        if bg is not None:
            fill = fill_of(bg.find("p:bgPr", NS))
            return fill if fill not in (None, UNKNOWN) else None
        part = pkg.related(part, next_kind) if next_kind else None
    return None


def title_size(pkg: Package, slide: str) -> float:
    """Title point size from the master's title style; titles inherit it when unset.

    Every stock title style is 32pt or larger, so without one a title is large text.
    """
    layout = pkg.related(slide, "slideLayout")
    master = pkg.related(layout, "slideMaster") if layout else None
    if master:
        rpr = pkg.xml(master).find("p:txStyles/p:titleStyle/a:lvl1pPr/a:defRPr", NS)
        if rpr is not None and rpr.get("sz"):
            return int(rpr.get("sz", "0")) / 100
    return 18.0


class Run:
    __slots__ = ("bold", "color", "effective", "field", "font", "size", "text")

    def __init__(self, el: ET.Element, field: bool) -> None:
        rpr = el.find("a:rPr", NS)
        self.text = "".join(t.text or "" for t in el.findall("a:t", NS))
        self.field = field
        sz = rpr.get("sz") if rpr is not None else None
        self.size = int(sz) / 100 if sz else None
        self.effective = self.size  # size for the contrast threshold, after inheritance
        self.bold = rpr is not None and rpr.get("b") in ("1", "true")
        self.color = solid_fill(rpr)
        latin = rpr.find("a:latin", NS) if rpr is not None else None
        self.font = latin.get("typeface") if latin is not None else None


def _local(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def runs(body: ET.Element | None) -> list[Run]:
    if body is None:
        return []
    out = [Run(r, False) for r in body.iter(f"{{{NS['a']}}}r")]
    out += [Run(f, True) for f in body.iter(f"{{{NS['a']}}}fld")]
    return out


def text_of(body: ET.Element | None, fields: bool = True) -> str:
    """Visible text, one line per paragraph, with line breaks as spaces."""
    if body is None:
        return ""
    lines = []
    for para in body.findall("a:p", NS):
        bits = []
        for child in para:
            tag = _local(child)
            if tag == "r" or (tag == "fld" and fields):
                bits.append("".join(t.text or "" for t in child.findall("a:t", NS)))
            elif tag == "br":
                bits.append(" ")
        lines.append("".join(bits))
    return "\n".join(lines).strip()


def box(el: ET.Element) -> tuple[int, int, int, int] | None:
    xfrm = el.find("p:spPr/a:xfrm", NS)
    if xfrm is None:
        xfrm = el.find("p:xfrm", NS)
    if xfrm is None:
        return None
    off, ext = xfrm.find("a:off", NS), xfrm.find("a:ext", NS)
    if off is None or ext is None:
        return None
    return int(off.get("x", 0)), int(off.get("y", 0)), int(ext.get("cx", 0)), int(ext.get("cy", 0))


def contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    cx, cy = inner[0] + inner[2] / 2, inner[1] + inner[3] / 2
    return outer[0] <= cx <= outer[0] + outer[2] and outer[1] <= cy <= outer[1] + outer[3]


Surface = tuple[tuple[int, int, int, int], str]


class Slide:
    """Everything the gates read from one slide, in z-order."""

    def __init__(self, pkg: Package, part: str, number: int) -> None:
        self.number = number
        self.bg = background(pkg, part)
        self.title_pt = title_size(pkg, part)
        self.fonts = pkg.theme_fonts(part)
        self.title = ""
        self.has_title = False
        self.body_text: list[str] = []
        self.text_runs: list[tuple[Run, str | None]] = []  # (run, colour behind it)
        self.pictures: list[bool] = []  # has alt text or is marked decorative
        tree = pkg.xml(part).find("p:cSld/p:spTree", NS)
        if tree is not None:
            self._walk(tree, [], in_group=False)
        notes = pkg.related(part, "notesSlide")
        self.notes = _notes_text(pkg, notes) if notes else ""

    def _walk(self, container: ET.Element, filled: list[Surface], in_group: bool) -> None:
        for el in container:
            tag = _local(el)
            if tag == "sp":
                self._shape(el, filled, in_group)
            elif tag == "pic":
                pr = el.find("p:nvPicPr/p:cNvPr", NS)
                descr = (pr.get("descr") or "").strip() if pr is not None else ""
                decorative = b'decorative val="1"' in ET.tostring(el)
                self.pictures.append(bool(descr) or decorative)
                rect = box(el)
                if rect is not None and not in_group:
                    filled.append((rect, UNKNOWN))
            elif tag == "graphicFrame":
                self._table(el, filled, in_group)
            elif tag == "grpSp":
                # Child offsets are in the group's own coordinate space.
                self._walk(el, filled, in_group=True)
            elif tag == "AlternateContent" and len(el):
                self._walk(el[0], filled, in_group)

    def _behind(self, el: ET.Element, filled: list[Surface], in_group: bool) -> str | None:
        if in_group:
            return UNKNOWN
        rect = box(el)
        if rect is not None:
            for outer, fill in reversed(filled):
                if contains(outer, rect):
                    return fill
        return self.bg

    def _shape(self, el: ET.Element, filled: list[Surface], in_group: bool) -> None:
        ph = el.find("p:nvSpPr/p:nvPr/p:ph", NS)
        ph_type = ph.get("type", "body") if ph is not None else None
        body = el.find("p:txBody", NS)
        found = runs(body)
        own = fill_of(el.find("p:spPr", NS), el.find("p:style", NS))
        behind = own if own is not None else self._behind(el, filled, in_group)
        if ph_type in ("title", "ctrTitle"):
            text = text_of(body)
            self.has_title = self.has_title or bool(text)
            self.title = self.title or " ".join(text.split())
            for r in found:
                r.effective = r.size if r.size is not None else self.title_pt
        elif ph_type != "sldNum":
            text = text_of(body, fields=False)
            if text:
                self.body_text.append(text)
        self.text_runs += [(r, behind) for r in found if r.text.strip()]
        rect = box(el)
        if own is not None and rect is not None and not in_group:
            filled.append((rect, own))

    def _table(self, el: ET.Element, filled: list[Surface], in_group: bool) -> None:
        frame_bg = self._behind(el, filled, in_group)
        for cell in el.iter(f"{{{NS['a']}}}tc"):
            own = fill_of(cell.find("a:tcPr", NS))
            fill = own if own is not None else frame_bg
            body = cell.find("a:txBody", NS)
            text = text_of(body)
            if text:
                self.body_text.append(text)
            self.text_runs += [(r, fill) for r in runs(body) if r.text.strip()]


def is_backup_divider(title: str) -> bool:
    """True for the slide that ends the talk; it and every slide after it are backup."""
    return bool(_BACKUP_TITLE.match(title))


def _notes_text(pkg: Package, part: str) -> str:
    out = []
    for sp in pkg.xml(part).iter(f"{{{NS['p']}}}sp"):
        ph = sp.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if ph is not None and ph.get("type") == "body":
            out.append(text_of(sp.find("p:txBody", NS), fields=False))
    return "\n".join(t for t in out if t).strip()


# ------------------------------------------------------------------ gates --


def check(
    path: pathlib.Path,
    level: str = "AAA",
    min_pt: float = 14,
    dense_words: int = 60,
    title_words: int = 14,
    jargon: tuple[str, ...] = (),
    backup_from: int | None = None,
) -> list[Finding]:
    if path.suffix.lower() == ".pdf":
        return check_pdf(path, dense_words, title_words, jargon, backup_from)
    if path.suffix.lower() in HTML:
        return check_html(path, level, min_pt, dense_words, title_words, jargon, backup_from)
    try:
        pkg = Package(path)
        parts = pkg.slides()
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        return [Finding(ERROR, "unreadable", f"{path}: {exc}")]
    if not parts:
        return [Finding(ERROR, "unreadable", f"{path}: no slides in sldIdLst")]

    normal, large = LEVELS[level]
    found: list[Finding] = []
    titles: dict[str, list[int]] = {}
    fonts: dict[str, set[int]] = {}
    no_notes: list[int] = []
    unchecked = 0
    in_backup = False

    for number, part in enumerate(parts, 1):
        try:
            s = Slide(pkg, part, number)
        except (KeyError, ET.ParseError) as exc:
            found.append(Finding(ERROR, "unreadable", f"{part}: {exc}", number))
            continue
        if not s.has_title:
            found.append(
                Finding(
                    BLOCK,
                    "no-title",
                    "no title placeholder with text; screen readers see an untitled slide",
                    number,
                )
            )
        else:
            titles.setdefault(s.title.casefold(), []).append(number)
        in_backup = (
            in_backup
            or is_backup_divider(s.title)
            or (backup_from is not None and number >= backup_from)
        )

        pairs: dict[tuple[str, str, bool], str] = {}
        for run, behind in s.text_runs:
            font = s.fonts.get(run.font, run.font) if run.font else None
            if font and not font.startswith("+"):
                fonts.setdefault(font, set()).add(number)
            if not run.field and run.size is not None and run.size < min_pt:
                found.append(
                    Finding(
                        WARN,
                        "small-text",
                        f"{run.size:g}pt < {min_pt:g}pt: {run.text.strip()[:40]!r}",
                        number,
                    )
                )
            if run.color is None or behind in (None, UNKNOWN):
                unchecked += 1
                continue
            big = is_large(run.effective, run.bold)
            if contrast(run.color, behind) < (large if big else normal):
                pairs.setdefault((run.color, behind, big), run.text.strip()[:40])
        for (fg, bg, big), sample in pairs.items():
            need = large if big else normal
            kind = "large" if big else "normal"
            found.append(
                Finding(
                    BLOCK,
                    "contrast",
                    f"#{fg} on #{bg} = {contrast(fg, bg):.2f}:1, {kind} text needs {need}:1 "
                    f"({level}): {sample!r}",
                    number,
                )
            )

        missing = s.pictures.count(False)
        if missing:
            found.append(
                Finding(
                    BLOCK,
                    "alt-text",
                    f"{missing} picture(s) with no alt text and not marked decorative",
                    number,
                )
            )

        visible = " ".join([s.title, *s.body_text])
        if not s.notes and not in_backup:
            no_notes.append(number)
        found += text_gates(
            number,
            s.title,
            visible,
            visible,
            sum(len(_WORD.findall(t)) for t in s.body_text),
            in_backup,
            dense_words,
            title_words,
            jargon,
            "{words} words of body text (> {limit}); move the rest to the script",
        )

    found += duplicate_titles(titles)
    odd = {f: sorted(n) for f, n in fonts.items() if f.casefold() not in PORTABLE_FONTS}
    for font, numbers in odd.items():
        found.append(
            Finding(
                WARN,
                "font",
                f"{font!r} may be substituted in PowerPoint or Google Slides "
                f"(slides {numbers[:8]})",
            )
        )
    if no_notes:
        found.append(
            Finding(WARN, "no-notes", f"no script in the speaker notes on slides {no_notes}")
        )
    if unchecked:
        found.append(
            Finding(
                INFO,
                "contrast",
                f"{unchecked} text run(s) inherit their colour or sit on a picture, "
                "gradient, theme or grouped surface; not checked",
            )
        )
    found.append(
        Finding(
            INFO,
            "render",
            "overflow and overlap are invisible to this check; render and look at every slide",
        )
    )
    return sorted(found, key=lambda f: (RANK[f.severity], f.slide or 0))


def text_gates(
    number: int,
    title: str,
    visible: str,
    figure_text: str,
    words: int,
    in_backup: bool,
    dense_words: int,
    title_words: int,
    jargon: tuple[str, ...],
    dense: str,
) -> list[Finding]:
    """The gates a slide's text alone can answer, shared by every deck format."""
    found: list[Finding] = []
    if "\u2014" in visible:
        found.append(Finding(BLOCK, "em-dash", "em-dash in slide text", number))
    if len(title.split()) > title_words:
        found.append(
            Finding(
                REVIEW, "long-title", f"{len(title.split())}-word title (> {title_words})", number
            )
        )
    if not in_backup:
        found += _jargon(visible, jargon, number)
    # The title slide carries dates, venues and author lists by design, and
    # backup slides hold the tables the talk left out.
    if in_backup or number == 1:
        return found
    figures = sorted({m.group(0) for m in _FIGURE.finditer(figure_text)})
    if figures:
        found.append(
            Finding(
                REVIEW,
                "figures",
                f"figures on a talk slide: {', '.join(figures[:6])}; "
                "keep only the ones this audience needs",
                number,
            )
        )
    if words > dense_words:
        found.append(Finding(REVIEW, "dense", dense.format(words=words, limit=dense_words), number))
    return found


def duplicate_titles(titles: dict[str, list[int]]) -> list[Finding]:
    return [
        Finding(WARN, "duplicate-title", f"slides {numbers} share the title {title!r}")
        for title, numbers in titles.items()
        if len(numbers) > 1
    ]


def _jargon(text: str, terms: tuple[str, ...], number: int) -> list[Finding]:
    hits = jargon_hits(text, terms)
    if not hits:
        return []
    return [
        Finding(
            REVIEW,
            "jargon",
            f"{', '.join(hits)} on a talk slide; use the plain word, the term in a muted footnote",
            number,
        )
    ]


def pdf_pages(path: pathlib.Path) -> list[str]:
    """Each page's text, in reading order, through poppler's pdftotext."""
    if not shutil.which("pdftotext"):
        raise OSError("pdftotext not found (poppler-utils)")
    out = subprocess.run(
        ["pdftotext", str(path), "-"], capture_output=True, text=True, check=True
    ).stdout
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def check_pdf(
    path: pathlib.Path,
    dense_words: int = 60,
    title_words: int = 14,
    jargon: tuple[str, ...] = (),
    backup_from: int | None = None,
) -> list[Finding]:
    """The gates a PDF's text can answer: a page's first line stands for its title."""
    try:
        pages = pdf_pages(path)
    except (OSError, subprocess.CalledProcessError) as exc:
        return [Finding(ERROR, "unreadable", f"{path}: {exc}")]
    if not pages:
        return [Finding(ERROR, "unreadable", f"{path}: no pages")]
    found: list[Finding] = []
    titles: dict[str, list[int]] = {}
    in_backup = False
    for number, page in enumerate(pages, 1):
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        lines = [ln for ln in lines if not _PAGE_COUNTER.match(ln)]
        title = lines[0] if lines else ""
        body = lines[1:]
        if title:
            titles.setdefault(title.casefold(), []).append(number)
        in_backup = (
            in_backup
            or is_backup_divider(title)
            or (backup_from is not None and number >= backup_from)
        )
        visible = " ".join(lines)
        found += text_gates(
            number,
            title,
            visible,
            " ".join(body),
            sum(len(_WORD.findall(t)) for t in body),
            in_backup,
            dense_words,
            title_words,
            jargon,
            "{words} words on the page (> {limit}), figure labels included; "
            "if they are prose, move it to the script or a figure",
        )
    found += duplicate_titles(titles)
    found.append(
        Finding(
            INFO,
            "pdf",
            "contrast, alt text, fonts and speaker notes live in the source; not checked from a "
            "PDF. A page's first line is read as its title",
        )
    )
    found.append(
        Finding(
            INFO,
            "render",
            "overflow and overlap are invisible to this check; render and look at every slide",
        )
    )
    return sorted(found, key=lambda f: (RANK[f.severity], f.slide or 0))


def verdict(found: list[Finding]) -> tuple[int, str]:
    errors = sum(f.severity == ERROR for f in found)
    blocks = sum(f.severity == BLOCK for f in found)
    if errors:
        return 1, f"UNREADABLE: {errors} error(s)."
    if blocks:
        return 2, f"NOT READY: {blocks} blocker(s)."
    reviews = sum(f.severity == REVIEW for f in found)
    return 0, f"READY to render: 0 blockers, {reviews} item(s) to review."


def script(path: pathlib.Path, wpm: int = 140) -> tuple[int, str]:
    """The speaker notes as a read-aloud script in Markdown, with a talk-time estimate."""
    if wpm <= 0:
        return 1, f"--wpm must be positive, not {wpm}"
    pairs: list[tuple[str, str]] = []
    try:
        if path.suffix.lower() in HTML:
            pairs = html_slides(path)
        else:
            pkg = Package(path)
            parts = pkg.slides()
            if not parts:
                return 1, f"{path}: no slides in sldIdLst"
            for number, part in enumerate(parts, 1):
                try:
                    s = Slide(pkg, part, number)
                except (KeyError, ET.ParseError) as exc:
                    return 1, f"{part}: {exc}"
                pairs.append((s.title, s.notes))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError, UnicodeDecodeError) as exc:
        return 1, f"{path}: {exc}"
    if not pairs:
        return 1, f"{path}: no slides"
    talk: list[str] = []
    backup: list[str] = []
    words = 0
    in_backup = False
    for number, (title, notes) in enumerate(pairs, 1):
        in_backup = in_backup or is_backup_divider(title)
        heading = f"## {number}. {title or '(untitled)'}"
        body = notes or "_No script on this slide._"
        (backup if in_backup else talk).append(f"{heading}\n\n{body}\n")
        if not in_backup:
            words += len(_WORD.findall(notes))
    minutes = words / wpm
    head = [
        f"# Script: {path.name}\n",
        f"{words} words on the talk slides, about {minutes:.1f} minutes at {wpm} words a minute.\n",
    ]
    tail = ["# Backup slides\n", *backup] if backup else []
    return 0, "\n".join(head + talk + tail)


# ------------------------------------------------------------------- html --

# A web deck is reveal.js HTML, checked and rendered in Chromium through Playwright,
# with axe-core for contrast and alt text. Pinned here so the commands in SKILL.md and
# the error messages agree.
PLAYWRIGHT = "playwright==1.63.0"
AXE = "axe-playwright-python==0.1.8"
WITH_BROWSER = f"uv run --no-project --quiet --with {PLAYWRIGHT} --with {AXE} --with pillow"
CANVAS = {"width": 1280, "height": 720}
SCREEN = {"width": 1920, "height": 1080}
PHONE = {"width": 390, "height": 844}
# Below this many CSS pixels on a phone, body text is unreadable at arm's length.
PHONE_MIN_PX = 12
AXE_ALT = ["image-alt", "svg-img-alt", "role-img-alt", "input-image-alt", "object-alt"]
# axe's 7:1 rule reports only text that passes 4.5:1, so AAA runs both.
AXE_CONTRAST = {"AAA": ["color-contrast", "color-contrast-enhanced"], "AA": ["color-contrast"]}
# What AAA asks of text that axe's 4.5:1 rule failed, by the ratio that rule expected.
_AAA_NEED = {"3:1": "4.5:1", "4.5:1": "7:1"}

HTML = (".html", ".htm")

# The slides, as reveal.js orders them: sections where reveal.js puts slides (in .slides, in a
# stack, or in a scroll-view page), not a section used as content inside a slide, and not
# the wrapper of a vertical stack, which scroll view lists with a NaN horizontal index.
_SLIDES = (
    "window.__deckSlides = () => Reveal.getSlides().filter((s) => "
    "s.parentElement.matches('.slides, .slides > section, .scroll-page-content') "
    "&& !s.querySelector(':scope > section') && Number.isInteger(Reveal.getIndices(s).h))"
)
_COUNT = "__deckSlides().length"

_STILL = "*, *::before, *::after { transition: none !important; animation: none !important; }"
# Scroll view shows fragments by scroll position and hides them again on the next scroll,
# so the phone pass shows every one outright.
_ALL_FRAGMENTS = (
    _STILL + " .reveal .fragment { opacity: 1 !important; visibility: inherit !important; }"
)
_SCROLL_TO = """(i) => {
  const s = __deckSlides()[i];
  (s.closest('.scroll-page') || s).scrollIntoView({block: 'start', behavior: 'instant'});
}"""

# Show slide i with every fragment, then read it. The frame is the slide canvas
# (config size times scale), not the section, whose box follows its content in a stock
# deck. A spill is an element drawn past the frame, clipped or not; only content inside a
# container that scrolls sideways is exempt, and those containers are counted as pans.
_READ_SLIDE = """(i) => {
  const s = __deckSlides()[i];
  const at = Reveal.getIndices(s);
  Reveal.slide(at.h, at.v);
  while (Reveal.nextFragment()) {}
  // Scroll view reveals fragments by scroll position, not by nextFragment.
  for (const f of s.querySelectorAll('.fragment')) f.classList.add('visible');
  const inNotes = (el) => el.closest('aside.notes');
  const heading = [...s.querySelectorAll('h1, h2, h3')].find((h) => !inNotes(h));
  const scratch = document.createElement('div');
  scratch.innerHTML = Reveal.getSlideNotes(s) || '';
  const config = Reveal.getConfig(), scale = Reveal.getScale();
  const w = config.width * scale, h = config.height * scale;
  let left, top;
  if (Reveal.isScrollView()) {
    const page = (s.closest('.scroll-page-content') || s).getBoundingClientRect();
    left = page.left + (page.width - w) / 2;
    top = page.top + (page.height - h) / 2;
  } else {
    const slides = document.querySelector('.reveal .slides').getBoundingClientRect();
    left = slides.left;
    top = slides.top;
  }
  const pans = (el) => {
    for (let a = el.parentElement; a && a !== s; a = a.parentElement) {
      if (['auto', 'scroll'].includes(getComputedStyle(a).overflowX)) return true;
    }
    return false;
  };
  // Screen-reader-only text: the element or an ancestor is clipped away, or a box of 1px or
  // less that hides its overflow.
  const hidden = (el) => {
    for (let a = el; a && a !== s; a = a.parentElement) {
      const st = getComputedStyle(a), r = a.getBoundingClientRect();
      if ((st.clip && st.clip !== 'auto') || st.clipPath !== 'none') return true;
      if (r.width <= 1 && r.height <= 1 && st.overflow !== 'visible') return true;
    }
    return false;
  };
  const out = [];
  for (const el of s.querySelectorAll('*')) {
    if (inNotes(el) || pans(el) || hidden(el)) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const st = getComputedStyle(el);
    if (st.visibility !== 'visible' || st.display === 'none' || st.opacity === '0') continue;
    if (r.right > left + w + 2 || r.bottom > top + h + 2 || r.left < left - 2
        || r.top < top - 2) out.push(el);
  }
  const spill = out.filter((el) => !out.some((o) => o !== el && el.contains(o)))
    .map((el) => (el.textContent || el.tagName).trim().replace(/\\s+/g, ' ').slice(0, 40));
  const panned = [...s.querySelectorAll('*')].filter((el) =>
    ['auto', 'scroll'].includes(getComputedStyle(el).overflowX)
    && el.scrollWidth > el.clientWidth + 1).length;
  return {
    title: heading ? heading.innerText.trim() : '',
    text: s.innerText,
    notes: scratch.textContent.trim(),
    spill,
    panned,
  };
}"""

# reveal.js paints slide backgrounds on a layer beside the slides, which axe reads as an
# element overlapping the text and gives up on. For the run the layer is hidden and its
# colour is painted on .slides, under the section. Over an image, a
# gradient or a video (on the layer or the section) the contrast rules are skipped and the
# slide's text is counted as unchecked.
_AXE_SLIDE = """async ([i, rules]) => {
  const s = __deckSlides()[i];
  const layer = document.querySelector('.reveal .backgrounds');
  const painted = Reveal.getSlideBackground(s);
  const paint = painted ? getComputedStyle(painted) : null;
  const own = getComputedStyle(s);
  // reveal.js puts an image or gradient on a child of the background element, and a video
  // or iframe inside it, so the whole subtree is searched.
  const media = ['VIDEO', 'IFRAME', 'IMG'];
  const picture = own.backgroundImage !== 'none' || (!!painted
    && [painted, ...painted.querySelectorAll('*')].some((el) =>
      getComputedStyle(el).backgroundImage !== 'none' || media.includes(el.tagName)));
  const run = picture ? rules.filter((r) => !r.startsWith('color-contrast')) : rules;
  const clear = (c) => !c || c === 'transparent' || /rgba\\(.*,\\s*0\\)$/.test(c);
  // The layer's colour goes on .slides, under the section, so a section with its own
  // background (opaque or see-through) is blended over the colour that is really behind it.
  const under = document.querySelector('.reveal .slides');
  const before = under.style.backgroundColor;
  if (paint && !picture && !clear(paint.backgroundColor)) {
    under.style.backgroundColor = paint.backgroundColor;
  }
  if (layer && !picture) layer.style.display = 'none';
  try {
    const r = await axe.run(s, {runOnly: {type: 'rule', values: run},
                                 resultTypes: ['violations', 'incomplete']});
    const nodes = (list) => list.flatMap((v) => v.nodes.map((n) => ({
      rule: v.id,
      target: String(n.target[0] || ''),
      data: (n.any[0] || n.all[0] || n.none[0] || {}).data || null,
    })));
    const text = picture ? [...s.querySelectorAll('*')].filter((el) => !el.closest('aside')
      && [...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())).length : 0;
    return {violations: nodes(r.violations),
            unchecked: text + nodes(r.incomplete)
              .filter((n) => n.rule.startsWith('color-contrast')).length};
  } finally {
    under.style.backgroundColor = before;
    if (layer) layer.style.display = '';
  }
}"""

# Animations on slide i still running a quarter second after it opens, with reduced motion
# requested. A loop driven by requestAnimationFrame or a timer is invisible to this.
_MOVING = """async (i) => {
  const s = __deckSlides()[i];
  const at = Reveal.getIndices(s);
  Reveal.slide(at.h, at.v);
  Reveal.nextFragment();
  await new Promise((r) => setTimeout(r, 250));
  return s.getAnimations({subtree: true}).filter((a) => a.playState === 'running').length;
}"""

# The smallest text on slide i, in screen pixels: reveal.js scales the slide, and an SVG's
# viewBox scales its text again, which getScreenCTM includes. Divided by `per`: the
# screen-to-canvas ratio on the desktop pass, the layout-to-phone width ratio on the phone.
_SMALLEST_TEXT = """([i, per]) => {
  const s = __deckSlides()[i];
  const scale = s.getBoundingClientRect().width / (s.offsetWidth || 1);
  let px = Infinity, sample = '';
  for (const el of s.querySelectorAll('*')) {
    if (el.closest('aside.notes') || el.closest('.slide-number')) continue;
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!own || !el.getClientRects().length) continue;
    const st = getComputedStyle(el);
    if (st.visibility !== 'visible' || st.opacity === '0') continue;
    const ctm = el instanceof SVGElement && el.getScreenCTM && el.getScreenCTM();
    const size = parseFloat(st.fontSize) * (ctm ? Math.hypot(ctm.c, ctm.d) : scale) / per;
    if (size < px) { px = size; sample = el.textContent.trim().slice(0, 40); }
  }
  return {px, sample};
}"""

_SIDEWAYS = "document.documentElement.scrollWidth > innerWidth + 1"
_VIEWPORT_META = "!!document.querySelector('meta[name=viewport]')"
# Chromium logs this for every failed load, which the asset gate already reports by URL.
_LOAD_FAILED = "Failed to load resource"


def _first_line(exc: BaseException) -> str:
    lines = str(exc).splitlines()
    return lines[0] if lines else type(exc).__name__


class DeckError(Exception):
    """A page that never started reveal.js, with what its console said."""


def _playwright():
    try:
        from playwright.sync_api import sync_playwright  # ty: ignore[unresolved-import]
    except ImportError:
        sys.exit(f"a web deck needs Playwright: run this command through `{WITH_BROWSER}`")
    return sync_playwright


def _axe_source() -> str:
    from importlib import resources

    try:
        return (resources.files("axe_playwright_python") / "axe.min.js").read_text()
    except ModuleNotFoundError:
        sys.exit(f"a web deck needs axe-core: run this command through `{WITH_BROWSER}`")


def _launch(pw):
    try:
        return pw.chromium.launch()
    except Exception as exc:  # playwright raises its own Error type, not importable here
        sys.exit(
            f"Chromium did not start ({_first_line(exc)}). Install it once with "
            f"`uv run --no-project --with {PLAYWRIGHT} playwright install chromium`"
        )


class _Watch:
    """What a page asked the network and the console for while it loaded and ran."""

    def __init__(self, page) -> None:
        self.errors: list[str] = []
        self.missing: list[str] = []
        self.hosts: set[str] = set()
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("requestfailed", self._failed)
        page.on("response", lambda r: r.status >= 400 and self.missing.append(r.url))
        page.on("request", self._request)

    def _console(self, message) -> None:
        if message.type == "error" and not message.text.startswith(_LOAD_FAILED):
            self.errors.append(message.text)

    def _failed(self, request) -> None:
        # reveal.js drops an iframe or video src when it leaves the slide; that is no miss.
        if "ERR_ABORTED" not in (request.failure or ""):
            self.missing.append(request.url)

    def _request(self, request) -> None:
        if request.url.startswith(("http:", "https:")):
            self.hosts.add(request.url.split("/")[2])


def _open(
    browser,
    deck: pathlib.Path,
    viewport: dict,
    query: str = "",
    during: str = "",
    seen: bool = False,
    **context,
):
    """A page with the deck loaded and reveal.js ready, or DeckError saying why not.

    `seen` marks a later pass on a deck that already started once, so a failure there is
    reported as that pass failing rather than as a page that is not a deck.
    """
    page = browser.new_context(viewport=viewport, bypass_csp=True, **context).new_page()
    watch = _Watch(page)
    try:
        page.goto(deck.resolve().as_uri() + query)
        page.wait_for_function("window.Reveal && Reveal.isReady && Reveal.isReady()", timeout=15000)
    except Exception as exc:
        said = [*dict.fromkeys(watch.errors), *(f"failed to load {u}" for u in watch.missing)]
        if said:
            raise DeckError(
                f"reveal.js never became ready{during}: {'; '.join(said)[:300]}"
            ) from exc
        if seen:
            raise DeckError(
                f"the deck started on the desktop but not{during} ({_first_line(exc)})"
            ) from exc
        raise DeckError(
            f"not a reveal.js deck: window.Reveal never became ready{during} "
            f"(a deck that imports reveal.js as a module must set window.Reveal; "
            f"{_first_line(exc)})"
        ) from exc
    page.evaluate(_SLIDES)
    return page, watch


def check_html(
    path: pathlib.Path,
    level: str = "AAA",
    min_pt: float = 14,
    dense_words: int = 60,
    title_words: int = 14,
    jargon: tuple[str, ...] = (),
    backup_from: int | None = None,
) -> list[Finding]:
    """Gate a reveal.js deck in Chromium: text, accessibility, assets, motion and phone fit."""
    if not path.is_file():
        return [Finding(ERROR, "unreadable", f"{path}: no such file")]
    with _playwright()() as pw:
        browser = _launch(pw)
        try:
            found = _check_in(
                browser, path, level, min_pt, dense_words, title_words, jargon, backup_from
            )
        except DeckError as exc:
            return [Finding(ERROR, "unreadable", f"{path}: {exc}")]
        except Exception as exc:  # a Playwright error mid-check, not a verdict on the deck
            return [Finding(ERROR, "unreadable", f"{path}: the browser failed: {exc}")]
        finally:
            browser.close()
    found.append(
        Finding(
            INFO,
            "render",
            "a figure that reads wrong is invisible to this check; render and look at every slide",
        )
    )
    return sorted(found, key=lambda f: (RANK[f.severity], f.slide or 0))


def _check_in(
    browser,
    path: pathlib.Path,
    level: str,
    min_pt: float,
    dense_words: int,
    title_words: int,
    jargon: tuple[str, ...],
    backup_from: int | None,
) -> list[Finding]:
    rules = [*AXE_CONTRAST[level], *AXE_ALT]
    found: list[Finding] = []
    page, watch = _open(browser, path, CANVAS)
    page.add_style_tag(content=_STILL)
    page.add_script_tag(content=_axe_source())
    count = page.evaluate(_COUNT)
    if not count:
        return [Finding(ERROR, "unreadable", f"{path}: no slides")]
    # Text sizes are judged on the slide's own canvas, the way a pptx point size is judged
    # on a 13.33-inch slide: the threshold scales with the deck's configured width.
    scale = page.evaluate("Reveal.getScale()")
    size = page.evaluate("[Reveal.getConfig().width, Reveal.getConfig().height]")
    canvas = f"{size[0]}x{size[1]}" if all(isinstance(v, int | float) for v in size) else "slide"
    wide = size[0] if isinstance(size[0], int | float) else CANVAS["width"]
    min_px = min_pt * 96 / 72 * wide / CANVAS["width"]
    titles: dict[str, list[int]] = {}
    no_notes: list[int] = []
    unchecked = 0
    in_backup = False
    for i in range(count):
        number = i + 1
        slide = page.evaluate(_READ_SLIDE, i)
        title = slide["title"]
        if title:
            titles.setdefault(title.casefold(), []).append(number)
        else:
            found.append(
                Finding(
                    BLOCK, "no-title", "no h1, h2 or h3; the outline sees an untitled slide", number
                )
            )
        in_backup = (
            in_backup
            or is_backup_divider(title)
            or (backup_from is not None and number >= backup_from)
        )
        lines = [ln.strip() for ln in slide["text"].splitlines() if ln.strip()]
        body = [ln for ln in lines if ln != title]
        visible = " ".join(lines)
        if not slide["notes"] and not in_backup:
            no_notes.append(number)
        found += text_gates(
            number,
            title,
            visible,
            visible,
            sum(len(_WORD.findall(t)) for t in body),
            in_backup,
            dense_words,
            title_words,
            jargon,
            "{words} words on the slide (> {limit}), figure labels included; "
            "if they are prose, move it to the script or a figure",
        )
        if slide["spill"]:
            found.append(
                Finding(
                    WARN,
                    "overflow",
                    f"drawn past the slide's edge: {', '.join(map(repr, slide['spill'][:3]))}",
                    number,
                )
            )
        text = page.evaluate(_SMALLEST_TEXT, [i, scale])
        if text["px"] < min_px:
            found.append(
                Finding(
                    WARN,
                    "small-text",
                    f"{text['px']:.0f}px < {min_px:.0f}px ({min_pt:g}pt) on the "
                    f"{canvas} canvas: {text['sample']!r}",
                    number,
                )
            )
        axe = page.evaluate(_AXE_SLIDE, [i, rules])
        unchecked += axe["unchecked"]
        # One finding per colour pair on a slide, as the pptx path reports it.
        pairs: dict[tuple, list[str]] = {}
        for node in axe["violations"]:
            if node["rule"].startswith("color-contrast"):
                d = node["data"] or {}
                need = d.get("expectedContrastRatio")
                if level == "AAA" and node["rule"] == "color-contrast":
                    need = _AAA_NEED.get(need, need)
                key = (d.get("fgColor"), d.get("bgColor"), d.get("contrastRatio"), need)
                pairs.setdefault(key, []).append(node["target"])
            else:
                found.append(
                    Finding(
                        BLOCK,
                        "alt-text",
                        f"{node['target']} has no text alternative ({node['rule']})",
                        number,
                    )
                )
        for (fg, bg, ratio, need), targets in pairs.items():
            more = f" and {len(targets) - 1} more" if len(targets) > 1 else ""
            found.append(
                Finding(
                    BLOCK,
                    "contrast",
                    f"{fg} on {bg} = {ratio}:1, needs {need} ({level}): {targets[0]}{more}",
                    number,
                )
            )
    found += duplicate_titles(titles)
    if no_notes:
        found.append(
            Finding(WARN, "no-notes", f"no script in the speaker notes on slides {no_notes}")
        )
    if unchecked:
        found.append(
            Finding(
                INFO,
                "contrast",
                f"{unchecked} text element(s) inside an SVG figure, or over an image, "
                "gradient or overlap, that axe cannot resolve; not checked",
            )
        )

    watches = [watch]
    for run_pass in (_motion_pass, _phone_pass):
        try:
            watches.append(run_pass(browser, path, found))
        except DeckError as exc:
            # A pass that cannot start is its own finding; the desktop results still stand.
            found.append(Finding(ERROR, "unreadable", f"{path}: {exc}"))

    errors = [e for w in watches for e in w.errors]
    missing = {u for w in watches for u in w.missing}
    hosts = {h for w in watches for h in w.hosts}
    for url in sorted(missing):
        found.append(Finding(BLOCK, "asset", f"failed to load: {url}"))
    for message in dict.fromkeys(errors):
        found.append(Finding(BLOCK, "script", f"console error: {message[:160]}"))
    if hosts:
        found.append(
            Finding(
                WARN,
                "offline",
                f"needs the network to present: {', '.join(sorted(hosts))}; "
                "vendor the files so the deck opens with no connection",
            )
        )
    return found


def _motion_pass(browser, path: pathlib.Path, found: list[Finding]) -> _Watch:
    moving, watch = _open(
        browser,
        path,
        CANVAS,
        during=" with reduced motion requested",
        seen=True,
        reduced_motion="reduce",
    )
    count = moving.evaluate(_COUNT)
    restless = [i + 1 for i in range(count) if moving.evaluate(_MOVING, i)]
    if restless:
        found.append(
            Finding(
                WARN,
                "motion",
                f"still animating with reduced motion requested, on slides {restless}; "
                "honour prefers-reduced-motion",
            )
        )
    return watch


def _phone_pass(browser, path: pathlib.Path, found: list[Finding]) -> _Watch:
    # Scroll view loads slides near the viewport only, so each is read after scrolling to it.
    phone, watch = _open(
        browser, path, PHONE, during=" on a phone", seen=True, is_mobile=True, has_touch=True
    )
    phone.add_style_tag(content=_ALL_FRAGMENTS)
    # Without a viewport meta tag a phone lays the page out 980px wide and shrinks it.
    per = phone.evaluate("innerWidth") / PHONE["width"]
    spilled: list[int] = []
    panned: list[int] = []
    least: dict = {"px": float("inf"), "sample": ""}
    for i in range(phone.evaluate(_COUNT)):
        phone.evaluate(_SCROLL_TO, i)
        slide = phone.evaluate(_READ_SLIDE, i)
        if slide["spill"]:
            spilled.append(i + 1)
        if slide["panned"]:
            panned.append(i + 1)
        text = phone.evaluate(_SMALLEST_TEXT, [i, per])
        if text["px"] < least["px"]:
            least = text
    if not phone.evaluate(_VIEWPORT_META):
        found.append(
            Finding(
                WARN,
                "phone",
                'no <meta name="viewport">; a phone lays the page out 980px wide and shrinks it',
            )
        )
    if phone.evaluate(_SIDEWAYS):
        found.append(Finding(WARN, "phone", "the page scrolls sideways on a phone"))
    if least["px"] < PHONE_MIN_PX:
        found.append(
            Finding(
                WARN,
                "phone",
                f"text renders at {least['px']:.1f}px on a {PHONE['width']}px-wide phone "
                f"(< {PHONE_MIN_PX}px): {least['sample']!r}",
            )
        )
    if spilled:
        found.append(
            Finding(
                WARN, "phone", f"content drawn past the slide's edge on a phone, slides {spilled}"
            )
        )
    if panned:
        found.append(
            Finding(
                INFO,
                "phone",
                f"figures pan sideways on a phone on slides {panned}; check the phone render "
                "shows the mark each one is about",
            )
        )
    return watch


# Tags whose text reads as a separate line in a speaker note.
_BREAKS = {"p", "div", "li", "br", "ul", "ol", "aside", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


# Elements with no end tag, which never open a level of nesting.
_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


class _Sections(HTMLParser):
    """Each slide's first heading and speaker notes, from the static HTML.

    Read as reveal.js reads them. A slide is a <section> directly inside `.slides`, or
    directly inside such a section (a vertical stack), with no sections of its own; a section
    nested deeper is content. A data-notes attribute wins over <aside class="notes">, even
    when empty. A data-markdown section is split as reveal.js's markdown plugin splits it
    (see _from_markdown). Slides marked data-visibility hidden or uncounted are left out, as
    reveal.js leaves them out of its slide list.
    """

    def __init__(self) -> None:
        super().__init__()
        self.slides: list[dict[str, str]] = []
        self._stack: list[dict[str, str]] = []
        self._open: list[tuple[str, str]] = []  # (tag, role): role is "slides", "slide" or ""
        self._into: str | None = None
        self._closer = ""
        self._depth = 0

    def _role(self, tag: str, a: dict[str, str | None]) -> str:
        if tag != "section":
            return "slides" if "slides" in (a.get("class") or "").split() else ""
        parent = self._open[-1][1] if self._open else ""
        grand = self._open[-2][1] if len(self._open) > 1 else ""
        if parent == "slides" or (parent == "slide" and grand == "slides"):
            return "slide"
        return ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        role = self._role(tag, a)
        if tag not in _VOID:
            self._open.append((tag, role))
        if role == "slide":
            if self._stack:
                self._stack[-1]["leaf"] = ""
            self._stack.append(
                {
                    "title": "",
                    "notes": "",
                    "data-notes": a.get("data-notes") or "",
                    "has-data-notes": "1" if "data-notes" in a else "",
                    "leaf": "1",
                    "hidden": "1" if a.get("data-visibility") in ("hidden", "uncounted") else "",
                    "markdown": "1" if "data-markdown" in a else "",
                    "separator": a.get("data-separator") or "",
                    "vertical": a.get("data-separator-vertical") or "",
                    "notes-separator": a.get("data-separator-notes") or "",
                    "md": "",
                }
            )
            return
        if not self._stack:
            return
        if self._into:
            if tag == self._closer:
                self._depth += 1
            self._gap(tag)
        elif tag in ("h1", "h2", "h3") and not self._stack[-1]["title"]:
            self._into, self._closer, self._depth = "title", tag, 1
        elif tag == "aside" and "notes" in (a.get("class") or "").split():
            self._into, self._closer, self._depth = "notes", tag, 1
            if self._stack[-1]["notes"]:
                self._stack[-1]["notes"] += "\n"

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._into and self._stack:
            self._gap(tag)

    def handle_endtag(self, tag: str) -> None:
        role = ""
        for k in range(len(self._open) - 1, -1, -1):
            if self._open[k][0] == tag:
                role = self._open[k][1]
                del self._open[k:]
                break
        if self._into:
            self._gap(tag)
            if tag == self._closer:
                self._depth -= 1
                if self._depth == 0:
                    self._into = None
        elif role == "slide" and self._stack:
            s = self._stack.pop()
            if s["hidden"] or not s["leaf"]:
                return
            if s["has-data-notes"]:
                s["notes"] = s["data-notes"]
            self.slides.extend(_from_markdown(s) if s["markdown"] else [s])

    def _gap(self, tag: str) -> None:
        """A line break inside notes, a space inside a title, where the markup breaks text."""
        if tag in _BREAKS:
            self._stack[-1][self._into or "notes"] += "\n" if self._into == "notes" else " "

    def handle_data(self, data: str) -> None:
        if not self._stack:
            return
        if self._into:
            self._stack[-1][self._into] += data
        elif self._stack[-1]["markdown"]:
            self._stack[-1]["md"] += data


# reveal.js 6.0.2's markdown plugin defaults, as it ships them: the slide separator, and the
# notes separator it splits on case-insensitively (its `s*` carries no backslash).
_MD_SLIDE = r"\r?\n---\r?\n"
_MD_NOTES = r"^s*notes?:"
_MD_ASIDE = re.compile(r'<aside[^>]*class="[^"]*\bnotes\b[^"]*"[^>]*>(.*?)</aside>', re.S)
_MD_FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)


def _from_markdown(s: dict[str, str]) -> list[dict[str, str]]:
    """Split a data-markdown section the way reveal.js's markdown plugin does.

    Slides split at the data-separator (and data-separator-vertical) patterns, matched across
    the whole text in multiline mode, before any markdown is parsed, so a `---` inside a code
    fence splits too. Notes are the text after the notes separator, only when it splits the
    slide into exactly two parts, or an <aside class="notes"> written in the markdown. The
    title is the first `#` line outside a code fence.
    """
    pattern = s["separator"] or _MD_SLIDE
    if s["vertical"]:
        pattern = f"{pattern}|{s['vertical']}"
    notes_at = re.compile(s["notes-separator"] or _MD_NOTES, re.I | re.M)
    out = []
    for chunk in re.split(pattern, s["md"], flags=re.M):
        parts = notes_at.split(chunk)
        text, notes = (parts[0], parts[1]) if len(parts) == 2 else (chunk, "")
        aside = _MD_ASIDE.search(text)
        if aside and not notes:
            notes = re.sub(r"<[^>]+>", " ", aside.group(1))
        prose = _MD_FENCE.sub("", _MD_ASIDE.sub("", text))
        title = next(
            (ln.lstrip("#").strip() for ln in prose.splitlines() if ln.strip().startswith("#")),
            "",
        )
        if s["has-data-notes"]:
            notes = s["data-notes"]
        out.append({**s, "title": title or s["title"], "notes": notes})
    return out


def html_slides(path: pathlib.Path) -> list[tuple[str, str]]:
    """(title, notes) per slide of a reveal.js deck, in order, without a browser."""
    parser = _Sections()
    parser.feed(path.read_text(encoding="utf-8"))
    out = []
    for s in parser.slides:
        notes = "\n".join(" ".join(ln.split()) for ln in s["notes"].splitlines())
        out.append((" ".join(s["title"].split()), re.sub(r"\n{2,}", "\n", notes).strip()))
    return out


def render_html(deck: pathlib.Path, out: pathlib.Path) -> int:
    """One PNG per slide at 1920x1080, the deck on a phone, and the print PDF."""
    if not deck.is_file():
        sys.exit(f"{deck}: no such file")
    with _playwright()() as pw:
        browser = _launch(pw)
        try:
            pngs, phones, pdf = _render_in(browser, deck, out)
        except DeckError as exc:
            sys.exit(f"{deck}: {exc}")
        except Exception as exc:  # a Playwright error mid-render
            sys.exit(f"{deck}: the browser failed: {_first_line(exc)}")
        finally:
            browser.close()
    sheets = contact_sheets(pngs, out) + contact_sheets(phones, out, "phone-sheet", 4)
    print("renderer: chromium")
    print(f"pdf: {pdf}")
    print(f"slides: {len(pngs)} png at {SCREEN['width']}x{SCREEN['height']} in {out}")
    print(f"phone: {len(phones)} png at {PHONE['width']}x{PHONE['height']}")
    for sheet in sheets:
        print(f"  {sheet}")
    return 0


def _render_in(browser, deck: pathlib.Path, out: pathlib.Path):
    # Every pass must start before render claims the folder, so a deck that fails in any of
    # them leaves no marker and no half-written render.
    page, _ = _open(browser, deck, SCREEN)
    count = page.evaluate(_COUNT)
    if not count:
        raise DeckError("no slides")
    phone, _ = _open(
        browser, deck, PHONE, during=" on a phone", seen=True, is_mobile=True, has_touch=True
    )
    printed, _ = _open(browser, deck, CANVAS, query="?print-pdf", during=" for print", seen=True)
    try:
        printed.wait_for_function("document.querySelectorAll('.pdf-page').length > 0")
    except Exception as exc:
        raise DeckError(f"the print layout never appeared ({_first_line(exc)})") from exc
    prepare_out(out)
    page.add_style_tag(content=_STILL)
    pngs = []
    for i in range(count):
        page.evaluate(_READ_SLIDE, i)
        target = out / f"slide-{i + 1:02d}.png"
        page.screenshot(path=str(target))
        pngs.append(target)
    phone.add_style_tag(content=_ALL_FRAGMENTS)
    phones = []
    for i in range(phone.evaluate(_COUNT)):
        phone.evaluate(_SCROLL_TO, i)
        phone.wait_for_timeout(150)
        target = out / f"phone-{i + 1:02d}.png"
        phone.screenshot(path=str(target))
        phones.append(target)
    pdf = out / (deck.stem + ".pdf")
    printed.pdf(path=str(pdf), print_background=True, prefer_css_page_size=True)
    return pngs, phones, pdf


# ----------------------------------------------------------------- render --


def is_wsl() -> bool:
    try:
        return "microsoft" in pathlib.Path("/proc/version").read_text().lower()
    except OSError:
        return False


def powerpoint_available() -> bool:
    if sys.platform == "win32":
        roots = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]
        shell = shutil.which("powershell")
    elif is_wsl():
        roots = ["/mnt/c/Program Files", "/mnt/c/Program Files (x86)"]
        shell = shutil.which("powershell.exe")
    else:
        return False
    return bool(shell and powerpoint_exes(roots))


def powerpoint_exes(roots: list[str]) -> list[str]:
    """Click-to-Run installs under root/Office16, MSI and volume licences under Office16."""
    layouts = (("root", "Office*"), ("Office*",))
    return [
        g
        for r in roots
        if r
        for layout in layouts
        for g in glob.glob(os.path.join(r, "Microsoft Office", *layout, "POWERPNT.EXE"))
    ]


def libreoffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def pick_renderer(preference: str = "auto") -> str:
    if preference in ("auto", "powerpoint") and powerpoint_available():
        return "powerpoint"
    if preference == "powerpoint":
        sys.exit(
            "PowerPoint is not reachable from here (needs Windows, or WSL with Office installed)"
        )
    if libreoffice():
        return "libreoffice"
    sys.exit("no renderer: install LibreOffice, or run where PowerPoint is installed")


# Quit only an instance this script started: PowerPoint is single-instance, so
# Quit() on an app the user already had open closes their windows too.
PS1 = """$ErrorActionPreference = "Stop"
$app = New-Object -ComObject PowerPoint.Application
$before = $app.Presentations.Count
try {{
  $p = $app.Presentations.Open("{src}", $true, $false, $false)
  $p.SaveAs("{dst}", 32)
  $p.Close()
}} finally {{
  if ($before -eq 0 -and $app.Presentations.Count -eq 0) {{ $app.Quit() }}
}}
"""


def write_ps1(script: pathlib.Path, src: str, dst: str) -> None:
    """PowerShell 5 reads a BOM-less .ps1 as the ANSI code page; a non-ASCII
    user name in the temp path would arrive mangled. UTF-8 with BOM is read right."""
    script.write_text(PS1.format(src=src, dst=dst), encoding="utf-8-sig")


def _powershell(args: list[str]) -> str:
    exe = "powershell" if sys.platform == "win32" else "powershell.exe"
    done = subprocess.run(
        [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if done.returncode:
        sys.exit(f"PowerPoint export failed:\n{done.stdout}{done.stderr}")
    return done.stdout.strip()


def render_powerpoint(deck: pathlib.Path, pdf: pathlib.Path) -> None:
    if sys.platform == "win32":
        work = pathlib.Path(tempfile.mkdtemp(prefix="techne-slides-"))
        to_win = str
    else:
        # PowerPoint cannot open a \\wsl$ path; stage the deck on the Windows side.
        win_tmp = _powershell(["-Command", "[IO.Path]::GetTempPath()"])
        base = subprocess.run(
            ["wslpath", "-u", win_tmp], capture_output=True, text=True, check=True
        ).stdout.strip()
        work = pathlib.Path(tempfile.mkdtemp(prefix="techne-slides-", dir=base))

        def to_win(p: pathlib.Path) -> str:
            return subprocess.run(
                ["wslpath", "-w", str(p)], capture_output=True, text=True, check=True
            ).stdout.strip()

    try:
        src, dst, script = work / "deck.pptx", work / "deck.pdf", work / "export.ps1"
        shutil.copyfile(deck, src)
        write_ps1(script, to_win(src), to_win(dst))
        _powershell(["-File", to_win(script)])
        shutil.copyfile(dst, pdf)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def render_libreoffice(deck: pathlib.Path, pdf: pathlib.Path) -> None:
    exe = libreoffice()
    assert exe, "pick_renderer checked this"
    with tempfile.TemporaryDirectory(prefix="techne-slides-") as work:
        # A private profile: with the user's own profile, an open LibreOffice
        # window swallows the conversion and soffice still exits 0.
        profile = (pathlib.Path(work) / "profile").as_uri()
        subprocess.run(
            [
                exe,
                f"-env:UserInstallation={profile}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                work,
                str(deck),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
        made = pathlib.Path(work) / (deck.stem + ".pdf")
        if not made.exists():
            sys.exit("LibreOffice exited cleanly and wrote no PDF")
        shutil.copyfile(made, pdf)


def contact_sheets(
    pngs: list[pathlib.Path], out: pathlib.Path, name: str = "sheet", cols: int = 2
) -> list[pathlib.Path]:
    """Images tiled cols across and two down, so a whole deck can be looked at in a few reads."""
    try:
        from PIL import Image  # ty: ignore[unresolved-import]
    except ImportError:
        return []
    sheets = []
    per = cols * 2
    for k in range(0, len(pngs), per):
        ims = [Image.open(p) for p in pngs[k : k + per]]
        w, h = ims[0].size
        sheet = Image.new("RGB", (w * cols, h * 2), "white")
        for i, im in enumerate(ims):
            sheet.paste(im, ((i % cols) * w, (i // cols) * h))
        target = out / f"{name}-{k // per + 1:02d}.png"
        sheet.save(target)
        sheets.append(target)
    return sheets


MARKER = ".techne-slides"


def prepare_out(out: pathlib.Path) -> None:
    """Claim an output folder, or refuse one that holds someone else's files.

    render deletes slide-*.png and sheet-*.png and overwrites <deck>.pdf in the
    folder it is given, so it only works in a folder that is new, empty, or
    already carries its marker. A deck's own folder is none of those.
    """
    if out.exists() and not out.is_dir():
        sys.exit(f"{out} is a file; pass a folder for the render output")
    if out.is_dir() and any(out.iterdir()) and not (out / MARKER).exists():
        sys.exit(f"{out} is not empty and was not made by render; pass a new folder")
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).touch()
    for old in [*out.glob("slide-*.png"), *out.glob("sheet-*.png"), *out.glob("phone-*.png")]:
        old.unlink()


def render(deck: pathlib.Path, out: pathlib.Path, preference: str = "auto", dpi: int = 80) -> int:
    if deck.suffix.lower() in HTML:
        return render_html(deck, out)
    if not shutil.which("pdftoppm"):
        sys.exit("pdftoppm not found (poppler-utils)")
    prepare_out(out)
    pdf = out / (deck.stem + ".pdf")
    if deck.suffix.lower() == ".pdf":
        # Already exported by the tool that will show it (a Typst or Beamer deck).
        renderer = "pdf"
        if deck.resolve() != pdf.resolve():
            shutil.copyfile(deck, pdf)
    else:
        renderer = pick_renderer(preference)
        (render_powerpoint if renderer == "powerpoint" else render_libreoffice)(deck, pdf)
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(out / "slide")], check=True)
    pngs = sorted(out.glob("slide-*.png"))
    sheets = contact_sheets(pngs, out)
    print(f"renderer: {renderer}")
    if renderer == "libreoffice":
        print(
            "  approximate: LibreOffice substitutes missing fonts; fit can differ in the real app"
        )
    print(f"pdf: {pdf}")
    print(f"slides: {len(pngs)} png in {out}")
    for sheet in sheets:
        print(f"  {sheet}")
    return 0


# ------------------------------------------------------------------- main --


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="run the gates")
    c.add_argument("deck", type=pathlib.Path)
    c.add_argument("--level", choices=sorted(LEVELS), default="AAA")
    c.add_argument("--min-pt", type=float, default=14)
    c.add_argument("--dense-words", type=int, default=60)
    c.add_argument("--title-words", type=int, default=14)
    c.add_argument(
        "--jargon",
        default="",
        help="comma-separated terms a newcomer would not know; flagged on talk slides",
    )
    c.add_argument(
        "--backup-from",
        type=int,
        default=None,
        help="first backup slide, when no divider is titled Backup or Appendix",
    )
    r = sub.add_parser(
        "render",
        help="screenshot a web deck in Chromium; export a .pptx through PowerPoint or "
        "LibreOffice (or take a PDF), then rasterize",
    )
    r.add_argument("deck", type=pathlib.Path)
    r.add_argument("out", type=pathlib.Path)
    r.add_argument(
        "--renderer",
        choices=("auto", "powerpoint", "libreoffice"),
        default="auto",
        help=".pptx only",
    )
    r.add_argument("--dpi", type=int, default=80, help=".pptx and PDF only")
    t = sub.add_parser("script", help="print the speaker notes as a read-aloud script")
    t.add_argument("deck", type=pathlib.Path)
    t.add_argument("--wpm", type=int, default=140)
    args = ap.parse_args()

    if args.cmd == "render":
        return render(args.deck, args.out, args.renderer, args.dpi)
    if args.cmd == "script":
        code, out = script(args.deck, args.wpm)
        print(out, file=sys.stderr if code else sys.stdout)
        return code
    terms = tuple(t.strip() for t in args.jargon.split(",") if t.strip())
    found = check(
        args.deck,
        args.level,
        args.min_pt,
        args.dense_words,
        args.title_words,
        terms,
        args.backup_from,
    )
    print(args.deck)
    for finding in found:
        print(f"  {finding}")
    code, line = verdict(found)
    print(f"\n{line}")
    return code


if __name__ == "__main__":
    sys.exit(main())
