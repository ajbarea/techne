"""doctor_lib: line format, PATH lookup, version parsing, platform detection and fixes.

In-process cases load the techne source. The subprocess cases run a small driver on
HOOK_PYTHON, which `make test-hooks-oldest` points at python3 3.9, so the shared file is held
to the oldest python3 the doctors run on.
"""

from __future__ import annotations

import os
import re
import subprocess
import time

import pytest
from conftest import DOCTOR_LIB, DOCTOR_LINE, HOOK_PYTHON, ROOT, _load, fake_chromium, stub_dir


@pytest.fixture(scope="module")
def dl():
    return _load("techne_doctor_lib", DOCTOR_LIB)


@pytest.fixture
def deb(dl):
    return dl.Platform(dl.DEBIAN, False)


# ------------------------------------------------------------------ render --


def test_render_prints_one_line_per_check_and_fixes_only_for_gaps(dl):
    checks = [
        dl.Check(dl.OK, "git", "2.43.0 at /usr/bin/git"),
        dl.Check(dl.MISSING, "gh", "not on PATH", ("fix: brew install gh",)),
        dl.Check(dl.OPTIONAL, "chromium", "no Chromium", ("fix: x",)),
        dl.Check(dl.NA, "lsof", "macOS only", ("fix: never shown",)),
    ]
    assert dl.render(checks).splitlines() == [
        "ok git: 2.43.0 at /usr/bin/git",
        "missing gh: not on PATH",
        "  fix: brew install gh",
        "optional chromium: no Chromium",
        "  fix: x",
        "n/a lsof: macOS only",
        "result: missing gh",
    ]
    assert dl.exit_code(checks) == 1
    assert dl.exit_code(checks[2:]) == 0
    assert dl.render(checks[2:]).splitlines()[-1] == "result: ready"


def test_guarded_turns_an_exception_into_a_line(dl):
    def boom():
        raise RuntimeError("bad")

    assert dl.guarded("x", True, boom) == dl.Check(
        dl.MISSING, "x", "could not check: RuntimeError: bad"
    )
    assert dl.guarded("x", False, boom).status == dl.OPTIONAL


# ------------------------------------------------------------------- which --


def test_which_searches_only_the_given_path(dl, tmp_path):
    path = stub_dir(tmp_path, {"tool": "exit 0"})
    assert dl.which("tool", path) == os.path.join(path, "tool")
    assert dl.which("sh", path) is None
    assert dl.which("tool", "") is None


def test_which_with_path_unset_finds_nothing(dl, monkeypatch):
    monkeypatch.delenv("PATH", raising=False)
    assert dl.which("sh") is None


def test_which_skips_directories_and_non_executables(dl, tmp_path):
    (tmp_path / "dir").mkdir()
    (tmp_path / "plain").write_text("x")
    assert dl.which("dir", str(tmp_path)) is None
    assert dl.which("plain", str(tmp_path)) is None


def test_which_tries_pathext_on_windows(dl, tmp_path):
    exe = tmp_path / "git.EXE"
    exe.write_text("")
    exe.chmod(0o755)
    found = dl.which("git", str(tmp_path), sysname="win32", pathext=".COM;.EXE")
    assert found == str(exe)


# ----------------------------------------------------------------- version --


@pytest.mark.parametrize(
    "text, want",
    [
        ("git version 2.43.0\n", (2, 43, 0)),
        ("gh version 2.45.0 (2025-07-18 Ubuntu 2.45.0-1ubuntu0.3)\nhttps://x/v2.45.0", (2, 45, 0)),
        ("uv 0.11.5 (x86_64-unknown-linux-gnu)", (0, 11, 5)),
        ("Latexmk, John Collins, 31 Jan. 2024. Version 4.83", (4, 83)),
        ("pdfTeX 3.141592653-2.6-1.40.25 (TeX Live 2023/Debian)", (3, 141592653)),
        (
            "pdfTeX 3.141592653-2.6-1.40.25 (TeX Live 2023/Debian)\n"
            "kpathsea version 6.3.5\nCopyright 2023 Han The Thanh",
            (3, 141592653),
        ),
        ("tmux 3.3a", (3, 3)),
        ("tmux next-3.5", (3, 5)),
        ("2.1.296 (Claude Code)", (2, 1, 296)),
        ("3.9.6", (3, 9, 6)),
        ("", None),
        ("command not found", None),
        ("version: unknown", None),
    ],
)
def test_parse_version(dl, text, want):
    assert dl.parse_version(text) == want


