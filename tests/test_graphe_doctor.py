"""The graphe setup doctor, run on the system python3 with a stub PATH."""

from __future__ import annotations

import re
import shutil
import sys

import pytest
from conftest import (
    DOCTOR_LIB,
    EMAIL,
    MACHINE_PATH,
    ROOT,
    _load,
    doctor_lines,
    fake_chromium,
    run_doctor,
    stub_dir,
)

PLUGIN = ROOT / "plugins" / "graphe"
DOCTOR = PLUGIN / "skills" / "setup" / "scripts" / "doctor.py"
AGENTS = PLUGIN / "AGENTS.md"
TEX = "echo 'Latexmk, John Collins, 31 Jan. 2024. Version 4.83'"
STUBS = {
    "uv": "echo 'uv 0.11.5'",
    "latexmk": TEX,
    "pdflatex": "echo 'pdfTeX 3.141592653-2.6-1.40.25 (TeX Live 2023/Debian)'",
    "biber": "echo 'biber version: 2.19'",
    "pdftotext": "exit 0",
    "pdfinfo": "exit 0",
    "pdffonts": "exit 0",
    "pdftoppm": "exit 0",
    "strings": "exit 0",
    "soffice": "exit 0",
}


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    fake_chromium(home / "ms-playwright")
    return home


def doctor(tmp_path, home, stubs=STUBS, env=None, cwd=None):
    proc = run_doctor(DOCTOR, path=stub_dir(tmp_path, stubs), home=home, env=env, cwd=cwd)
    return proc, doctor_lines(proc)


def test_all_present_is_ready(tmp_path, home):
    proc, found = doctor(tmp_path, home)
    assert proc.returncode == 0, proc.stdout
    assert [k for k, v in found.items() if v[0] == "ok"] == [
        "uv",
        "latexmk",
        "pdflatex",
        "biber",
        "pdftotext",
        "pdfinfo",
        "pdffonts",
        "pdftoppm",
        "strings",
        "chromium",
        "pptx-renderer",
    ]
    assert found["node"][0] == "optional" and found["pptxgenjs"][0] == "n/a"


@pytest.mark.parametrize(
    "drop, os_name, fix",
    [
        ("latexmk", "debian", "fix: sudo apt install texlive-latex-extra latexmk"),
        ("latexmk", "macos", "fix: brew install --cask mactex-no-gui"),
        ("pdflatex", "debian", "fix: sudo apt install texlive-latex-extra latexmk"),
        ("pdffonts", "debian", "fix: sudo apt install poppler-utils"),
        ("pdftoppm", "macos", "fix: brew install poppler"),
        ("strings", "debian", "fix: sudo apt install binutils"),
        ("strings", "macos", "fix: xcode-select --install"),
        ("uv", "debian", "fix: curl -LsSf https://astral.sh/uv/install.sh | sh"),
    ],
)
def test_each_missing_required_tool_names_its_fix(tmp_path, home, drop, os_name, fix):
    stubs = {k: v for k, v in STUBS.items() if k != drop}
    proc, found = doctor(tmp_path, home, stubs, env={"TECHNE_DOCTOR_OS": os_name})
    assert proc.returncode == 1 and found[drop][0] == "missing"
    assert f"  {fix}" in proc.stdout.splitlines()


def test_missing_chromium_is_required(tmp_path, home):
    shutil.rmtree(home / "ms-playwright")
    proc, found = doctor(tmp_path, home)
    assert proc.returncode == 1 and found["chromium"][0] == "missing"
    assert "playwright==1.63.0 playwright install chromium" in proc.stdout


def test_a_stale_chromium_is_missing(tmp_path, home):
    shutil.rmtree(home / "ms-playwright")
    fake_chromium(home / "ms-playwright", revision="1234")
    proc, found = doctor(tmp_path, home)
    assert proc.returncode == 1 and found["chromium"][0] == "missing"
    assert "1243" in found["chromium"][1]


def test_optional_gaps_leave_it_ready(tmp_path, home):
    stubs = {k: v for k, v in STUBS.items() if k not in ("biber", "soffice")}
    proc, found = doctor(tmp_path, home, stubs)
    assert proc.returncode == 0
    assert found["biber"][0] == "optional" and found["pptx-renderer"][0] == "optional"
    assert "  fix: sudo apt install libreoffice-impress" in proc.stdout.splitlines()


def test_pptxgenjs_is_found_only_where_require_looks_from_the_current_folder(tmp_path, home):
    root = tmp_path / "npm-root"
    (root / "pptxgenjs").mkdir(parents=True)
    stubs = {**STUBS, "node": "echo v24.18.0", "npm": f"echo {root}"}
    deck = tmp_path / "deck"
    deck.mkdir()
    proc, found = doctor(tmp_path, home, stubs, cwd=deck)
    assert found["node"][0] == "ok" and found["pptxgenjs"][0] == "optional"
    assert str(deck) in found["pptxgenjs"][1]
    assert "  fix: npm install pptxgenjs" in proc.stdout.splitlines()
    (deck / "node_modules" / "pptxgenjs").mkdir(parents=True)
    _, found = doctor(tmp_path, home, stubs, cwd=deck)
    assert found["pptxgenjs"] == ("ok", str(deck / "node_modules" / "pptxgenjs"))
    sub = deck / "slides"
    sub.mkdir()
    _, found = doctor(tmp_path, home, stubs, cwd=sub)
    assert found["pptxgenjs"] == ("ok", str(deck / "node_modules" / "pptxgenjs"))


