"""Load the skill-shipped scripts as importable modules.

Skills ship standalone scripts, not packages, so there is nothing to install
and nothing on sys.path. Each one is loaded from its path by file.

Two ways of faking a subprocess are in use, and the split is deliberate. Use
pytest-subprocess (`fp`) to stand in for a command's output and to assert the
exact argv, which is what the catchup sweep needs across many gh and git calls.
Use monkeypatch where the assertion is about the environment a command runs in:
`fp.calls` records argv only, so it cannot see that the latex build sets
max_print_line, which is the line the log parsing depends on.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS = ROOT / "plugins" / "techne" / "skills"
LATEX_SCRIPT = SKILLS / "latex" / "scripts" / "latex.py"
RENDER_SCRIPT = SKILLS / "pdf" / "scripts" / "render.py"
SWEEP_SCRIPT = SKILLS / "catchup" / "scripts" / "sweep.py"
SLIDES_SCRIPT = SKILLS / "slides" / "scripts" / "slides.py"
HYGIENE_SCRIPT = SKILLS / "sisters" / "scripts" / "hygiene.py"
PROSE_SCRIPT = ROOT / "plugins" / "techne" / "_shared" / "prose_check.py"


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


def _load(name: str, path: pathlib.Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
def sl() -> types.ModuleType:
    return _load("techne_slides", SLIDES_SCRIPT)


@pytest.fixture(scope="session")
def hy() -> types.ModuleType:
    return _load("techne_hygiene", HYGIENE_SCRIPT)


@pytest.fixture(scope="session")
def pc() -> types.ModuleType:
    return _load("techne_prose_check", PROSE_SCRIPT)


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
