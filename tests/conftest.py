"""Load the skill-shipped scripts as importable modules.

Skills ship standalone scripts, not packages, so there is nothing to install
and nothing on sys.path. Each one is loaded from its path by file.

Two ways of faking a subprocess are in use, and the split is deliberate. Use
pytest-subprocess (`fp`) to stand in for a command's output and to assert the
exact argv, which is what the catchup sweep needs across many gh and git calls.
Use monkeypatch where the assertion is about the environment a command runs in:
`fp.calls` records argv only, so it cannot see that the latex build sets
max_print_line, which is the line the log parsing depends on. A hook or script run as its
own process (the board hook on python3 3.9) gets `gh_stub`: a fake gh first on PATH, answering
from rules and logging every call.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
import types
from collections.abc import Iterable, Mapping

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS = ROOT / "plugins" / "techne" / "skills"
DOC_SKILLS = ROOT / "plugins" / "graphe" / "skills"
LATEX_SCRIPT = DOC_SKILLS / "latex" / "scripts" / "latex.py"
RENDER_SCRIPT = DOC_SKILLS / "pdf" / "scripts" / "render.py"
SWEEP_SCRIPT = SKILLS / "catchup" / "scripts" / "sweep.py"
SLIDES_SCRIPT = DOC_SKILLS / "slides" / "scripts" / "slides.py"
HYGIENE_SCRIPT = SKILLS / "sisters" / "scripts" / "hygiene.py"
AGENTS_MD_SCRIPT = SKILLS / "sisters" / "scripts" / "agents_md.py"
LOGCHECK_SCRIPT = SKILLS / "logging" / "scripts" / "logcheck.py"
BOARD_SCRIPT = SKILLS / "board" / "scripts" / "board.py"
PROSE_SCRIPT = ROOT / "plugins" / "graphe" / "_shared" / "prose_check.py"
DOKIMASIA_SCRIPT = ROOT / "plugins" / "dokimasia" / "skills" / "check" / "scripts" / "dokimasia.py"
DOCTOR_LIB = ROOT / "plugins" / "techne" / "_shared" / "doctor_lib.py"
SCHOLARLY_SCRIPT = ROOT / "plugins" / "techne" / "_shared" / "scholarly.py"
REPO_KIND_SCRIPT = ROOT / "plugins" / "techne" / "_shared" / "repo_kind.py"
GOLD_RUNNER = ROOT / "scripts" / "heuresis_gold.py"

# The doctors and hooks run on the user's system python3; `make test-hooks-oldest` sets this
# to python3 3.9.
HOOK_PYTHON = os.environ.get("TECHNE_GUARD_PYTHON", sys.executable)

# The PDF read-back tests (web deck export, markdown render) use poppler's pdftotext and pdfinfo.
# A machine without it declares so with TECHNE_NO_POPPLER=1; test_slides_web.py fails otherwise.
NO_POPPLER = os.environ.get("TECHNE_NO_POPPLER") == "1"
HAVE_POPPLER = not NO_POPPLER and all(shutil.which(t) for t in ("pdftotext", "pdfinfo"))
needs_poppler = pytest.mark.skipif(
    not HAVE_POPPLER, reason="no poppler (declared by TECHNE_NO_POPPLER)"
)


def hook_env(
    on: Iterable[str] | Mapping[str, str] = (), drop: tuple[str, ...] = (), **extra: str
) -> dict[str, str]:
    """A plugin hook's environment: ours without any inherited CLAUDE_PLUGIN_OPTION_* or DROP
    prefix and without the developer's global or system git config (where a phylax.* key
    would switch a guard off), each ON option set ("true" for a key, or the value a mapping
    gives), then EXTRA."""
    if isinstance(on, str):
        raise TypeError("hook_env takes a list of option keys or a mapping, not one string")
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_PLUGIN_OPTION_", *drop))
    }
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    values = on if isinstance(on, Mapping) else dict.fromkeys(on, "true")
    env.update({f"CLAUDE_PLUGIN_OPTION_{key.upper()}": value for key, value in values.items()})
    env.update(extra)
    return env


def hook_handlers(plugin: str, event: str, matcher: str | None = None) -> list[dict]:
    """The handlers PLUGIN's hooks/hooks.json registers for EVENT, in groups matching MATCHER."""
    config = json.loads((ROOT / "plugins" / plugin / "hooks" / "hooks.json").read_text())
    groups = config["hooks"].get(event, [])
    return [h for g in groups if matcher in (None, g.get("matcher")) for h in g["hooks"]]


