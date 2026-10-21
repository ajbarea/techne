#!/usr/bin/env python3
"""Render markdown files to print-quality PDFs through Typst + cmarker.

Run with ``uv run --with 'typst>=0.15,<0.16' python render.py ...``, the ``typst`` wheel
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
import shutil
import subprocess
import sys
import tempfile

# The prose check and the install table ship in the plugin's _shared/ directory.
sys.dont_write_bytecode = True  # a missing-tool exit leaves no file behind in the plugin cache
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "_shared"))
import doctor_lib  # noqa: E402  # ty: ignore[unresolved-import]

try:
    import prose_check  # ty: ignore[unresolved-import]
except ImportError:  # an install without prose_check.py
    prose_check = None

try:
    import length_budget  # ty: ignore[unresolved-import]
except ImportError:  # an install without length_budget.py
    length_budget = None

SETUP = "/graphe:setup"

# Ordered fallbacks. Libertinus Serif and DejaVu Sans Mono
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
    """Return (title, subtitle, remaining body) for one markdown document.

    Blank lines and whole-line HTML comments (a budget declaration) may precede the title;
    the comments stay at the head of the body."""
    lines = text.splitlines()
    title = subtitle = None
    index = 0
    comments: list[str] = []

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
        elif stripped.startswith("<!--"):
            end = index
            while end < len(lines) and not lines[end].rstrip().endswith("-->"):
                end += 1
            if end >= len(lines):
                break
            comments += lines[index : end + 1]
            index = end + 1
        else:
            break
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

    return title, subtitle, "\n".join([*comments, *lines[index:]]).lstrip("\n")


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
    # Installed by the skill at render time, not a declared dependency.
    import typst  # ty: ignore[unresolved-import]

    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        typ_path = build_typ(src, work)
        dest = out_dir / f"{src.stem}.pdf"
        typst.compile(str(typ_path), output=str(dest), root=str(work))
    return dest, pdf_fonts(dest)


def prose_lines(body: str) -> list[str]:
    """Advisory REVIEW lines for the markdown body; never decides the exit code."""
    if prose_check is None:
        return ["  INFO   prose check not installed (no _shared/prose_check.py)"]
    hits, skipped = prose_check.report(prose_check.markdown_prose(body))
    if skipped:
        return [f"  INFO   {skipped}"]
    return [f"  REVIEW prose {hit.count}x {hit.name}: \u201c{hit.example}\u201d" for hit in hits]


def budget_lines(
    src: pathlib.Path, pdf: pathlib.Path, source: str, body: str
) -> tuple[list[str], str]:
    """Lines to print, and the reason the run fails: over budget or an unreadable line.

    `source` holds the declaration; `body` is what follows the title block."""
    if length_budget is None:
        return ["  INFO   budget check not installed (no _shared/length_budget.py)"], ""
    hint = "`<!-- budget: N words -->` in the .md"
    lines, reason = [], ""
    for severity, message in length_budget.assess(source, pdf, hint=hint, body=body):
        lines.append(f"  {severity:<6} budget {message}")
        if severity == "BLOCK":
            reason = f"{src.name}: {message}"
    return lines, reason


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
    parser.add_argument(
        "--no-prose", action="store_true", help="skip the plain-prose pattern check"
    )
    args = parser.parse_args(argv)
    if shutil.which("strings") is None:
        doctor_lib.exit_missing([("strings", "strings")], SETUP)

    sources = sorted(args.src.glob("*.md")) if args.src.is_dir() else [args.src]
    if not sources:
        print(f"no markdown files under {args.src}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    drift: list[str] = []
    budget_failures: list[str] = []
    for src in sources:
        dest, fonts = render(src, args.out)
        print(f"{dest}  [{', '.join(fonts)}]")
        source = src.read_text(encoding="utf-8")
        body = split_front_matter(source)[2]
        if not args.no_prose:
            for line in prose_lines(body):
                print(line)
        lines, over = budget_lines(src, dest, source, body)
        for line in lines:
            print(line)
        if over:
            budget_failures.append(over)
        if args.check_fonts and sorted(args.check_fonts) != fonts:
            drift.append(f"{dest.name}: expected {sorted(args.check_fonts)}, got {fonts}")

    for heading, failures in (("font drift", drift), ("budget", budget_failures)):
        if failures:
            print(f"\n{heading}:", file=sys.stderr)
            for line in failures:
                print(f"  {line}", file=sys.stderr)
    return 1 if drift or budget_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