# ---------------------------------------------------------------- platform --


def _release(tmp_path, body):
    path = tmp_path / "os-release"
    path.write_text(body)
    return path


@pytest.mark.parametrize(
    "body, want",
    [
        ("ID=ubuntu\nID_LIKE=debian\n", "debian"),
        ("ID=debian\n", "debian"),
        ('ID=pop\nID_LIKE="ubuntu debian"\n', "debian"),
        ("ID=fedora\n", "other"),
        ("", "other"),
    ],
)
def test_linux_distros(dl, tmp_path, body, want):
    got = dl.detect_platform({}, "linux", _release(tmp_path, body), tmp_path / "none")
    assert got.os == want


def test_macos_windows_and_overrides(dl, tmp_path):
    none = tmp_path / "none"
    assert dl.detect_platform({}, "darwin", none, none) == dl.Platform(dl.MACOS, False)
    assert dl.detect_platform({}, "win32", none, none) == dl.Platform(dl.OTHER, False)
    forced = {"TECHNE_DOCTOR_OS": "macos", "TECHNE_DOCTOR_WSL": "1"}
    assert dl.detect_platform(forced, "linux", none, none) == dl.Platform(dl.MACOS, True)


def test_wsl_from_env_or_kernel(dl, tmp_path):
    none = tmp_path / "none"
    kernel = tmp_path / "osrelease"
    kernel.write_text("6.6.87.2-microsoft-standard-WSL2\n")
    assert dl.detect_platform({"WSL_DISTRO_NAME": "Ubuntu"}, "linux", none, none).wsl
    assert dl.detect_platform({}, "linux", none, kernel).wsl
    assert not dl.detect_platform({}, "linux", none, none).wsl
    assert not dl.detect_platform({"WSL_DISTRO_NAME": "x"}, "darwin", none, none).wsl


# ------------------------------------------------------------------- fixes --


def test_fix_lines_per_platform(dl):
    fix = dl.FIXES["tmux"]
    assert dl.fix_lines(dl.Platform(dl.DEBIAN, False), fix) == ("fix: sudo apt install tmux",)
    assert dl.fix_lines(dl.Platform(dl.MACOS, False), fix) == ("fix: brew install tmux",)
    assert dl.fix_lines(dl.Platform(dl.OTHER, False), fix) == (
        "fix (Debian/Ubuntu): sudo apt install tmux",
        "fix (macOS): brew install tmux",
    )
    for os_name in (dl.DEBIAN, dl.MACOS, dl.OTHER):
        assert dl.fix_lines(dl.Platform(os_name, False), dl.FIXES["uv"]) == (
            "fix: curl -LsSf https://astral.sh/uv/install.sh | sh",
        )


def test_exact_fix_commands(dl):
    f = dl.FIXES
    assert f["latex"] == dl.Fix(
        apt="sudo apt install texlive-latex-extra latexmk",
        brew="brew install --cask mactex-no-gui",
    )
    assert f["poppler"] == dl.Fix(apt="sudo apt install poppler-utils", brew="brew install poppler")
    assert f["strings"] == dl.Fix(apt="sudo apt install binutils", brew="xcode-select --install")
    assert f["texcount"] == dl.Fix(
        apt="sudo apt install texlive-extra-utils", brew="brew install --cask mactex-no-gui"
    )
    assert f["biber"] == dl.Fix(apt="sudo apt install biber", brew="brew install biber")
    assert f["gh"].brew == "brew install gh"
    assert f["gh"].apt.endswith("sudo apt update && sudo apt install gh -y")
    assert "https://cli.github.com/packages stable main" in f["gh"].apt
    assert f["chromium"].cmd == (
        "uv run --no-project --with playwright==1.63.0 playwright install chromium"
    )


def test_missing_message_groups_tools_by_fix(dl, deb):
    msg = dl.missing_message(
        [("latexmk", "latex"), ("pdftotext", "poppler"), ("pdfinfo", "poppler")],
        "/graphe:setup",
        deb,
    )
    assert msg.splitlines() == [
        "latexmk not found on PATH.",
        "  fix: sudo apt install texlive-latex-extra latexmk",
        "pdftotext, pdfinfo not found on PATH.",
        "  fix: sudo apt install poppler-utils",
        "Run /graphe:setup to check everything else this plugin needs.",
    ]
    one = dl.missing_message([("pdftotext", "poppler")], "/graphe:setup", deb, one_line=True)
    assert "\n" not in one and "fix: sudo apt install poppler-utils" in one