def hook_shell(plugin: str, handler: Mapping, python: str | None = HOOK_PYTHON) -> str:
    """HANDLER's shell-form command with the plugin root filled in, and `exec python3` run on
    PYTHON (None keeps the PATH lookup, for a test that python3 never starts)."""
    shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT / "plugins" / plugin))
    return (
        shell if python is None else shell.replace("exec python3 ", f"exec {shlex.quote(python)} ")
    )


def run_hook_handler(
    plugin: str,
    handler: Mapping,
    stdin: str,
    env: Mapping[str, str],
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess:
    """Run HANDLER through sh, as Claude Code runs a shell-form hook."""
    return subprocess.run(
        ["sh", "-c", hook_shell(plugin, handler)],
        input=stdin,
        capture_output=True,
        text=True,
        env=dict(env),
        cwd=cwd,
        check=False,
        timeout=60,
    )


# One doctor output line: a check, an indented fix, or the closing result.
DOCTOR_LINE = re.compile(
    r"^(ok|missing|optional|n/a) [^\s:]+: .+$"
    r"|^  fix( \((Debian/Ubuntu|macOS)\))?: .+$"
    r"|^result: (ready|missing .+)$"
)

# Published text must not carry a personal address or a path from someone's machine.
EMAIL = re.compile(
    r"[\w.+-]+@(?!(?:[\w-]+\.)*example\.(?:com|edu|org)(?![\w-]*\.\w))[\w-]+\.[A-Za-z][\w.]*"
)
MACHINE_PATH = re.compile(r"/(?:home|mnt|Users)/|[A-Za-z]:\\Users")


def stub_dir(
    root: pathlib.Path, stubs: Mapping[str, str] | None = None, links: Iterable[str] = ()
) -> str:
    """A PATH holding only the given stubs and links to chosen real tools.

    A stub body is POSIX sh after a `#!/bin/sh` line; anything it runs besides sh builtins
    must be named by absolute path, since PATH holds only this directory.
    """
    bindir = root / "stub-bin"
    if bindir.exists():
        shutil.rmtree(bindir)  # each call defines the whole PATH
    bindir.mkdir()
    for name, body in (stubs or {}).items():
        script = bindir / name
        script.write_text(f"#!/bin/sh\n{body}\n")
        script.chmod(0o755)
    for name in links:
        real = shutil.which(name)
        assert real, f"{name} is needed on this machine to build the stub PATH"
        (bindir / name).symlink_to(real)
    return str(bindir)


def fake_chromium(
    root: pathlib.Path, revision: str = "1243", body: str = "echo 'Chromium 150.0.7871.0'"
) -> pathlib.Path:
    """The headless-shell executable `playwright install chromium` puts under `root`."""
    exe = root / f"chromium_headless_shell-{revision}" / "chrome-headless-shell-linux64"
    exe.mkdir(parents=True, exist_ok=True)
    exe = exe / "chrome-headless-shell"
    exe.write_text(f"#!/bin/sh\n{body}\n")
    exe.chmod(0o755)
    return exe


def run_doctor(
    script: pathlib.Path,
    *args: str,
    path: str,
    home: pathlib.Path,
    cwd: pathlib.Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a doctor the way the setup skill does: on the system python3, in a bare env."""
    base = {
        "PATH": path,
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "TECHNE_DOCTOR_OS": "debian",
        "TECHNE_DOCTOR_WSL": "0",
        "PLAYWRIGHT_BROWSERS_PATH": str(home / "ms-playwright"),
    }
    return subprocess.run(
        [HOOK_PYTHON, str(script), *args],
        cwd=cwd or home,
        env={**base, **(env or {})},
        capture_output=True,
        text=True,
        timeout=60,
    )


def doctor_lines(proc: subprocess.CompletedProcess) -> dict[str, tuple[str, str]]:
    """{check name: (status, detail)}, after asserting every line is in the doctor format."""
    assert "Traceback" not in proc.stderr, proc.stderr
    lines = proc.stdout.splitlines()
    assert lines and lines[-1].startswith("result: "), proc.stdout
    bad = [line for line in lines if not DOCTOR_LINE.match(line)]
    assert not bad, bad
    found: dict[str, tuple[str, str]] = {}
    for line in lines:
        if line.startswith(("  ", "result: ")):
            continue
        status, _, rest = line.partition(" ")
        name, _, detail = rest.partition(": ")
        found[name] = (status, detail)
    return found


def doctor(
    script: pathlib.Path,
    tmp_path: pathlib.Path,
    home: pathlib.Path,
    *args: str,
    stubs: Mapping[str, str] | None = None,
    links: Iterable[str] = (),
    cwd: pathlib.Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess, dict[str, tuple[str, str]]]:
    """Run a doctor on a PATH of just these stubs and links; (process, parsed lines)."""
    path = stub_dir(tmp_path, stubs, links)
    proc = run_doctor(script, *args, path=path, home=home, cwd=cwd, env=env)
    return proc, doctor_lines(proc)


# The variables a git hook exports that point git at a repository.
GIT_REPO_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
)


@pytest.fixture(autouse=True, scope="session")
def _no_inherited_git_repo():
    """Unset the repo-locating git variables for the whole suite.

    From a worktree a hook exports them as absolute paths, so a test's `git init`
    in tmp_path would act on the real repo instead.
    """
    with pytest.MonkeyPatch.context() as mp:
        for var in GIT_REPO_VARS:
            mp.delenv(var, raising=False)
        yield


def locked_versions(lock: pathlib.Path) -> dict[str, set[str]]:
    """Package name -> the versions a uv.lock pins for it."""
    out: dict[str, set[str]] = {}
    for pkg in tomllib.loads(lock.read_text())["package"]:
        out.setdefault(pkg["name"], set()).add(pkg.get("version", ""))
    return out


def _load(name: str, path: pathlib.Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Registered in sys.modules, so every client that imports polite_http shares this one copy.
polite_http = _load("polite_http", ROOT / "plugins" / "techne" / "_shared" / "polite_http.py")


class Sleeps(list):
    """Seconds polite_http would have slept. `now` is its fake clock, advanced by each sleep."""

    now = 1_000_000.0


@pytest.fixture(autouse=True)
def slept(monkeypatch, tmp_path):
    """No test waits on a real host interval or touches the user's pacing stamps."""
    waits = Sleeps()

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        waits.now += seconds

    monkeypatch.setenv("TECHNE_POLITE_DIR", str(tmp_path / "polite-http"))
    monkeypatch.setattr(polite_http, "_sleep", sleep)
    monkeypatch.setattr(polite_http, "_now", lambda: waits.now)
    monkeypatch.setattr(polite_http, "_ROBOTS", {})
    return waits


@pytest.fixture(scope="session")
def lx() -> types.ModuleType:
    return _load("techne_latex", LATEX_SCRIPT)


@pytest.fixture(scope="session")
def rn() -> types.ModuleType:
    """render.py imports typst lazily, so the module loads without the wheel."""
    return _load("techne_render", RENDER_SCRIPT)


@pytest.fixture(scope="session")
def sw() -> types.ModuleType:
    return _load("techne_sweep", SWEEP_SCRIPT)


@pytest.fixture(scope="session")
def rk() -> types.ModuleType:
    return _load("techne_repo_kind", REPO_KIND_SCRIPT)


@pytest.fixture(scope="session")
def sl() -> types.ModuleType:
    return _load("techne_slides", SLIDES_SCRIPT)


@pytest.fixture(scope="session")
def hy() -> types.ModuleType:
    return _load("techne_hygiene", HYGIENE_SCRIPT)


@pytest.fixture(scope="session")
def am() -> types.ModuleType:
    return _load("techne_agents_md", AGENTS_MD_SCRIPT)


@pytest.fixture(scope="session")
def pc() -> types.ModuleType:
    return _load("techne_prose_check", PROSE_SCRIPT)


@pytest.fixture(scope="session")
def dk() -> types.ModuleType:
    return _load("techne_dokimasia", DOKIMASIA_SCRIPT)


@pytest.fixture(scope="session")
def pb() -> types.ModuleType:
    """The board's shared module, registered as project_board so board.py imports this copy."""
    return _load("project_board", ROOT / "plugins" / "techne" / "_shared" / "project_board.py")


@pytest.fixture(scope="session")
def bd(pb: types.ModuleType) -> types.ModuleType:
    return _load("techne_board", BOARD_SCRIPT)


@pytest.fixture
def gates():
    """Reduce findings to the (severity, gate) pairs a test actually asserts on."""

    def _gates(found) -> set[tuple[str, str]]:
        return {(f.severity, f.gate) for f in found}

    return _gates


@pytest.fixture
def write_log(tmp_path):
    """Write a .log beside a fake source and hand back its path."""

    def _write(body: str, stem: str = "doc") -> pathlib.Path:
        log = tmp_path / f"{stem}.log"
        log.write_text(body, encoding="utf-8")
        return log

    return _write


GH_STUB = ROOT / "tests" / "fixtures" / "gh_stub.py"


class GhStub:
    """A fake gh on PATH plus a HOME and cache under tmp_path; see fixtures/gh_stub.py."""

    def __init__(self, tmp_path: pathlib.Path) -> None:
        self.home = tmp_path / "home"
        (self.home / ".claude").mkdir(parents=True)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        shim = bin_dir / "gh"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{GH_STUB}" "$@"\n')
        shim.chmod(0o755)
        self.log = tmp_path / "gh-calls.jsonl"
        self.rules_file = tmp_path / "gh-rules.json"
        self.rules([])
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "HOME": str(self.home),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GH_STUB_LOG": str(self.log),
            "GH_STUB_RULES": str(self.rules_file),
        }

    def rules(self, rules: list[dict]) -> None:
        self.rules_file.write_text(json.dumps(rules))

    def config(self, text: str) -> None:
        (self.home / ".claude" / "techne.toml").write_text(text)

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def argvs(self) -> list[list[str]]:
        return [c["argv"] for c in self.calls()]


@pytest.fixture
def gh_stub(tmp_path: pathlib.Path) -> GhStub:
    return GhStub(tmp_path)


BOARD_TOML = '[board]\nowner = "ajbarea"\nnumber = 7\n'
BOARD_OPTIONS = {"Idea": "o_idea", "Issue": "o_issue", "In PR": "o_pr", "Merged": "o_merged",
                 "Live": "o_live"}  # fmt: skip


def board_rules(options: Mapping[str, str] = BOARD_OPTIONS) -> list[dict]:
    """gh answers for a board whose Status field holds OPTIONS: view, field-list, item-add
    (item id PVTI_<n> from the URL's number), item-edit, and a membership query that finds
    no item on the board."""
    fields = {
        "fields": [
            {"id": "F_TITLE", "name": "Title", "type": "ProjectV2Field"},
            {
                "id": "F_STATUS",
                "name": "Status",
                "type": "ProjectV2SingleSelectField",
                "options": [{"id": i, "name": n} for n, i in options.items()],
            },
        ],
        "totalCount": 2,
    }
    rules: list[dict] = [
        {"match": ["project", "view"], "stdout": json.dumps({"id": "PVT_7", "number": 7})},
        {"match": ["project", "field-list"], "stdout": json.dumps(fields)},
        {"match": ["project", "item-edit"], "stdout": "{}"},
    ]
    for n in range(1, 10):
        rules.append(
            {
                "match": ["project", "item-add", f"*/{n}"],
                "stdout": json.dumps({"id": f"PVTI_{n}", "type": "Issue"}),
            }
        )
    absent = {"data": {"resource": {"projectItems": {"nodes": []}}}}
    rules.append({"match": ["api", "graphql"], "stdout": json.dumps(absent)})
    return rules


def proc_state(pid: int) -> str:
    """The /proc state letter of PID, or "Z" once it is gone (reaped between two reads too)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0]
    except OSError:
        return "Z"


def assert_gone(pid: int) -> None:
    """Fail unless PID has exited (a zombie counts: init reaps it later) within 2 s; it is
    killed afterwards either way."""
    try:
        for _ in range(40):
            if proc_state(pid) == "Z":
                return
            time.sleep(0.05)
        raise AssertionError(f"process {pid} is still running")
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
