#!/usr/bin/env python3
"""Render markdown files to print-quality PDFs through Typst + cmarker.

Run with ``uv run --with typst python render.py ...``, the ``typst`` wheel
bundles the compiler, so nothing needs to be installed on the machine.

The first ``# Heading`` of each file becomes the PDF title and the rendered
title block; an italic-only line immediately after it becomes the subtitle.
Both are lifted out of the body so the template can style them separately.

Font resolution is reported on every run. Typst falls back silently when a
family is missing or is in a format it cannot read (Type 1 ``.pfb``, for
one), which is how a document quietly changes typeface between machines.
``--check-fonts`` asserts the resolved set instead of trusting it.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
import tempfile

# Ordered fallbacks. Libertinus Serif, New Computer Modern and DejaVu Sans Mono
# ship inside the typst wheel, so the last entry of each list always resolves.
SERIF = ["Charter", "XCharter", "Libertinus Serif"]
SANS = ["Helvetica Neue", "Helvetica", "TeX Gyre Heros", "Arial", "Libertinus Serif"]
MONO = ["SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono"]

TEMPLATE = pathlib.Path(__file__).resolve().parent.parent / "templates" / "document.typ.tmpl"

_H1 = re.compile(r"^#\s+(.*?)\s*$")
_EM_ONLY = re.compile(r"^\*(?P<text>[^*].*?)\*$|^_(?P<alt>[^_].*?)_$")


def _typst_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _typst_list(values: list[str]) -> str:
    return "(" + ", ".join(_typst_str(v) for v in values) + ",)"


def split_front_matter(text: str) -> tuple[str | None, str | None, str]:
    """Return (title, subtitle, remaining body) for one markdown document."""
    lines = text.splitlines()
    title = subtitle = None
    index = 0

    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines):
        match = _H1.match(lines[index])
        if match:
            title = match.group(1)
            index += 1

    if title is not None:
        probe = index
        while probe < len(lines) and not lines[probe].strip():
            probe += 1
        if probe < len(lines):
            match = _EM_ONLY.match(lines[probe].strip())
            if match:
                subtitle = match.group("text") or match.group("alt")
                index = probe + 1

    return title, subtitle, "\n".join(lines[index:]).lstrip("\n")


def build_typ(src: pathlib.Path, work: pathlib.Path) -> pathlib.Path:
    """Write the .typ driver plus the body-only markdown it reads."""
    title, subtitle, body = split_front_matter(src.read_text(encoding="utf-8"))
    body_path = work / f"{src.stem}.body.md"
    body_path.write_text(body, encoding="utf-8")

    filled = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("{{SERIF}}", _typst_list(SERIF))
        .replace("{{SANS}}", _typst_list(SANS))
        .replace("{{MONO}}", _typst_list(MONO))
        .replace("{{TITLE}}", _typst_str(title or src.stem))
        .replace("{{SUBTITLE}}", _typst_str(subtitle) if subtitle else "none")
        .replace("{{BODY_PATH}}", _typst_str(body_path.name))
    )
    typ_path = work / f"{src.stem}.typ"
    typ_path.write_text(filled, encoding="utf-8")
    return typ_path


def pdf_fonts(pdf: pathlib.Path) -> list[str]:
    """Font families actually embedded in a PDF, via the subset-tagged names."""
    raw = subprocess.run(["strings", str(pdf)], capture_output=True, text=True, check=False).stdout
    found = re.findall(r"BaseFont\s*/(?:[A-Z]{6}\+)?([A-Za-z0-9-]+)", raw)
    return sorted({name.split("-")[0] for name in found})


def render(src: pathlib.Path, out_dir: pathlib.Path) -> tuple[pathlib.Path, list[str]]:
    import typst

    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        typ_path = build_typ(src, work)
        dest = out_dir / f"{src.stem}.pdf"
        typst.compile(str(typ_path), output=str(dest), root=str(work))
    return dest, pdf_fonts(dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=pathlib.Path, help="markdown file or directory")
    parser.add_argument("out", type=pathlib.Path, help="output directory for PDFs")
    parser.add_argument(
        "--check-fonts",
        metavar="FAMILY",
        nargs="+",
        help="fail unless every rendered PDF embeds exactly these families",
    )
    args = parser.parse_args(argv)

    sources = sorted(args.src.glob("*.md")) if args.src.is_dir() else [args.src]
    if not sources:
        print(f"no markdown files under {args.src}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    drift: list[str] = []
    for src in sources:
        dest, fonts = render(src, args.out)
        print(f"{dest}  [{', '.join(fonts)}]")
        if args.check_fonts and sorted(args.check_fonts) != fonts:
            drift.append(f"{dest.name}: expected {sorted(args.check_fonts)}, got {fonts}")

    if drift:
        print("\nfont drift:", file=sys.stderr)
        for line in drift:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
