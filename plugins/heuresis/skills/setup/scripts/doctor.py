#!/usr/bin/env python3
"""Check what heuresis needs: uv, git, gh, the ideas repository, the repos folder, API keys.

Runs on the system python3 (3.9 or newer, standard library only) and installs nothing.
Usage: python3 doctor.py IDEAS_REPO=<path> REPOS_ROOT=<path>
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

sys.dont_write_bytecode = True  # a doctor leaves no file behind, not even in the plugin cache
PLUGIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN / "_shared"))
import doctor_lib as d  # noqa: E402  # ty: ignore[unresolved-import]
import plugin_keys as pk  # noqa: E402  # ty: ignore[unresolved-import]

INFO = pk.load_plugin(PLUGIN)


def parse(argv: Sequence[str]) -> dict[str, str]:
    values = {}
    for arg in argv:
        key, sep, value = arg.partition("=")
        if sep:
            values[key] = value.strip()
    return values


def folder(name: str, value: str, *, is_ideas_repo: bool) -> d.Check:
    if not value or value.startswith("${"):
        return d.Check(d.MISSING, name, "not set; set it in /config under the heuresis plugin")
    path = Path(value).expanduser()
    if not path.is_dir():
        return d.Check(d.MISSING, name, f"{path} does not exist")
    if is_ideas_repo and not ((path / "ideas").is_dir() and (path / ".git").exists()):
        detail = f"{path} is not an ideas repository; the runbook creates one"
        return d.Check(d.MISSING, name, detail)
    return d.Check(d.OK, name, str(path))


def checks(values: Mapping[str, str], environ: Mapping[str, str]) -> list[d.Check]:
    platform = d.detect_platform()
    found = [
        d.program(platform, "uv", "uv", version_argv=("--version",)),
        d.program(platform, "git", "git", version_argv=("--version",)),
        d.program(platform, "gh", "gh", required=False, why="GitHub search and the ideas remote"),
        folder("ideas_repo", values.get("IDEAS_REPO", ""), is_ideas_repo=True),
        folder("repos_root", values.get("REPOS_ROOT", ""), is_ideas_repo=False),
    ]
    return found + d.key_checks(pk.doctor_entries(INFO, environ))


def main(argv: Sequence[str] | None = None) -> int:
    values = parse(sys.argv[1:] if argv is None else argv)
    return d.report(checks(values, os.environ))


if __name__ == "__main__":
    sys.exit(main())
