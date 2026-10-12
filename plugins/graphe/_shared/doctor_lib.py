"""Shared helpers for the plugin setup doctors.

A doctor runs on the system python3 (3.9 or newer, standard library only), never through uv,
so it can report a missing uv. It installs nothing. Each check prints one line,
`ok|missing|optional|n/a <name>: <detail>`, and a missing or optional one adds the commands
that fix it. plugins/techne/_shared/ holds the source; `make guards` keeps each plugin's copy
identical. Skill scripts import `missing_message` so their errors name the same commands.
"""

from __future__ import annotations

import glob
import os
import re
import signal
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple, TextIO

OK, MISSING, OPTIONAL, NA = "ok", "missing", "optional", "n/a"
DEBIAN, MACOS, OTHER = "debian", "macos", "other"
LABELS = {DEBIAN: "Debian/Ubuntu", MACOS: "macOS"}

UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh"
PLAYWRIGHT_PIN = "playwright==1.63.0"
CHROMIUM_INSTALL = f"uv run --no-project --with {PLAYWRIGHT_PIN} playwright install chromium"
CLAUDE_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"
# cli.github.com's apt instructions (docs/install_linux.md in cli/cli), on one line.
GH_APT = (
    "(type -p wget >/dev/null || (sudo apt update && sudo apt install wget -y))"
    " && sudo mkdir -p -m 755 /etc/apt/keyrings"
    " && out=$(mktemp)"
    " && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg"
    " && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null"
    " && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg"
    " && sudo mkdir -p -m 755 /etc/apt/sources.list.d"
    ' && echo "deb [arch=$(dpkg --print-architecture)'
    " signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg]"
    ' https://cli.github.com/packages stable main"'
    " | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null"
    " && sudo apt update && sudo apt install gh -y"
)
# Prints the interpreter's version even where `--version` goes to stderr (Python 2).
PYTHON_VERSION_ARGV = ("-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])")
DEFAULT_TIMEOUT = 10.0
CONFIG_DOCS = "https://ajbarea.github.io/techne/configuration/"


class Fix(NamedTuple):
    apt: str | None = None
    brew: str | None = None
    cmd: str | None = None


# research(2026-10): package names checked on packages.debian.org (trixie) and
# packages.ubuntu.com (noble), casks and formulae on formulae.brew.sh, the gh line on
# cli.github.com, uv on docs.astral.sh, Claude Code on code.claude.com/docs/en/setup.
FIXES = {
    "git": Fix(apt="sudo apt install git", brew="xcode-select --install"),
    "gh": Fix(apt=GH_APT, brew="brew install gh"),
    "uv": Fix(cmd=UV_INSTALL),
    "python3": Fix(
        apt="sudo apt install python3",
        brew="brew install python",
        cmd="uv python install --default 3.12",
    ),
    "tmux": Fix(apt="sudo apt install tmux", brew="brew install tmux"),
    "latex": Fix(
        apt="sudo apt install texlive-latex-extra latexmk",
        brew="brew install --cask mactex-no-gui",
    ),
    "biber": Fix(apt="sudo apt install biber", brew="brew install biber"),
    "poppler": Fix(apt="sudo apt install poppler-utils", brew="brew install poppler"),
    "strings": Fix(apt="sudo apt install binutils", brew="xcode-select --install"),
    "chromium": Fix(cmd=CHROMIUM_INSTALL),
    "libreoffice": Fix(
        apt="sudo apt install libreoffice-impress", brew="brew install --cask libreoffice"
    ),
    "node": Fix(apt="sudo apt install nodejs npm", brew="brew install node"),
    "pptxgenjs": Fix(cmd="npm install -g pptxgenjs"),
    "claude": Fix(cmd=CLAUDE_INSTALL),
    "claude-update": Fix(cmd="claude update"),
}


class Check(NamedTuple):
    status: str
    name: str
    detail: str
    fixes: tuple[str, ...] = ()


