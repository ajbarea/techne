"""Exit non-zero unless this interpreter is the pinned build: PYTHON_PATH (setup-python's
python-path output) at version PYTHON_VERSION. A timing job runs it under `uv run` so the venv
the timed code runs in is checked, not only the runner's PATH. sys._base_executable (the
interpreter a venv was made from) is CPython's; elsewhere sys.executable stands in."""

import os
import sys

real = os.path.realpath
got = (
    real(getattr(sys, "_base_executable", sys.executable)),
    ".".join(map(str, sys.version_info[:3])),
)
want = (real(os.environ["PYTHON_PATH"]), os.environ["PYTHON_VERSION"])
sys.exit(0 if got == want else f"the venv runs {got}, not the pinned {want}")
