"""Records which functions of the files under mutation each test reaches, in every Python process.

scripts/mutation.py puts this folder first on PYTHONPATH for its trace run, so the pytest process
and every python3 a test starts (a hook run as a script, a module it imports) load it. Set
MUTATION_TRACE_DIR (where to write), MUTATION_TRACE_FILES (the files to watch, joined by
os.pathsep) and MUTATION_TEST_ID (the test running, set by mutation_trace_plugin.py) to turn it
on; without them it does nothing. Each process writes one JSON line per test it saw:
{"test": <node id>, "hits": [[file, qualified name], ...]}. A hook test runs its hook as a
subprocess, which is why the trace cannot be one in-process hook the way mutmut's own is.
Needs python3 3.12 or newer (sys.monitoring); on an older one it does nothing.
"""

from __future__ import annotations

import atexit
import json
import os
import sys

_DIR = os.environ.get("MUTATION_TRACE_DIR")
_FILES = {f for f in os.environ.get("MUTATION_TRACE_FILES", "").split(os.pathsep) if f}
_hits: set[tuple[str, str]] = set()
_watched: dict[str, str | None] = {}  # co_filename -> its real path when watched, else None
_tool: int | None = None


def _start(code, offset):
    path = _watched.get(code.co_filename, "")
    if path == "":
        real = os.path.realpath(code.co_filename)
        path = _watched[code.co_filename] = real if real in _FILES else None
    if path is not None:
        _hits.add((path, code.co_qualname))
    # Each function is recorded once per test; flush() turns the event back on for the next.
    return sys.monitoring.DISABLE


def flush(test_id: str | None) -> None:
    """Write the hits since the last flush under TEST_ID (none: drop them) and start afresh."""
    if _tool is None:
        return
    if test_id and _hits:
        name = os.path.join(_DIR or "", f"{os.getpid()}.jsonl")
        with open(name, "a", encoding="utf-8") as out:
            out.write(json.dumps({"test": test_id, "hits": sorted(_hits)}) + "\n")
    _hits.clear()
    sys.monitoring.restart_events()


def _install() -> None:
    global _tool
    if not (_DIR and _FILES and hasattr(sys, "monitoring")):
        return
    mon = sys.monitoring
    for tool in range(6):
        if mon.get_tool(tool) is None:
            mon.use_tool_id(tool, "techne-mutation-trace")
            _tool = tool
            break
    else:
        return
    mon.register_callback(_tool, mon.events.PY_START, _start)
    mon.set_events(_tool, mon.events.PY_START)
    atexit.register(lambda: flush(os.environ.get("MUTATION_TEST_ID")))


try:
    _install()
except Exception:  # tracing must never break the process it watches
    _tool = None