class Platform(NamedTuple):
    os: str
    wsl: bool


_VERSION = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?:\.(\d+))?")
_WINDOWS_MOUNT = re.compile(r"^/mnt/[a-z]/")


def which(
    name: str, path: str | None = None, sysname: str | None = None, pathext: str | None = None
) -> str | None:
    """Resolve `name` on PATH, or on `path` when given.

    An unset or empty PATH finds nothing; shutil.which would fall back to os.defpath and
    find the /usr/bin tools a stub PATH left out.
    """
    search = os.environ.get("PATH", "") if path is None else path
    platform_name = sys.platform if sysname is None else sysname
    windows = platform_name == "win32"
    exts = [""]
    if windows and not os.path.splitext(name)[1]:
        raw = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD") if pathext is None else pathext
        exts = [ext for ext in raw.split(";") if ext]
    for folder in search.split(";" if windows else ":"):
        if not folder:
            continue
        for ext in exts:
            candidate = os.path.join(folder, name + ext)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def windows_side(path: str) -> bool:
    """True for a file on a Windows drive as WSL mounts it."""
    return bool(_WINDOWS_MOUNT.match(path))


def native_which(name: str, platform: Platform, path: str | None = None) -> str | None:
    """`which`, except that on WSL a copy found only under /mnt/<drive>/ (Windows' PATH is
    appended there) counts as absent."""
    found = which(name, path)
    return None if found and platform.wsl and windows_side(found) else found


def first_line(text: str, limit: int = 100) -> str:
    for line in text.splitlines():
        if line.strip():
            line = line.strip()
            return line if len(line) <= limit else line[: limit - 3] + "..."
    return ""


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, AttributeError):  # AttributeError: Windows has no killpg
        proc.kill()


def run(argv: Sequence[str], timeout: float = DEFAULT_TIMEOUT) -> tuple[int | None, str]:
    """(exit code, stdout and stderr merged). The code is None when the program could not
    start or ran past `timeout`; its own process group is killed so a child it left holding
    the pipe cannot hang the doctor."""
    try:
        proc = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        return None, str(exc)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        return None, f"timed out after {timeout:g}s"
    return proc.returncode, out.decode("utf-8", "replace")


def parse_version(text: str) -> tuple[int, ...] | None:
    """The first dotted number, preferring one after the word "version"."""
    lowered = text.lower()
    at = lowered.find("version")
    for chunk in (text[at:], text) if at >= 0 else (text,):
        m = _VERSION.search(chunk)
        if m:
            return tuple(int(g) for g in m.groups() if g is not None)
    return None


def fmt_version(version: Sequence[int]) -> str:
    return ".".join(str(part) for part in version)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _debian_like(os_release: Path) -> bool:
    ids: set[str] = set()
    for line in _read(os_release).splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("ID", "ID_LIKE"):
            ids.update(value.strip().strip("'\"").lower().split())
    return bool(ids & {"debian", "ubuntu"})


def detect_platform(
    environ: Mapping[str, str] | None = None,
    sysname: str | None = None,
    os_release: Path | None = None,
    kernel_release: Path | None = None,
) -> Platform:
    """Which fix lines apply. TECHNE_DOCTOR_OS (debian, macos, other) and TECHNE_DOCTOR_WSL
    (1 or 0) override detection, for tests."""
    env = os.environ if environ is None else environ
    platform_name = sys.platform if sysname is None else sysname
    forced = env.get("TECHNE_DOCTOR_OS")
    if forced in (DEBIAN, MACOS, OTHER):
        os_name = forced
    elif platform_name == "darwin":
        os_name = MACOS
    elif platform_name.startswith("linux") and _debian_like(os_release or Path("/etc/os-release")):
        os_name = DEBIAN
    else:
        os_name = OTHER
    forced_wsl = env.get("TECHNE_DOCTOR_WSL")
    if forced_wsl in ("0", "1"):
        wsl = forced_wsl == "1"
    else:
        kernel = _read(kernel_release or Path("/proc/sys/kernel/osrelease")).lower()
        wsl = platform_name.startswith("linux") and (
            bool(env.get("WSL_DISTRO_NAME")) or "microsoft" in kernel
        )
    return Platform(os_name, wsl)


