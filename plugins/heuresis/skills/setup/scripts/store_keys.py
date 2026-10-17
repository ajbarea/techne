#!/usr/bin/env python3
"""Save heuresis's search keys from a .env file into Claude Code's secure storage.

Runs on the system python3 (3.9 or newer, standard library only).
Usage: python3 store_keys.py --template
       python3 store_keys.py <file> [--plugin heuresis@techne]
Values go to `claude plugin configure --values-stdin` on stdin and are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

sys.dont_write_bytecode = True
PLUGIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN / "hooks"))
from search_keys import BY_ENV, KEYS  # noqa: E402  # ty: ignore[unresolved-import]

PLUGIN_NAME = "heuresis"


class StoreError(Exception):
    """A message safe to print: it never contains a value."""


def template() -> str:
    return "".join(f"# {k.why[0].upper()}{k.why[1:]}\n{k.env}=\n\n" for k in KEYS)


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def parse(text: str) -> dict[str, str]:
    """Env var name to non-empty value. An unknown name raises, naming the line, not the value."""
    found: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[len("export") :].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or name not in BY_ENV:
            what = f"unknown name {name!r}" if sep else "not a NAME=value line"
            raise StoreError(f"line {number}: {what}")
        value = unquote(value)
        if value:
            found[name] = value
    return found


def find_plugin_id(listing: str, wanted: str | None) -> str:
    if wanted:
        return wanted
    try:
        entries = json.loads(listing)
    except ValueError:
        raise StoreError("could not read `claude plugin list --json`; pass --plugin <id>") from None
    ids = sorted(
        {
            e["id"]
            for e in entries
            if isinstance(e, dict) and str(e.get("id", "")).startswith(f"{PLUGIN_NAME}@")
        }
    )
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise StoreError(f"{PLUGIN_NAME} is not installed; install it or pass --plugin <id>")
    raise StoreError(f"several {PLUGIN_NAME} installs ({', '.join(ids)}); pass --plugin <id>")


def redact(text: str, values: Sequence[str]) -> str:
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def run_claude(argv: Sequence[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StoreError(f"`{' '.join(argv[:3])}` failed to run: {type(exc).__name__}") from None


def warn_if_shared(path: Path) -> None:
    if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(f"warning: {path} is readable by others; run chmod 600 on it", file=sys.stderr)


def store(path: Path, plugin: str | None) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read {path}: {type(exc).__name__}", file=sys.stderr)
        return 2
    warn_if_shared(path)
    try:
        found = parse(text)
    except StoreError as exc:
        print(f"error: {path}: {exc}", file=sys.stderr)
        return 2
    if not found:
        print(f"No values in {path}; nothing stored.")
        return 1
    if not shutil.which("claude"):
        print("error: `claude` is not on PATH; install Claude Code first", file=sys.stderr)
        return 2
    try:
        listing = run_claude(["claude", "plugin", "list", "--json"]) if not plugin else None
        plugin_id = find_plugin_id(listing.stdout if listing else "", plugin)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    values = {BY_ENV[name].option: value for name, value in found.items()}
    try:
        done = run_claude(
            ["claude", "plugin", "configure", plugin_id, "--values-stdin"], stdin=json.dumps(values)
        )
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if done.returncode != 0:
        secrets = list(values.values())
        print(f"error: claude plugin configure exited {done.returncode}", file=sys.stderr)
        print(redact(done.stderr or "", secrets).strip(), file=sys.stderr)
        return 1
    print(f"Stored in Claude Code's secure storage for {plugin_id}: {', '.join(found)}")
    print("Restart Claude Code to apply it.")
    print(f"Delete {path} now, or keep it somewhere private; it holds the keys in plain text.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", nargs="?", help=".env file holding the keys")
    ap.add_argument("--template", action="store_true", help="print a .env template and exit")
    ap.add_argument("--plugin", help="plugin id, such as heuresis@techne")
    args = ap.parse_args(argv)
    if args.template:
        print(template(), end="")
        return 0
    if not args.file:
        ap.error("give a file, or --template")
    return store(Path(args.file).expanduser(), args.plugin)


if __name__ == "__main__":
    sys.exit(main())
