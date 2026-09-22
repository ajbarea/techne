#!/usr/bin/env python3
"""Gate a .pptx before it is presented, and render it through the app that will show it.

    python slides.py check  <deck.pptx> [--level AAA|AA] [--min-pt 14]
    python slides.py render <deck.pptx> <out-dir> [--renderer auto|powerpoint|libreoffice]

No Python dependencies. ``render`` needs poppler's ``pdftoppm`` plus either
PowerPoint (native Windows, or Windows from WSL) or LibreOffice; with Pillow
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
_FIGURE = re.compile(r"\d+(?:\.\d+)?\s?%|\b\d+\s?/\s?\d+\b|\b\d+\.\d+\b|\b\d+ of \d+\b|\b\d{3,}\b")
_BACKUP_TITLE = re.compile(r"^\s*backup\b", re.I)
_WORD = re.compile(r"[\w\u2019'-]+")


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

    def xml(self, part: str) -> ET.Element:
        return ET.fromstring(self.zip.read(part))

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        """Relationship id -> (type suffix, absolute part name)."""
        folder, name = posixpath.split(part)
        rels_part = posixpath.join(folder, "_rels", name + ".rels")
        if rels_part not in self.names:
            return {}
        out = {}
        for rel in self.xml(rels_part).findall("pr:Relationship", NS):
            target = rel.get("Target", "")
            if rel.get("TargetMode") == "External":
                continue
            absolute = posixpath.normpath(posixpath.join(folder, target))
            out[rel.get("Id", "")] = (rel.get("Type", "").rsplit("/", 1)[-1], absolute)
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


def solid_fill(parent: ET.Element | None) -> str | None:
    if parent is None:
        return None
    clr = parent.find("a:solidFill/a:srgbClr", NS)
    return clr.get("val", "").upper() if clr is not None else None


def background(pkg: Package, slide: str) -> str | None:
    """First solid sRGB background on the slide, its layout, then its master."""
    part: str | None = slide
    for next_kind in ("slideLayout", "slideMaster", None):
        if part is None:
            return None
        fill = solid_fill(pkg.xml(part).find("p:cSld/p:bg/p:bgPr", NS))
        if fill:
            return fill
        part = pkg.related(part, next_kind) if next_kind else None
    return None


class Run:
    __slots__ = ("bold", "color", "field", "font", "size", "text")

    def __init__(self, el: ET.Element, field: bool) -> None:
        rpr = el.find("a:rPr", NS)
        self.text = "".join(t.text or "" for t in el.findall("a:t", NS))
        self.field = field
        sz = rpr.get("sz") if rpr is not None else None
        self.size = int(sz) / 100 if sz else None
        self.bold = rpr is not None and rpr.get("b") in ("1", "true")
        self.color = solid_fill(rpr)
        latin = rpr.find("a:latin", NS) if rpr is not None else None
        self.font = latin.get("typeface") if latin is not None else None


def runs(body: ET.Element | None) -> list[Run]:
    if body is None:
        return []
    out = [Run(r, False) for r in body.iter(f"{{{NS['a']}}}r")]
    out += [Run(f, True) for f in body.iter(f"{{{NS['a']}}}fld")]
    return out


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


class Slide:
    """Everything the gates read from one slide, flattened in z-order."""

    def __init__(self, pkg: Package, part: str, number: int) -> None:
        self.number = number
        self.bg = background(pkg, part)
        root = pkg.xml(part)
        self.title = ""
        self.has_title = False
        self.body_text: list[str] = []
        self.text_runs: list[tuple[Run, str | None]] = []  # (run, colour behind it)
        self.pictures: list[bool] = []  # has alt text or is marked decorative
        filled: list[tuple[tuple[int, int, int, int], str]] = []
        tree = root.find("p:cSld/p:spTree", NS)
        for el in tree.iter() if tree is not None else []:
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "sp":
                self._shape(el, filled)
            elif tag == "pic":
                pr = el.find("p:nvPicPr/p:cNvPr", NS)
                descr = (pr.get("descr") or "").strip() if pr is not None else ""
                decorative = b'decorative val="1"' in ET.tostring(el)
                self.pictures.append(bool(descr) or decorative)
            elif tag == "graphicFrame":
                self._table(el, filled)
        notes = pkg.related(part, "notesSlide")
        self.notes = _notes_text(pkg, notes) if notes else ""

    def _behind(self, el: ET.Element, filled) -> str | None:
        rect = box(el)
        if rect is not None:
            for outer, fill in reversed(filled):
                if contains(outer, rect):
                    return fill
        return self.bg

    def _shape(self, el: ET.Element, filled) -> None:
        ph = el.find("p:nvSpPr/p:nvPr/p:ph", NS)
        ph_type = ph.get("type", "body") if ph is not None else None
        body = el.find("p:txBody", NS)
        found = runs(body)
        text = "".join(r.text for r in found if not r.field).strip()
        own_fill = solid_fill(el.find("p:spPr", NS))
        behind = own_fill or self._behind(el, filled)
        if ph_type in ("title", "ctrTitle"):
            self.has_title = self.has_title or bool(text)
            self.title = self.title or " ".join(text.split())
        elif ph_type != "sldNum" and text:
            self.body_text.append(text)
        self.text_runs += [(r, behind) for r in found if r.text.strip()]
        rect = box(el)
        if own_fill and rect is not None:
            filled.append((rect, own_fill))

    def _table(self, el: ET.Element, filled) -> None:
        frame_bg = self._behind(el, filled)
        for cell in el.iter(f"{{{NS['a']}}}tc"):
            fill = solid_fill(cell.find("a:tcPr", NS)) or frame_bg
            found = runs(cell.find("a:txBody", NS))
            text = "".join(r.text for r in found).strip()
            if text:
                self.body_text.append(text)
            self.text_runs += [(r, fill) for r in found if r.text.strip()]


def _notes_text(pkg: Package, part: str) -> str:
    out = []
    for sp in pkg.xml(part).iter(f"{{{NS['p']}}}sp"):
        ph = sp.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if ph is not None and ph.get("type") == "body":
            out += [r.text for r in runs(sp.find("p:txBody", NS)) if not r.field]
    return "".join(out).strip()


# ------------------------------------------------------------------ gates --


def check(
    path: pathlib.Path,
    level: str = "AAA",
    min_pt: float = 14,
    dense_words: int = 60,
    title_words: int = 14,
) -> list[Finding]:
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
        s = Slide(pkg, part, number)
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
        in_backup = in_backup or bool(_BACKUP_TITLE.match(s.title))

        pairs: dict[tuple[str, str, bool], str] = {}
        for run, behind in s.text_runs:
            if run.font:
                fonts.setdefault(run.font, set()).add(number)
            if not run.field and run.size is not None and run.size < min_pt:
                found.append(
                    Finding(
                        WARN,
                        "small-text",
                        f"{run.size:g}pt < {min_pt:g}pt: {run.text.strip()[:40]!r}",
                        number,
                    )
                )
            if run.color is None or behind is None:
                unchecked += 1
                continue
            big = is_large(run.size, run.bold)
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
        if "—" in visible:
            found.append(Finding(BLOCK, "em-dash", "em-dash in slide text", number))
        if not s.notes:
            no_notes.append(number)
        # The title slide carries dates, venues and author lists by design.
        if in_backup or number == 1:
            continue
        figures = sorted({m.group(0) for m in _FIGURE.finditer(visible)})
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
        words = sum(len(_WORD.findall(t)) for t in s.body_text)
        if words > dense_words:
            found.append(
                Finding(
                    REVIEW,
                    "dense",
                    f"{words} words of body text (> {dense_words}); move the rest to the notes",
                    number,
                )
            )
        if len(s.title.split()) > title_words:
            found.append(
                Finding(
                    REVIEW,
                    "long-title",
                    f"{len(s.title.split())}-word title (> {title_words})",
                    number,
                )
            )

    for title, numbers in titles.items():
        if len(numbers) > 1:
            found.append(
                Finding(WARN, "duplicate-title", f"slides {numbers} share the title {title!r}")
            )
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
        found.append(Finding(WARN, "no-notes", f"no speaker notes on slides {no_notes}"))
    if unchecked:
        found.append(
            Finding(
                INFO,
                "contrast",
                f"{unchecked} text run(s) inherit their colour or sit on a non-solid "
                "background; not checked",
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
    exes = [
        g
        for r in roots
        if r
        for g in glob.glob(os.path.join(r, "Microsoft Office", "root", "Office*", "POWERPNT.EXE"))
    ]
    return bool(shell and exes)


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
  if ($before -eq 0) {{ $app.Quit() }}
}}
"""


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
        script.write_text(PS1.format(src=to_win(src), dst=to_win(dst)), encoding="ascii")
        _powershell(["-File", to_win(script)])
        shutil.copyfile(dst, pdf)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def render_libreoffice(deck: pathlib.Path, pdf: pathlib.Path) -> None:
    exe = libreoffice()
    assert exe, "pick_renderer checked this"
    with tempfile.TemporaryDirectory(prefix="techne-slides-") as work:
        subprocess.run(
            [exe, "--headless", "--convert-to", "pdf", "--outdir", work, str(deck)],
            check=True,
            capture_output=True,
            timeout=300,
        )
        shutil.copyfile(pathlib.Path(work) / (deck.stem + ".pdf"), pdf)


