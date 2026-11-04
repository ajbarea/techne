"""pytest plugin for scripts/mutation.py's trace run: names the running test for sitecustomize.

Loaded with `-p mutation_trace_plugin`. Before each test it sets MUTATION_TEST_ID, which every
python3 the test starts inherits, and after it writes what this process reached under that id.
"""

from __future__ import annotations

import os

import sitecustomize


def pytest_runtest_setup(item) -> None:
    sitecustomize.flush(None)  # what collection and fixtures of earlier tests reached
    os.environ["MUTATION_TEST_ID"] = item.nodeid


def pytest_runtest_teardown(item, nextitem) -> None:
    sitecustomize.flush(item.nodeid)
    os.environ.pop("MUTATION_TEST_ID", None)