def fix_lines(platform: Platform, fix: Fix) -> tuple[str, ...]:
    """The fix lines for this platform: its package manager's line, then any command that
    works everywhere. An unrecognized platform gets both labelled lines."""
    lines = []
    if platform.os == DEBIAN and fix.apt:
        lines.append(f"fix: {fix.apt}")
    elif platform.os == MACOS and fix.brew:
        lines.append(f"fix: {fix.brew}")
    elif platform.os == OTHER:
        if fix.apt:
            lines.append(f"fix ({LABELS[DEBIAN]}): {fix.apt}")
        if fix.brew:
            lines.append(f"fix ({LABELS[MACOS]}): {fix.brew}")
    if fix.cmd:
        lines.append(f"fix: {fix.cmd}")
    return tuple(lines)


def tool(
    name: str,
    *,
    platform: Platform,
    fix: Fix,
    required: bool = True,
    version_argv: Sequence[str] | None = None,
    minimum: Sequence[int] | None = None,
    why: str = "",
    windows_ok: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
) -> Check:
    """Check one program on PATH, and its version when `version_argv` is given.

    A version that cannot be read is fine unless the program also failed or a minimum is
    set: a shim that only says "install the developer tools" exits non-zero.
    """
    shown = name
    absent = MISSING if required else OPTIONAL
    fixes = fix_lines(platform, fix)
    suffix = f" ({why})" if why else ""
    found = which(name)
    if not found:
        return Check(absent, shown, f"not on PATH{suffix}", fixes)
    if platform.wsl and not windows_ok and windows_side(found):
        detail = f"only the Windows copy at {found} is on PATH; install the Linux one{suffix}"
        return Check(absent, shown, detail, fixes)
    if version_argv is None:
        return Check(OK, shown, found)
    code, out = run([found, *version_argv], timeout=timeout)
    version = parse_version(out) if code is not None else None
    if version is None:
        said = first_line(out)
        if code == 0 and minimum is None:
            return Check(OK, shown, f"{found} (version not read)")
        need = f"; need {fmt_version(minimum)} or newer" if minimum else ""
        why_not = said or f"exit {code}"
        return Check(absent, shown, f"{found} gave no version ({why_not}){need}{suffix}", fixes)
    if minimum is not None and version < tuple(minimum):
        detail = f"{fmt_version(version)} at {found}; need {fmt_version(minimum)} or newer"
        return Check(absent, shown, f"{detail}{suffix}", fixes)
    return Check(OK, shown, f"{fmt_version(version)} at {found}")


def program(platform: Platform, name: str, fix: str, **options) -> Check:
    """`tool` for the program `name`, with the FIXES entry `fix`, guarded against a bug in the
    check. `options` are the other `tool` keywords."""
    required = options.get("required", True)
    return guarded(name, required, lambda: tool(name, platform=platform, fix=FIXES[fix], **options))


