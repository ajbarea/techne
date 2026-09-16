"""End-to-end tests for techne:latex against a real TeX Live.

These build actual documents, so they need latexmk and poppler. CI does not
install TeX; it sets TECHNE_NO_TEX=1 to say so out loud. Without that variable
a machine missing the toolchain fails here rather than reporting a green run
that quietly tested nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest
from conftest import LATEX_SCRIPT

NEEDED = ("latexmk", "pdftotext", "pdfinfo", "pdffonts")
MISSING = [tool for tool in NEEDED if not shutil.which(tool)]
needs_tex = pytest.mark.skipif(bool(MISSING), reason=f"not installed: {', '.join(MISSING)}")

CLEAN = r"""
\documentclass{article}
\begin{document}
\section{One}\label{sec:one}
Section \ref{sec:one} is fine.
\end{document}
"""

FATAL = r"""
\documentclass{article}
\begin{document}
\includegraphics{nofile.png}
\end{document}
"""

DRAFT = r"""
\documentclass{article}
\begin{document}
\section{One}
FILL in the answer here.
\end{document}
"""

MISSING_CITE = r"""
\documentclass{article}
\usepackage[backend=biber]{biblatex}
\addbibresource{refs.bib}
\begin{document}
Problem 1. See \cite{ghost}.
\printbibliography
\end{document}
"""

BIB = "@article{real, author = {A. Author}, title = {T}, journal = {J}, year = {2026}}\n"


def run(target, *args):
    proc = subprocess.run(
        [sys.executable, str(LATEX_SCRIPT), str(target), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout


def test_the_toolchain_is_present_or_its_absence_is_declared():
    """Green by absence is the failure this guards. Either the builds below
    ran, or the environment said in writing that it opted out of them."""
    if not MISSING:
        return
    assert os.environ.get("TECHNE_NO_TEX") == "1", (
        f"missing {', '.join(MISSING)} and TECHNE_NO_TEX is unset: the end-to-end "
        "tests would have skipped silently. Install TeX Live and poppler, or set "
        "TECHNE_NO_TEX=1 to opt out on purpose."
    )


@needs_tex
def test_a_clean_document_exits_zero(tmp_path):
    (tmp_path / "doc.tex").write_text(CLEAN)
    code, out = run(tmp_path)
    assert code == 0, out
    assert "CLEAN" in out


@needs_tex
def test_a_document_that_cannot_build_exits_one(tmp_path):
    (tmp_path / "doc.tex").write_text(FATAL)
    code, out = run(tmp_path)
    assert code == 1, out
    assert "FAILED to build" in out
    assert "tex-error" in out


@needs_tex
def test_a_surviving_draft_marker_exits_two(tmp_path):
    (tmp_path / "doc.tex").write_text(DRAFT)
    code, out = run(tmp_path)
    assert code == 2, out
    assert "draft-marker" in out


@needs_tex
def test_a_marker_the_repo_does_not_use_is_not_gated_on(tmp_path):
    (tmp_path / "doc.tex").write_text(DRAFT)
    code, out = run(tmp_path, "--markers", "TKTK")
    assert code == 0, out


@needs_tex
def test_an_unresolvable_citation_exits_two(tmp_path):
    """The whole reason build and gate are one command: latexmk exits 0 here."""
    (tmp_path / "doc.tex").write_text(MISSING_CITE)
    (tmp_path / "refs.bib").write_text(BIB)
    code, out = run(tmp_path)
    assert code == 2, out
    # Which gate fires depends on how far the biber cycle got: on a first build
    # the .blg names the key, on a rebuild biblatex's own warning does too.
    assert "ghost" in out or "undefined-cite" in out

    latexmk = subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", "doc.tex"],
        cwd=tmp_path,
        capture_output=True,
    )
    assert latexmk.returncode == 0, "latexmk started failing on this; the premise changed"


@needs_tex
def test_coverage_reads_a_prompt_from_another_directory(tmp_path):
    (tmp_path / "doc.tex").write_text(DRAFT)
    prompt = tmp_path / "elsewhere" / "assignment.md"
    prompt.parent.mkdir()
    prompt.write_text("Problem 1. Do a thing.\nProblem 2. Do another.\n")
    code, out = run(tmp_path, "--prompt", str(prompt), "--markers", "TKTK")
    assert code == 0, out
    assert "Problem 1, Problem 2" in out


# ------------------------------------------------- build invocation (no TeX) --


def test_the_log_is_unwrapped_at_the_source(lx, tmp_path, monkeypatch):
    """TeX breaks log lines at 79 columns mid-word, which every regex in this
    script reads across. Losing max_print_line makes the gates miss findings
    quietly rather than fail."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env", {})
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(lx.subprocess, "run", fake_run)
    tex = tmp_path / "doc.tex"
    tex.write_text(CLEAN)
    lx.build(tex, "pdf")

    assert captured["env"]["max_print_line"] == "10000"
    assert "-file-line-error" in captured["cmd"]
    assert "-halt-on-error" in captured["cmd"]
    assert captured["cmd"][1] == "-pdf"


def test_the_engine_flag_is_passed_through(lx, tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        lx.subprocess,
        "run",
        lambda cmd, **kw: (
            captured.setdefault("cmd", cmd) and subprocess.CompletedProcess(cmd, 0, "", "")
        ),
    )
    tex = tmp_path / "doc.tex"
    tex.write_text(CLEAN)
    lx.build(tex, "lualatex")
    assert captured["cmd"][1] == "-lualatex"