# -------------------------------------------------------------------- tool --


def test_tool_statuses(dl, deb, tmp_path, monkeypatch):
    path = stub_dir(
        tmp_path,
        {
            "new": "echo 'thing 3.12.3'",
            "old": "echo 'thing 3.10.12'",
            "quiet": "exit 0",
            "shim": "echo 'xcrun: error: invalid active developer path' >&2; exit 1",
        },
    )
    monkeypatch.setenv("PATH", path)
    fix = dl.FIXES["python3"]
    v = ("--version",)
    assert dl.tool("absent", platform=deb, fix=fix).status == dl.MISSING
    assert dl.tool("absent", platform=deb, fix=fix, required=False).status == dl.OPTIONAL
    assert dl.tool("quiet", platform=deb, fix=fix) == dl.Check(
        dl.OK, "quiet", os.path.join(path, "quiet")
    )
    new = dl.tool("new", platform=deb, fix=fix, version_argv=v, minimum=(3, 11))
    assert new.status == dl.OK and new.detail.startswith("3.12.3 at ")
    old = dl.tool("old", platform=deb, fix=fix, version_argv=v, minimum=(3, 11))
    assert old.status == dl.MISSING and "3.10.12" in old.detail and "need 3.11" in old.detail
    assert old.fixes == ("fix: uv python install --default 3.12 && uv python update-shell",)
    unread = dl.tool("quiet", platform=deb, fix=fix, version_argv=v)
    assert unread.status == dl.OK and "version not read" in unread.detail
    assert dl.tool("quiet", platform=deb, fix=fix, version_argv=v, minimum=(3, 9)).status == (
        dl.MISSING
    )
    assert dl.tool("shim", platform=deb, fix=fix, version_argv=v).status == dl.MISSING


# Review Focus 2: on WSL, Windows' PATH is appended; a Linux tool found only there is absent.
def test_wsl_windows_side_binary_counts_as_absent(dl, monkeypatch):
    wsl = dl.Platform(dl.DEBIAN, True)
    monkeypatch.setattr(dl, "which", lambda *_a, **_k: "/mnt/c/Program Files/nodejs/npm")
    got = dl.tool("npm", platform=wsl, fix=dl.FIXES["node"], required=False)
    assert got.status == dl.OPTIONAL and "Windows copy" in got.detail
    assert got.fixes == ("fix: sudo apt install nodejs npm",)
    ok = dl.tool("npm", platform=wsl, fix=dl.FIXES["node"], windows_ok=True)
    assert ok.status == dl.OK
    native = dl.tool("npm", platform=dl.Platform(dl.DEBIAN, False), fix=dl.FIXES["node"])
    assert native.status == dl.OK


