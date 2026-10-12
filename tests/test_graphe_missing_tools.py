"""graphe's scripts name the install command for a missing tool instead of a traceback."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest
from conftest import LATEX_SCRIPT, RENDER_SCRIPT, ROOT, stub_dir

PLUGIN = ROOT / "plugins" / "graphe"
ENV = {"TECHNE_DOCTOR_OS": "debian", "TECHNE_DOCTOR_WSL": "0"}


def run(script, *args, path, env=ENV):
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        env={"PATH": path, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def tex_file(tmp_path):
    tex = tmp_path / "main.tex"
    tex.write_text("\\documentclass{article}\\begin{document}x\\end{document}\n")
    return tex


def test_latex_names_every_missing_tool_and_its_install(tmp_path):
    proc = run(LATEX_SCRIPT, tex_file(tmp_path), path=stub_dir(tmp_path))
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    lines = proc.stderr.splitlines()
    assert "latexmk not found on PATH." in lines
    assert "  fix: sudo apt install texlive-latex-extra latexmk" in lines
    assert "pdftotext, pdfinfo, pdffonts not found on PATH." in lines
    assert "  fix: sudo apt install poppler-utils" in lines
    assert lines[-1] == "Run /graphe:setup to check everything else this plugin needs."


def test_latex_on_macos(tmp_path):
    env = {**ENV, "TECHNE_DOCTOR_OS": "macos"}
    proc = run(LATEX_SCRIPT, tex_file(tmp_path), path=stub_dir(tmp_path), env=env)
    assert "  fix: brew install --cask mactex-no-gui" in proc.stderr.splitlines()


def test_render_names_strings_before_compiling(tmp_path):
    src = tmp_path / "a.md"
    src.write_text("# A\n\nbody\n")
    proc = run(RENDER_SCRIPT, src, tmp_path / "out", path=stub_dir(tmp_path))
    assert proc.returncode == 1 and "Traceback" not in proc.stderr
    assert "  fix: sudo apt install binutils" in proc.stderr.splitlines()


def test_slides_render_names_pdftoppm(sl, monkeypatch, tmp_path):
    monkeypatch.setenv("TECHNE_DOCTOR_OS", "debian")
    monkeypatch.setattr(sl.shutil, "which", lambda _name: None)
    deck = tmp_path / "talk.pdf"
    deck.write_bytes(b"%PDF-1.7")
    with pytest.raises(SystemExit) as exc:
        sl.render(deck, tmp_path / "out")
    assert "fix: sudo apt install poppler-utils" in str(exc.value)


def test_slides_without_a_renderer_names_libreoffice(sl, monkeypatch):
    monkeypatch.setenv("TECHNE_DOCTOR_OS", "debian")
    monkeypatch.setattr(sl, "powerpoint_available", lambda: False)
    monkeypatch.setattr(sl, "libreoffice", lambda: None)
    with pytest.raises(SystemExit) as exc:
        sl.pick_renderer()
    assert "fix: sudo apt install libreoffice-impress" in str(exc.value)


def test_slides_ignores_a_windows_side_libreoffice_on_wsl(sl, monkeypatch):
    monkeypatch.setenv("TECHNE_DOCTOR_WSL", "1")
    windows = "/mnt/c/Program Files/LibreOffice/program/soffice"
    monkeypatch.setattr(sl.doctor_lib, "which", lambda name, *a, **k: windows)
    assert sl.libreoffice() is None
    monkeypatch.setenv("TECHNE_DOCTOR_WSL", "0")
    assert sl.libreoffice() == windows


def test_the_scripts_leave_no_bytecode(tmp_path):
    plugin = tmp_path / "plugin" / "graphe"
    shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns("__pycache__", "evals"))

    def listing():
        return sorted(p.relative_to(plugin).as_posix() for p in plugin.rglob("*"))

    before = listing()
    tex = tex_file(tmp_path)
    src = tmp_path / "a.md"
    src.write_text("# A\n")
    env = {**ENV, "PYTHONDONTWRITEBYTECODE": ""}
    path = stub_dir(tmp_path)
    run(plugin / "skills" / "latex" / "scripts" / "latex.py", tex, path=path, env=env)
    run(
        plugin / "skills" / "pdf" / "scripts" / "render.py", src, tmp_path / "o", path=path, env=env
    )
    assert listing() == before
