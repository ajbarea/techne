#!/usr/bin/env python3
"""Check what the graphe document skills need on this machine, and print each fix.

Runs on the system python3 (3.9 or newer, standard library only) and installs nothing.
Usage: python3 doctor.py
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

sys.dont_write_bytecode = True  # a doctor leaves no file behind, not even in the plugin cache
PLUGIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN / "_shared"))
import doctor_lib as d  # noqa: E402  # ty: ignore[unresolved-import]
import plugin_keys as pk  # noqa: E402  # ty: ignore[unresolved-import]

KEYS = pk.load_keys(PLUGIN)

POPPLER = ("pdftotext", "pdfinfo", "pdffonts", "pdftoppm")
PPTX_ONLY = "only for a deck that must be a .pptx"


def pptx_renderer(platform: d.Platform) -> d.Check:
    for name in ("soffice", "libreoffice"):
        found = d.native_which(name, platform)
        if found:
            return d.Check(d.OK, "pptx-renderer", f"LibreOffice at {found}")
    # PowerPoint runs on Windows, so under WSL powershell.exe is the Windows one by design.
    shell = d.which("powershell.exe" if platform.wsl else "powershell")
    exes = d.powerpoint_exes(d.office_roots(platform.wsl)) if shell else []
    if exes:
        return d.Check(d.OK, "pptx-renderer", f"PowerPoint at {exes[0]}")
    return d.Check(
        d.OPTIONAL,
        "pptx-renderer",
        "no LibreOffice or PowerPoint (graphe:slides needs one to render a .pptx)",
        d.fix_lines(platform, d.FIXES["libreoffice"]),
    )


def pptxgenjs(platform: d.Platform) -> d.Check:
    node, npm = d.native_which("node", platform), d.native_which("npm", platform)
    if not node or not npm:
        return d.Check(d.NA, "pptxgenjs", "node and npm are missing")
    here = Path.cwd()
    for folder in [here, *here.parents]:
        found = folder / "node_modules" / "pptxgenjs"
        if found.is_dir():
            return d.Check(d.OK, "pptxgenjs", str(found))
    return d.Check(
        d.OPTIONAL,
        "pptxgenjs",
        f"not found from {here} or a parent folder; require() reads the deck folder's "
        f"node_modules, not the global one, so run the fix in the deck folder ({PPTX_ONLY})",
        d.fix_lines(platform, d.FIXES["pptxgenjs"]),
    )


def key_checks(environ: Mapping[str, str]) -> list[d.Check]:
    """The optional search keys: a missing one never makes the result `missing`."""
    hint = pk.configure_hint(PLUGIN)
    return [
        d.Check(d.OK if present else d.OPTIONAL, name, detail)
        for name, present, detail in pk.doctor_entries(KEYS, environ, hint)
    ]


def checks(platform: d.Platform, environ: Mapping[str, str] | None = None) -> list[d.Check]:
    def program(name, fix, **options):
        return d.program(platform, name, fix, **options)

    version = ("--version",)
    found = [
        program("uv", "uv", version_argv=version),
        program("latexmk", "latex", version_argv=("-v",)),
        program("pdflatex", "latex", version_argv=version),
        program("biber", "biber", required=False, version_argv=version, why="biblatex"),
    ]
    found += [program(name, "poppler") for name in POPPLER]
    found += [
        program("strings", "strings", why="graphe:pdf reads embedded font names with it"),
        d.guarded(
            "chromium", True, lambda: d.chromium(required=True, why="graphe:slides web decks")
        ),
        d.guarded("pptx-renderer", False, lambda: pptx_renderer(platform)),
        program("node", "node", required=False, version_argv=version, why=PPTX_ONLY),
        d.guarded("pptxgenjs", False, lambda: pptxgenjs(platform)),
    ]
    return found + key_checks(os.environ if environ is None else environ)


def main() -> int:
    return d.report(checks(d.detect_platform()))


if __name__ == "__main__":
    sys.exit(main())
