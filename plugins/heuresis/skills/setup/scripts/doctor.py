#!/usr/bin/env python3
"""Check what heuresis needs: uv, git, gh, the ideas repository, the repos folder, API keys.

Runs on the system python3 (3.9 or newer, standard library only) and installs nothing.
Usage: python3 doctor.py IDEAS_REPO=<path> REPOS_ROOT=<path>
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

sys.dont_write_bytecode = True  # a doctor leaves no file behind, not even in the plugin cache
PLUGIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN / "_shared"))
import doctor_lib as d  # noqa: E402  # ty: ignore[unresolved-import]
import plugin_keys as pk  # noqa: E402  # ty: ignore[unresolved-import]


def parse(argv: Sequence[str]) -> dict[str, str]:
    values = {}
    for arg in argv:
        key, sep, value = arg.partition("=")
        if sep:
            values[key] = value.strip()
    return values


def ideas_repo(path: Path) -> bool:
    """Mirrors heuresis.context.is_ideas_repo, which this standard-library script cannot import."""
    if not ((path / "ideas").is_dir() and (path / "projects.toml").is_file()):
        return False
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    top = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return not top.returncode and Path(top.stdout.strip()).resolve() == path.resolve()


def folder(name: str, value: str, *, is_ideas_repo: bool) -> d.Check:
    if not value or value.startswith("${"):
        return d.Check(d.MISSING, name, "not set; set it in /config under the heuresis plugin")
    path = Path(value).expanduser()
    if not path.is_dir():
        return d.Check(d.MISSING, name, f"{path} does not exist")
    if is_ideas_repo and not ideas_repo(path):
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
    return found + d.key_checks(pk.doctor_entries_for(PLUGIN, environ))


def main(argv: Sequence[str] | None = None) -> int:
    values = parse(sys.argv[1:] if argv is None else argv)
    return d.report(checks(values, os.environ))


if __name__ == "__main__":
    sys.exit(main())
