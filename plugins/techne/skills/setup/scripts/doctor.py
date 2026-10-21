#!/usr/bin/env python3
"""Check what the techne skills need on this machine, and print the fix for each gap.

Runs on the system python3 (3.9 or newer, standard library only) and installs nothing.
Usage: python3 doctor.py [--repo PATH]
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # a doctor leaves no file behind, not even in the plugin cache
PLUGIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN / "_shared"))
import doctor_lib as d  # noqa: E402  # ty: ignore[unresolved-import]
import techne_config as tc  # noqa: E402  # ty: ignore[unresolved-import]

SKELETON = PLUGIN / "skills" / "setup" / "skill-context.template.md"
TOML_KEYS = ("workspace_root", "github_user")


def gh_auth() -> d.Check:
    gh = d.which("gh")
    if not gh:
        return d.Check(d.NA, "gh-auth", "gh is missing")
    host = os.environ.get("GH_HOST") or "github.com"
    code, out = d.run([gh, "auth", "status", "--hostname", host])
    # gh 2.45 exits 0 for a dead token, a bad GH_TOKEN or a host with no sign-in, and marks
    # the failure with an "X Failed to log in" line.
    failed = [line.strip()[2:].strip() for line in out.splitlines() if line.strip()[:2] == "X "]
    if code == 0 and not failed and "Failed to log in" not in out:
        return d.Check(d.OK, "gh-auth", f"signed in to {host}")
    lines = [line.strip() for line in out.splitlines() if line.strip() and line.strip() != host]
    why = d.first_line(failed[0] if failed else "\n".join(lines)) or "not signed in"
    return d.Check(
        d.MISSING, "gh-auth", f"{host}: {why}", (f"fix: gh auth login --hostname {host}",)
    )


def repo_root(start: Path) -> tuple[Path | None, str]:
    git = d.which("git")
    if not git:
        return None, "git is missing"
    code, out = d.run([git, "-C", str(start), "rev-parse", "--show-toplevel"])
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if code == 0 and lines:
        return Path(lines[-1]), ""
    return None, f"{start} is not inside a git repository"


def skill_context(start: Path) -> d.Check:
    root, why = repo_root(start)
    if root is None:
        return d.Check(d.NA, "skill-context", why)
    ctx = root / ".claude" / "skill-context.md"
    if ctx.is_file():
        return d.Check(d.OK, "skill-context", str(ctx))
    copy = (
        f"mkdir -p {shlex.quote(str(ctx.parent))}"
        f" && cp {shlex.quote(str(SKELETON))} {shlex.quote(str(ctx))}"
    )
    detail = f"no .claude/skill-context.md in {root} (techne:audit and techne:theoros read it)"
    return d.Check(d.OPTIONAL, "skill-context", detail, (f"fix: {copy}",))


def techne_toml() -> d.Check:
    """techne.toml read the way every techne script reads it (techne_config); below python3 3.11,
    with no TOML parser, a presence check of its keys instead."""
    path = tc.techne_toml()
    edit = (f"fix: ${{EDITOR:-nano}} ~/.claude/techne.toml  # schema: {d.CONFIG_DOCS}",)
    try:
        cfg = tc.load(path)
        if cfg is not None:
            tc.sisters(cfg, path)
            tc.workspace_root(cfg)
    except tc.NeedsTomllib:
        cfg = None
        text = path.read_text(encoding="utf-8", errors="replace")
        top = re.split(r"^\s*\[", text, maxsplit=1, flags=re.MULTILINE)[0]  # keys before tables
        lacking = [k for k in TOML_KEYS if not re.search(rf"^\s*{k}\s*=", top, re.MULTILINE)]
        if not re.search(r"^\s*\[\[sisters\]\]", text, re.MULTILINE):
            lacking.append("[[sisters]]")
    except tc.ConfigError as exc:
        return d.Check(d.OPTIONAL, "techne.toml", str(exc), edit)
    else:
        if cfg is None:
            return d.Check(
                d.OPTIONAL, "techne.toml", "~/.claude/techne.toml not found (techne:sisters)", edit
            )
        lacking = [k for k in TOML_KEYS if k not in cfg]
        if "sisters" not in cfg:
            lacking.append("[[sisters]]")
        if not lacking:
            try:
                tc.required(cfg, path)
            except tc.ConfigError as exc:
                return d.Check(d.OPTIONAL, "techne.toml", str(exc), edit)
    if lacking:
        return d.Check(d.OPTIONAL, "techne.toml", "missing " + ", ".join(lacking), edit)
    return d.Check(d.OK, "techne.toml", str(path))


def lsof(platform: d.Platform) -> d.Check:
    if platform.os != d.MACOS:
        return d.Check(d.NA, "lsof", "only macOS needs it; Linux reads /proc")
    found = d.which("lsof")
    if found:
        return d.Check(d.OK, "lsof", found)
    return d.Check(
        d.MISSING,
        "lsof",
        "not on PATH; macOS ships it in /usr/sbin (techne:sisters clean mode)",
        ("fix: echo 'export PATH=\"$PATH:/usr/sbin\"' >> ~/.zprofile",),
    )


def checks(platform: d.Platform, repo: Path) -> list[d.Check]:
    version = ("--version",)
    return [
        d.program(platform, "git", "git", version_argv=version),
        d.program(platform, "gh", "gh", version_argv=version),
        d.guarded("gh-auth", True, gh_auth),
        d.program(platform, "uv", "uv", version_argv=version),
        d.program(
            platform,
            "python3",
            "python3",
            version_argv=d.PYTHON_VERSION_ARGV,
            minimum=(3, 11),
            why=(
                "techne:catchup, techne:sisters and techne:board need 3.11; "
                "below it, docsync and ci-audit ask on every repo when techne.toml exists"
            ),
        ),
        d.program(platform, "tmux", "tmux", version_argv=("-V",), why="techne:theoros"),
        d.guarded(
            "chromium", False, lambda: d.chromium(required=False, why="techne:docs-site visual QA")
        ),
        d.guarded("lsof", True, lambda: lsof(platform)),
        d.guarded("skill-context", False, lambda: skill_context(repo)),
        d.guarded("techne.toml", False, techne_toml),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="where to look for .claude/skill-context.md (default: the current directory)",
    )
    args = parser.parse_args(argv)
    return d.report(checks(d.detect_platform(), args.repo or Path.cwd()))


if __name__ == "__main__":
    sys.exit(main())