def playwright_root(
    environ: Mapping[str, str] | None = None, sysname: str | None = None
) -> Path | None:
    """Where `playwright install` puts browsers; None when PLAYWRIGHT_BROWSERS_PATH=0 keeps
    them inside the playwright package."""
    env = os.environ if environ is None else environ
    platform_name = sys.platform if sysname is None else sysname
    custom = env.get("PLAYWRIGHT_BROWSERS_PATH")
    if custom == "0":
        return None
    if custom:
        return Path(custom)
    home = Path(env.get("HOME") or env.get("USERPROFILE") or str(Path.home()))
    if platform_name == "darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    if platform_name == "win32":
        return Path(env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")) / "ms-playwright"
    return Path(env.get("XDG_CACHE_HOME") or str(home / ".cache")) / "ms-playwright"


def chromium(*, required: bool, why: str = "") -> Check:
    absent = MISSING if required else OPTIONAL
    suffix = f" ({why})" if why else ""
    root = playwright_root()
    if root is None:
        detail = "PLAYWRIGHT_BROWSERS_PATH=0 keeps Chromium where this check cannot see it"
        return Check(
            absent,
            "chromium",
            detail,
            (f"fix: unset PLAYWRIGHT_BROWSERS_PATH && {CHROMIUM_INSTALL}",),
        )
    builds = sorted(p.name for p in root.glob("chromium*-*") if p.is_dir()) if root.is_dir() else []
    if builds:
        return Check(OK, "chromium", f"{', '.join(builds)} in {root}")
    return Check(
        absent, "chromium", f"no Chromium in {root}{suffix}", (f"fix: {CHROMIUM_INSTALL}",)
    )


def office_roots(
    wsl: bool, environ: Mapping[str, str] | None = None, sysname: str | None = None
) -> list[str]:
    """The Program Files folders PowerPoint installs under, as this platform sees them."""
    env = os.environ if environ is None else environ
    if (sys.platform if sysname is None else sysname) == "win32":
        return [env.get("ProgramFiles", ""), env.get("ProgramFiles(x86)", "")]
    if wsl:
        return ["/mnt/c/Program Files", "/mnt/c/Program Files (x86)"]
    return []


def powerpoint_exes(roots: Sequence[str]) -> list[str]:
    """Click-to-Run installs under root/Office16, MSI and volume licences under Office16."""
    layouts = (("root", "Office*"), ("Office*",))
    return [
        g
        for r in roots
        if r
        for layout in layouts
        for g in glob.glob(os.path.join(r, "Microsoft Office", *layout, "POWERPNT.EXE"))
    ]


def guarded(name: str, required: bool, fn: Callable[[], Check]) -> Check:
    """Run one check; a bug in it becomes a line, never a traceback."""
    try:
        return fn()
    except Exception as exc:
        status = MISSING if required else OPTIONAL
        return Check(status, name, f"could not check: {type(exc).__name__}: {exc}")


def render(checks: Iterable[Check]) -> str:
    found = list(checks)
    lines = []
    for check in found:
        lines.append(f"{check.status} {check.name}: {check.detail}")
        if check.status in (MISSING, OPTIONAL):
            lines.extend(f"  {fix}" for fix in check.fixes)
    missing = [check.name for check in found if check.status == MISSING]
    lines.append("result: missing " + ", ".join(missing) if missing else "result: ready")
    return "\n".join(lines)


def exit_code(checks: Iterable[Check]) -> int:
    return 1 if any(check.status == MISSING for check in checks) else 0


def report(checks: Iterable[Check], stream: TextIO | None = None) -> int:
    found = list(checks)
    print(render(found), file=stream or sys.stdout)
    return exit_code(found)


def missing_message(
    tools: Sequence[tuple[str, str]],
    setup: str,
    platform: Platform | None = None,
    one_line: bool = False,
) -> str:
    """Name each missing program with its fix, once per fix, then the setup skill."""
    plat = platform or detect_platform()
    by_fix: dict[str, list[str]] = {}
    for name, key in tools:
        by_fix.setdefault(key, []).append(name)
    lines = []
    for key, names in by_fix.items():
        lines.append(f"{', '.join(names)} not found on PATH.")
        lines.extend(f"  {line}" for line in fix_lines(plat, FIXES[key]))
    lines.append(f"Run {setup} to check everything else this plugin needs.")
    return " ".join(line.strip() for line in lines) if one_line else "\n".join(lines)


def exit_missing(
    tools: Sequence[tuple[str, str]], setup: str, platform: Platform | None = None
) -> None:
    """Stop a skill script with the `missing_message` for `tools`."""
    sys.exit(missing_message(tools, setup, platform))
