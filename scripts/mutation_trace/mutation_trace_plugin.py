"""pytest plugin for scripts/mutation.py's trace run: names the running test for sitecustomize.

Loaded with `-p mutation_trace_plugin`. Before each test's fixtures are set up it sets
MUTATION_TEST_ID, which every python3 the test starts inherits, and after the test's fixtures are
torn down it writes what this process reached under that id, fixture code included.
"""

from __future__ import annotations

import os

import pytest
import sitecustomize


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item) -> None:
    sitecustomize.flush(None)  # what collection and fixtures of earlier tests reached
    os.environ["MUTATION_TEST_ID"] = item.nodeid


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem) -> None:
    sitecustomize.flush(item.nodeid)
    os.environ.pop("MUTATION_TEST_ID", None)
