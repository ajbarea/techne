#!/usr/bin/env python3
"""Build one LaTeX document and gate the result on its log, its PDF, and the prompt it answers.

Run with ``python latex.py <path>``. Needs TeX Live and poppler on PATH; no
Python dependencies.

Building and gating are one command on purpose. ``latexmk`` exits 0 on a
document whose citations all resolved to ``[?]``, so the exit code is not the
signal -- the parsed log is. Splitting the two would make the gate skippable.

The log is unwrapped at the source with ``max_print_line``, so every warning
lands on one line and the regexes below hold. Without it TeX breaks messages at
79 columns mid-word.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys

ERROR, BLOCK, WARN, REVIEW, INFO = "ERROR", "BLOCK", "WARN", "REVIEW", "INFO"
RANK = {ERROR: 0, BLOCK: 1, WARN: 2, REVIEW: 3, INFO: 4}

# Anything still bracketed by one of these in the built PDF is an unfinished draft.
DEFAULT_MARKERS = ("FILL", "TODO", "XXX", "CITATION NEEDED")

# Unwrap the log and widen error context. TeX defaults to 79 columns.
LOG_ENV = {"max_print_line": "10000", "error_line": "254", "half_error_line": "238"}

_FILE_LINE_ERROR = re.compile(r"^(?P<file>[^:\s][^:]*):(?P<line>\d+):\s*(?P<msg>.+)$")
_BANG_ERROR = re.compile(r"^!\s*(?P<msg>.+)$")
_UNDEF_REF = re.compile(r"Reference `(?P<key>[^']+)' on page (?P<page>\d+) undefined")
_UNDEF_CITE = re.compile(r"Citation `(?P<key>[^']+)' on page (?P<page>\d+) undefined")
_MULTI_LABEL = re.compile(r"Label `(?P<key>[^']+)' multiply defined")
_MISSING_CHAR = re.compile(r"^Missing character: There is no (?P<ch>.+?) in font (?P<font>.+?)!")
_OVERFULL = re.compile(
    r"^(?P<kind>Overfull|Underfull) \\(?P<box>[hv])box "
    r"\((?P<amount>[\d.]+)pt too (?:wide|high)\).*?at lines? (?P<lines>[\d-]+)"
)
_FONT_SUB = re.compile(
    r"^LaTeX Font Warning: Font shape `(?P<shape>[^']+)' (?:undefined|not available)"
)
_PKG_WARN = re.compile(
    r"^(?:Package|Class) (?P<pkg>[\w@-]+) Warning: (?P<msg>.+?)(?: on input line \d+)?\.?$"
)
_RERUN = re.compile(r"Rerun to get|Please \(re\)run|Rerun LaTeX")
# Biber prefixes every line with its own module trace, so this cannot be anchored.
_BLG_ERROR = re.compile(r"\b(?P<level>ERROR|WARN) - (?P<msg>.+)$")
_NO_ENTRY = re.compile(r"(?:didn't find a database entry for|entry could not be found)")
# Problem headers, as they appear in both an assignment prompt and the answer PDF.
_PROBLEM = re.compile(
    r"\b(?P<kind>Problem|Question|Exercise|Task|Bonus)\s*#?\s*(?P<num>\d{1,2}|[A-Z])\b"
)


class Finding:
    __slots__ = ("gate", "message", "severity", "where")

    def __init__(self, severity: str, gate: str, message: str, where: str = "") -> None:
        self.severity = severity
        self.gate = gate
        self.message = message
        self.where = where

    def __str__(self) -> str:
        tail = f"  [{self.where}]" if self.where else ""
        return f"{self.severity:<6} {self.gate:<16} {self.message}{tail}"


def find_main_tex(target: pathlib.Path) -> pathlib.Path:
    """Resolve a path to the one .tex holding \\documentclass."""
    if target.is_file():
        return target
    if not target.is_dir():
        sys.exit(f"no such path: {target}")
    roots = [
        p
        for p in sorted(target.glob("*.tex"))
        if "\\documentclass" in p.read_text(encoding="utf-8", errors="replace")
    ]
    if not roots:
        sys.exit(f"no .tex with \\documentclass in {target}")
    if len(roots) > 1:
        names = ", ".join(p.name for p in roots)
        sys.exit(f"{len(roots)} root documents in {target} ({names}); name the one to build")
    return roots[0]


def build(tex: pathlib.Path, engine: str) -> int:
    """Run latexmk to completion. Returns its exit code; the log carries the detail."""
    cmd = [
        "latexmk",
        f"-{engine}",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-silent",
        tex.name,
    ]
    env = {**os.environ, **LOG_ENV}
    proc = subprocess.run(cmd, cwd=tex.parent, env=env, capture_output=True, text=True)
    return proc.returncode


def parse_log(log: pathlib.Path, overfull_pt: float) -> list[Finding]:
    if not log.exists():
        return [Finding(ERROR, "build", f"no log written at {log.name}")]

    found: list[Finding] = []
    overfull: list[tuple[float, str, str]] = []
    missing_chars: dict[str, int] = {}
    pkg_warns: set[tuple[str, str]] = set()
    text = log.read_text(encoding="utf-8", errors="replace")

    for raw in text.splitlines():
        line = raw.rstrip()

        if m := _BANG_ERROR.match(line):
            found.append(Finding(ERROR, "tex-error", m["msg"]))
            continue
        starts_warning = line.startswith(("Package", "Class", "LaTeX"))
        if (m := _FILE_LINE_ERROR.match(line)) and not starts_warning:
            found.append(Finding(ERROR, "tex-error", m["msg"], f"{m['file']}:{m['line']}"))
            continue
        if m := _UNDEF_REF.search(line):
            found.append(
                Finding(
                    BLOCK,
                    "undefined-ref",
                    f"\\ref{{{m['key']}}} renders as ??",
                    f"page {m['page']}",
                )
            )
            continue
        if m := _UNDEF_CITE.search(line):
            found.append(
                Finding(
                    BLOCK,
                    "undefined-cite",
                    f"\\cite{{{m['key']}}} renders as [?]",
                    f"page {m['page']}",
                )
            )
            continue
        if m := _MULTI_LABEL.search(line):
            found.append(
                Finding(
                    BLOCK,
                    "duplicate-label",
                    f"label `{m['key']}' defined twice; refs point at the last one",
                )
            )
            continue
        if m := _MISSING_CHAR.match(line):
            missing_chars[m["font"]] = missing_chars.get(m["font"], 0) + 1
            continue
        if m := _OVERFULL.match(line):
            amount = float(m["amount"])
            if m["kind"] == "Overfull" and amount >= overfull_pt:
                overfull.append((amount, m["box"], m["lines"]))
            continue
        if m := _FONT_SUB.match(line):
            found.append(
                Finding(
                    WARN,
                    "font-substitution",
                    f"font shape `{m['shape']}' undefined; TeX substituted",
                )
            )
            continue
        if m := _PKG_WARN.match(line):
            # biblatex reports an unresolvable key as a package warning, not as
            # "Citation undefined". It still renders as [?].
            if _NO_ENTRY.search(m["msg"]):
                found.append(
                    Finding(
                        BLOCK,
                        "undefined-cite",
                        "an entry is missing from the database; it renders as [?]",
                        m["pkg"],
                    )
                )
            else:
                pkg_warns.add((m["pkg"], m["msg"].strip()))
            continue

    # A surviving rerun request means latexmk stopped before the document settled.
    if _RERUN.search(text[-4000:]):
        found.append(
            Finding(BLOCK, "unsettled", "log still asks for a rerun; cross-references are stale")
        )

    for font, count in sorted(missing_chars.items(), key=lambda kv: -kv[1]):
        found.append(
            Finding(BLOCK, "missing-glyph", f"{count} character(s) dropped from the PDF", font)
        )

    overfull.sort(reverse=True)
    for amount, box, lines in overfull[:5]:
        found.append(
            Finding(WARN, "overfull", f"{box}box {amount:.1f}pt over the measure", f"lines {lines}")
        )
    if len(overfull) > 5:
        found.append(Finding(INFO, "overfull", f"{len(overfull) - 5} more below the largest five"))

    for pkg, msg in sorted(pkg_warns):
        found.append(Finding(WARN, "package", msg, pkg))
    return found


def parse_blg(tex: pathlib.Path) -> list[Finding]:
    """Biber fails into its own log; latexmk still exits 0 with an empty bibliography."""
    found: list[Finding] = []
    for blg in tex.parent.glob(f"{tex.stem}.blg"):
        for line in blg.read_text(encoding="utf-8", errors="replace").splitlines():
            if m := _BLG_ERROR.search(line):
                # Every biber WARN survives into the PDF as a wrong or absent entry.
                severity = ERROR if m["level"] == "ERROR" else BLOCK
                found.append(Finding(severity, "bibliography", m["msg"].strip(), blg.name))
    return found


def pdf_text(pdf: pathlib.Path) -> str:
    proc = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True)
    return proc.stdout


def pdf_checks(pdf: pathlib.Path, text: str, markers: tuple[str, ...]) -> list[Finding]:
    if not pdf.exists():
        return [Finding(ERROR, "no-pdf", "the build produced no PDF")]

    found: list[Finding] = []
    for marker in markers:
        hits = text.count(marker)
        if hits:
            found.append(
                Finding(BLOCK, "draft-marker", f"{hits}x `{marker}' still in the PDF", pdf.name)
            )

    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    pages = next(
        (row.split(":", 1)[1].strip() for row in info.splitlines() if row.startswith("Pages:")),
        "?",
    )
    found.append(
        Finding(INFO, "pdf", f"{pages} pages, {pdf.stat().st_size / 1024:.0f} KB", pdf.name)
    )

    listing = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True)
    rows = listing.stdout.splitlines()[2:]
    families = sorted({row.split()[0].split("+")[-1] for row in rows if row.strip()})
    if families:
        found.append(
            Finding(INFO, "fonts", ", ".join(families[:6]) + (" ..." if len(families) > 6 else ""))
        )
    return found


def prompt_coverage(prompt: pathlib.Path, text: str) -> list[Finding]:
    """Heuristic. Reports what it could not locate; never decides the exit code."""
    source = prompt.read_text(encoding="utf-8", errors="replace")
    asked = {f"{m['kind']} {m['num']}" for m in _PROBLEM.finditer(source)}
    answered = {f"{m['kind']} {m['num']}" for m in _PROBLEM.finditer(text)}
    if not asked:
        return [
            Finding(INFO, "coverage", f"no problem headers in {prompt.name}; nothing to compare")
        ]

    missing = sorted(asked - answered, key=lambda s: (s.split()[0], s.split()[1]))
    if missing:
        return [
            Finding(
                REVIEW, "coverage", f"not located in the PDF: {', '.join(missing)}", prompt.name
            )
        ]
    return [Finding(INFO, "coverage", f"all {len(asked)} headers in {prompt.name} appear")]


def find_prompt(tex: pathlib.Path) -> tuple[pathlib.Path | None, str]:
    """A sidecar of the document itself is not the prompt it answers."""
    own = f"{tex.stem}.extracted"
    candidates = [p for p in sorted(tex.parent.glob("*.extracted.md")) if p.stem != own]
    if len(candidates) == 1:
        return candidates[0], ""
    if not candidates:
        return None, ""
    names = ", ".join(p.name for p in candidates)
    return None, f"{len(candidates)} possible prompts ({names}); pass --prompt to pick one"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "path", type=pathlib.Path, help="a .tex, or a directory holding one root document"
    )
    ap.add_argument(
        "--prompt",
        type=pathlib.Path,
        help="assignment text to check coverage against "
        "(default: the lone *.extracted.md beside the source)",
    )
    ap.add_argument("--no-prompt", action="store_true", help="skip the coverage check entirely")
    ap.add_argument(
        "--markers",
        default=",".join(DEFAULT_MARKERS),
        help="comma-separated draft markers that must not survive into the PDF",
    )
    ap.add_argument(
        "--overfull-pt",
        type=float,
        default=5.0,
        help="report overfull boxes at or above this many points (default 5)",
    )
    ap.add_argument(
        "--engine",
        default="pdf",
        choices=["pdf", "xelatex", "lualatex"],
        help="latexmk engine flag (default pdf, i.e. pdflatex)",
    )
    args = ap.parse_args()

    tex = find_main_tex(args.path)
    code = build(tex, args.engine)
    log, pdf = tex.with_suffix(".log"), tex.with_suffix(".pdf")

    found = parse_log(log, args.overfull_pt) + parse_blg(tex)
    text = pdf_text(pdf) if pdf.exists() else ""
    markers = tuple(m.strip() for m in args.markers.split(",") if m.strip())
    found += pdf_checks(pdf, text, markers)

    if not args.no_prompt and text:
        prompt, ambiguous = (args.prompt, "") if args.prompt else find_prompt(tex)
        if prompt and prompt.exists():
            found += prompt_coverage(prompt, text)
        elif ambiguous:
            found.append(Finding(INFO, "coverage", ambiguous))

    if code != 0 and not any(f.severity == ERROR for f in found):
        found.append(Finding(ERROR, "build", f"latexmk exited {code}, log says nothing"))

    found.sort(key=lambda f: RANK[f.severity])
    # A build that died wrote no .aux, so every ref and cite reads as undefined.
    # Reporting that cascade buries the one error that actually has to be fixed.
    if any(f.severity == ERROR for f in found):
        hidden = sum(f.severity in (BLOCK, WARN, REVIEW) for f in found)
        found = [f for f in found if f.severity in (ERROR, INFO)]
        if hidden:
            found.append(
                Finding(INFO, "cascade", f"{hidden} downstream finding(s) hidden until it is fixed")
            )

    print(f"{tex.parent}/{tex.name}")
    for finding in found:
        print(f"  {finding}")

    errors = sum(f.severity == ERROR for f in found)
    blocks = sum(f.severity == BLOCK for f in found)
    reviews = sum(f.severity == REVIEW for f in found)
    if errors:
        print(f"\nFAILED to build: {errors} error(s). Log: {log}")
        return 1
    if blocks:
        print(f"\nBUILT but not submittable: {blocks} blocker(s). Log: {log}")
        return 2
    verdict = f"\nCLEAN: {pdf}"
    if reviews:
        verdict += f" -- {reviews} coverage item(s) to confirm by eye"
    print(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