def test_chromium_is_ok_only_for_the_expected_runnable_build(dl, tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert dl.chromium(required=True).status == dl.MISSING
    assert dl.chromium(required=False).status == dl.OPTIONAL
    exe = fake_chromium(tmp_path)
    got = dl.chromium(required=True)
    assert got.status == dl.OK and "Chromium 150" in got.detail and str(exe) in got.detail


def test_stale_partial_or_broken_chromium_is_missing(dl, tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    fake_chromium(tmp_path, revision="1234")  # a build for another Playwright
    stale = dl.chromium(required=True)
    assert stale.status == dl.MISSING and "1243" in stale.detail
    assert stale.fixes == (f"fix: {dl.CHROMIUM_INSTALL}",)
    (tmp_path / "chromium_headless_shell-1243").mkdir()  # a download that stopped early
    assert dl.chromium(required=True).status == dl.MISSING
    fake_chromium(
        tmp_path, body="echo 'error while loading shared libraries: libnss3.so' >&2; exit 127"
    )
    broken = dl.chromium(required=True)
    assert broken.status == dl.MISSING and "libnss3" in broken.detail
    assert broken.fixes == (f"fix: {dl.CHROMIUM_INSTALL}", f"fix: {dl.CHROMIUM_DEPS}")


def test_playwright_root_per_platform(dl, tmp_path):
    home = {"HOME": str(tmp_path)}
    assert dl.playwright_root(home, "linux") == tmp_path / ".cache" / "ms-playwright"
    assert dl.playwright_root({**home, "XDG_CACHE_HOME": "/x"}, "linux") == (
        dl.Path("/x") / "ms-playwright"
    )
    assert dl.playwright_root(home, "darwin") == (tmp_path / "Library" / "Caches" / "ms-playwright")
    assert dl.playwright_root({"PLAYWRIGHT_BROWSERS_PATH": "0"}, "linux") is None


def test_powerpoint_is_found_in_both_install_layouts(dl, tmp_path):
    for layout in (("root", "Office16"), ("Office16",)):
        root = tmp_path / "-".join(layout)
        exe = root.joinpath("Microsoft Office", *layout, "POWERPNT.EXE")
        exe.parent.mkdir(parents=True)
        exe.touch()
        assert dl.powerpoint_exes([str(root)]) == [str(exe)]


# ------------------------------------------------- python3 3.9 subprocess --

DRIVER = """
import sys
sys.path.insert(0, sys.argv[1])
import doctor_lib as d
p = d.detect_platform()
fix = d.Fix(apt="sudo apt install x")
names = sys.argv[2:]
checks = [d.tool(n, platform=p, fix=fix, version_argv=("--version",), timeout=1.0) for n in names]
print(d.render(checks))
"""

ODD = {
    "empty": "exit 0",
    "junk": "echo 'no digits here'",
    "binary": "printf '\\377\\376\\000x'",
    "stderr": "echo 'thing 1.2.3' >&2",
    "fails": "echo boom >&2; exit 3",
    "hangs": "/bin/sleep 30",
    "orphan": "(/bin/sleep 30 &); exit 0",
}


# Review Focus 1: odd --version output never tracebacks and never hangs the doctor.
def test_odd_version_output_never_tracebacks_and_never_hangs(tmp_path):
    path = stub_dir(tmp_path, ODD)
    driver = tmp_path / "drive.py"
    driver.write_text(DRIVER)
    start = time.monotonic()
    proc = subprocess.run(
        [HOOK_PYTHON, str(driver), str(DOCTOR_LIB.parent), *ODD],
        env={
            "PATH": path,
            "TECHNE_DOCTOR_OS": "debian",
            "TECHNE_DOCTOR_WSL": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert time.monotonic() - start < 20
    assert "Traceback" not in proc.stderr, proc.stderr
    lines = proc.stdout.splitlines()
    assert all(DOCTOR_LINE.match(line) for line in lines), lines
    status = {
        line.split(" ", 1)[1].split(":", 1)[0]: line.split(" ", 1)[0]
        for line in lines
        if not line.startswith(("  ", "result: "))
    }
    assert status == {
        "empty": "ok",
        "junk": "ok",
        "binary": "ok",
        "stderr": "ok",
        "fails": "missing",
        "hangs": "missing",
        "orphan": "missing",
    }


def test_imports_on_the_oldest_python(tmp_path):
    proc = subprocess.run(
        [
            HOOK_PYTHON,
            "-c",
            f"import sys; sys.path.insert(0, {str(DOCTOR_LIB.parent)!r}); import doctor_lib",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------- pins --


def test_playwright_pin_matches_every_caller(dl):
    pin = dl.PLAYWRIGHT_PIN
    assert pin == "playwright==1.63.0"
    assert f"--with {pin}" in (ROOT / "Makefile").read_text()
    assert f"--with {pin}" in (ROOT / ".github" / "workflows" / "validate.yml").read_text()
    slides = ROOT / "plugins" / "graphe" / "skills" / "slides" / "scripts" / "slides.py"
    assert f'PLAYWRIGHT = "{pin}"' in slides.read_text()
    docs_site = ROOT / "plugins" / "techne" / "skills" / "docs-site"
    callers = [*docs_site.rglob("*"), ROOT / "docs" / "skills" / "docs-site.md"]
    callers = [p for p in callers if p.is_file() and "__pycache__" not in p.parts]
    assert any("--with playwright" in p.read_text() for p in callers)
    for path in callers:
        assert not re.search(r"--with playwright(?!==)", path.read_text()), path


# ------------------------------------------------- shared helpers, rulings --


def test_native_which_rejects_a_windows_copy_only_on_wsl(dl, monkeypatch):
    monkeypatch.setattr(dl, "which", lambda *_a, **_k: "/mnt/c/Program Files/x/soffice.exe")
    assert dl.native_which("soffice", dl.Platform(dl.DEBIAN, True)) is None
    assert dl.native_which("soffice", dl.Platform(dl.DEBIAN, False)).endswith("soffice.exe")
    monkeypatch.setattr(dl, "which", lambda *_a, **_k: "/usr/bin/soffice")
    assert dl.native_which("soffice", dl.Platform(dl.DEBIAN, True)) == "/usr/bin/soffice"
    monkeypatch.setattr(dl, "which", lambda *_a, **_k: None)
    assert dl.native_which("soffice", dl.Platform(dl.DEBIAN, True)) is None


def test_program_runs_tool_through_guarded(dl, deb, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", stub_dir(tmp_path, {"thing": "echo 'thing 1.2.3'"}))
    got = dl.program(deb, "thing", "tmux", version_argv=("--version",))
    assert got.status == dl.OK and got.name == "thing" and got.detail.startswith("1.2.3 at ")
    assert dl.program(deb, "absent", "tmux", required=False).status == dl.OPTIONAL
    assert dl.program(deb, "absent", "tmux").fixes == ("fix: sudo apt install tmux",)
    assert dl.program(deb, "thing", "no-such-key").status == dl.MISSING  # a bug, not a traceback


def test_exit_missing_exits_with_the_message(dl, deb):
    with pytest.raises(SystemExit) as caught:
        dl.exit_missing([("tmux", "tmux")], "/techne:setup", deb)
    assert caught.value.code == dl.missing_message([("tmux", "tmux")], "/techne:setup", deb)


def test_config_docs_url_is_the_published_page(dl):
    assert dl.CONFIG_DOCS == "https://ajbarea.github.io/techne/configuration/"


# A doctor sets dont_write_bytecode before importing doctor_lib, so running it from an
# installed plugin leaves no __pycache__ in the plugin cache.
def test_a_doctor_importing_doctor_lib_writes_no_bytecode(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "_shared").mkdir(parents=True)
    (plugin / "_shared" / "doctor_lib.py").write_text(DOCTOR_LIB.read_text())
    doctor = plugin / "doctor.py"
    doctor.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.dont_write_bytecode = True\n"
        "sys.path.insert(0, str(Path(__file__).parent / '_shared'))\n"
        "import doctor_lib\n"
        "print(doctor_lib.render([]))\n"
    )
    before = sorted(p.relative_to(plugin) for p in plugin.rglob("*"))
    proc = subprocess.run(
        [HOOK_PYTHON, str(doctor)],
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert sorted(p.relative_to(plugin) for p in plugin.rglob("*")) == before
    assert not list(plugin.rglob("__pycache__"))


def test_a_version_in_the_output_of_a_failed_run_is_not_a_version(dl, deb, tmp_path, monkeypatch):
    glibc = (
        "echo \"node: libc.so.6: version 'GLIBC_2.28' not found (required by node)\" >&2; exit 1"
    )
    monkeypatch.setenv("PATH", stub_dir(tmp_path, {"node": glibc}))
    got = dl.tool("node", platform=deb, fix=dl.FIXES["node"], version_argv=("--version",))
    assert got.status == dl.MISSING and "ok" not in got.detail.split()[:1]


def test_run_kills_the_grandchild_it_leaves_behind(dl, tmp_path):
    pidfile = tmp_path / "pid"
    stub = stub_dir(tmp_path, {"t": f'/bin/sleep 30 &\necho $! > "{pidfile}"\nexit 0'})
    code, _ = dl.run([os.path.join(stub, "t")], timeout=1.0)
    pid = int(pidfile.read_text())
    try:
        assert code is None
        for _ in range(40):  # SIGKILL lands at once; a zombie lingers until init reaps it
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            if "Z" in _proc_state(pid):
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"grandchild {pid} is still running")
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def _proc_state(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0]
    except OSError:
        return "Z"


def test_render_keeps_each_field_on_one_line(dl):
    bad = dl.Check(dl.MISSING, "x", "line1\nok sneaky: all good\x1b[31m", ("fix: a\nb",))
    lines = dl.render([bad]).splitlines()
    assert len(lines) == 3 and "\x1b" not in lines[0]
    assert all(DOCTOR_LINE.match(line) for line in lines), lines
