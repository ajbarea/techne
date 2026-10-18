"""The sisters hook starts on the user's system python3, which may be 3.9.

hygiene.py needs 3.11 (tomllib). As a hook it must end quietly on an older python3; for a
person at a terminal it must still say what to do. `make test-hooks-oldest` runs this file
with TECHNE_GUARD_PYTHON set to 3.9, and the normal run uses the current python.
"""

from __future__ import annotations

import subprocess
import sys

from conftest import HOOK_PYTHON, HYGIENE_SCRIPT


def run(*args: str, tmp_path):
    return subprocess.run(
        [HOOK_PYTHON, str(HYGIENE_SCRIPT), *args],
        env={
            "HOME": str(tmp_path),
            "PATH": str(tmp_path / "empty"),
            "XDG_CACHE_HOME": str(tmp_path),
        },
        input="{}",
        capture_output=True,
        text=True,
    )


def test_the_hook_exits_zero_and_silent_on_whatever_python_runs_it(tmp_path):
    for flags in (["--auto"], ["--auto", "--hook"]):
        proc = run(*flags, tmp_path=tmp_path)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_a_person_on_an_old_python_is_told_what_to_do(tmp_path):
    version = subprocess.run(
        [HOOK_PYTHON, "-c", "import sys; print(sys.version_info >= (3, 11))"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    proc = run("--env", tmp_path=tmp_path)
    if version == "False":
        assert proc.returncode != 0
        assert "older than 3.11" in proc.stderr
    else:
        assert "older than" not in proc.stderr
    assert sys.executable