def load_doctor(monkeypatch):
    monkeypatch.syspath_prepend(str(DOCTOR_LIB.parent))
    gd = _load("graphe_doctor", DOCTOR)
    return gd, sys.modules["doctor_lib"]


# Review Focus 2, graphe's instance: a Windows LibreOffice on WSL's PATH renders nothing.
def test_windows_side_libreoffice_is_not_a_renderer(monkeypatch):
    gd, d = load_doctor(monkeypatch)
    windows = "/mnt/c/Program Files/LibreOffice/program/soffice"
    monkeypatch.setattr(d, "which", lambda name, *a, **k: windows if name == "soffice" else None)
    assert gd.pptx_renderer(d.Platform(d.DEBIAN, True)).status == d.OPTIONAL
    assert gd.pptx_renderer(d.Platform(d.DEBIAN, False)).status == d.OK


def test_powershell_exe_and_powerpoint_count_on_wsl(monkeypatch):
    gd, d = load_doctor(monkeypatch)
    shell = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    exe = "/mnt/c/Program Files/Microsoft Office/root/Office16/POWERPNT.EXE"
    monkeypatch.setattr(
        d, "which", lambda name, *a, **k: shell if name == "powershell.exe" else None
    )
    monkeypatch.setattr(d, "powerpoint_exes", lambda roots: [exe])
    got = gd.pptx_renderer(d.Platform(d.DEBIAN, True))
    assert got.status == d.OK and exe in got.detail
    monkeypatch.setattr(d, "powerpoint_exes", lambda roots: [])
    assert gd.pptx_renderer(d.Platform(d.DEBIAN, True)).status == d.OPTIONAL


def test_windows_side_npm_is_not_npm(monkeypatch):
    gd, d = load_doctor(monkeypatch)
    paths = {"node": "/usr/bin/node", "npm": "/mnt/c/Program Files/nodejs/npm"}
    monkeypatch.setattr(d, "which", lambda name, *a, **k: paths.get(name))
    got = gd.pptxgenjs(d.Platform(d.DEBIAN, True))
    assert got.status == d.NA and "npm" in got.detail


def test_running_the_doctor_leaves_no_bytecode(tmp_path, home):
    plugin = tmp_path / "plugin" / "graphe"
    shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns("__pycache__", "evals"))

    def listing():
        return sorted(p.relative_to(plugin).as_posix() for p in plugin.rglob("*"))

    before = listing()
    script = plugin / "skills" / "setup" / "scripts" / "doctor.py"
    path = stub_dir(tmp_path, STUBS)
    proc = run_doctor(script, path=path, home=home, env={"PYTHONDONTWRITEBYTECODE": ""})
    assert "Traceback" not in proc.stderr and proc.stdout
    assert listing() == before


def test_runbook_restates_only_fixes_from_the_table():
    lib = _load("graphe_doctor_lib_runbook", DOCTOR_LIB)
    known = {v for fix in lib.FIXES.values() for v in (fix.apt, fix.brew, fix.cmd) if v}
    text = AGENTS.read_text(encoding="utf-8")
    spans = re.findall(r"`([^`\n]+)`", text)
    quoted = [
        s
        for s in spans
        if re.match(r"(sudo apt install|brew install|xcode-select|uv python install|uv run|npm)", s)
    ]
    assert quoted
    assert [s for s in quoted if s not in known] == []
    assert lib.PLAYWRIGHT_PIN.split("==")[1] in text


def test_published_text_has_no_email_or_machine_path():
    for path in (AGENTS, DOCTOR.parent.parent / "SKILL.md"):
        text = path.read_text(encoding="utf-8")
        assert not EMAIL.search(text) and not MACHINE_PATH.search(text), path
        assert "—" not in text, path


def agents_rows():
    rows = {}
    for line in AGENTS.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| `") and len(cells) == 3:
            rows[cells[0]] = cells[2]
    return rows


def test_runbook_gives_every_sudo_and_browser_fix_to_the_user():
    text = AGENTS.read_text(encoding="utf-8")
    assert "contains `sudo`" in text
    rows = agents_rows()
    lib = _load("graphe_doctor_lib_rows", DOCTOR_LIB)

    def row(name):
        return next(cell for names, cell in rows.items() if f"`{name}`" in names)

    by_row = {
        "uv": "uv",
        "latexmk": "latex",
        "biber": "biber",
        "pdftotext": "poppler",
        "strings": "strings",
        "pptx-renderer": "libreoffice",
        "node": "node",
        "chromium": "chromium",
        "pptxgenjs": "pptxgenjs",
    }
    for name, key in by_row.items():
        fix = lib.FIXES[key]
        brew = fix.brew or ""
        if "sudo" in (fix.apt or "") and brew.startswith("brew install ") and "--cask" not in brew:
            assert "On Debian or Ubuntu the user runs the fix line with `!`" in row(name), name
            assert "On macOS you may run it after the user approves" in row(name), name
        elif "sudo" in (fix.apt or "") or "xcode-select" in brew:
            assert "The user runs the fix line with `!`" in row(name), name
        else:
            assert "after the user approves" in row(name), name
    assert f"`{lib.CHROMIUM_DEPS}` after `!`" in row("chromium")