def contact_sheets(pngs: list[pathlib.Path], out: pathlib.Path) -> list[pathlib.Path]:
    try:
        from PIL import Image  # ty: ignore[unresolved-import]
    except ImportError:
        return []
    sheets = []
    for k in range(0, len(pngs), 4):
        ims = [Image.open(p) for p in pngs[k : k + 4]]
        w, h = ims[0].size
        sheet = Image.new("RGB", (w * 2, h * 2), "white")
        for i, im in enumerate(ims):
            sheet.paste(im, ((i % 2) * w, (i // 2) * h))
        target = out / f"sheet-{k // 4 + 1:02d}.png"
        sheet.save(target)
        sheets.append(target)
    return sheets


def render(deck: pathlib.Path, out: pathlib.Path, preference: str = "auto", dpi: int = 80) -> int:
    if not shutil.which("pdftoppm"):
        sys.exit("pdftoppm not found (poppler-utils)")
    out.mkdir(parents=True, exist_ok=True)
    renderer = pick_renderer(preference)
    pdf = out / (deck.stem + ".pdf")
    (render_powerpoint if renderer == "powerpoint" else render_libreoffice)(deck, pdf)
    for old in out.glob("slide-*.png"):
        old.unlink()
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
    r = sub.add_parser("render", help="export through PowerPoint or LibreOffice, then rasterize")
    r.add_argument("deck", type=pathlib.Path)
    r.add_argument("out", type=pathlib.Path)
    r.add_argument("--renderer", choices=("auto", "powerpoint", "libreoffice"), default="auto")
    r.add_argument("--dpi", type=int, default=80)
    args = ap.parse_args()

    if args.cmd == "render":
        return render(args.deck, args.out, args.renderer, args.dpi)
    found = check(args.deck, args.level, args.min_pt, args.dense_words, args.title_words)
    print(args.deck)
    for finding in found:
        print(f"  {finding}")
    code, line = verdict(found)
    print(f"\n{line}")
    return code


if __name__ == "__main__":
    sys.exit(main())
