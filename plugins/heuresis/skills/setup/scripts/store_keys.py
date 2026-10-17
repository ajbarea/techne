#!/usr/bin/env python3
"""Save heuresis's search keys from a .env file into Claude Code's secure storage.

Runs on the system python3 (3.9 or newer, standard library only).
Usage: python3 store_keys.py --template
       python3 store_keys.py <file> [--plugin heuresis@techne]
Values go to `claude plugin configure --values-stdin` on stdin and are never printed.
Exit codes: 0 stored, 1 nothing stored (the file holds no values), 2 any error (usage, unreadable
or unparsable file, `claude` missing or failing, configure failure).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

sys.dont_write_bytecode = True
PLUGIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN / "hooks"))
from search_keys import BY_ENV, KEYS  # noqa: E402  # ty: ignore[unresolved-import]

PLUGIN_NAME = "heuresis"
SHARED_BITS = stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH


class StoreError(Exception):
    """A message safe to print: it never contains a value."""


def template() -> str:
    blocks = []
    for k in KEYS:
        head, _, tail = k.why.partition("; ")
        partners = [o.env for o in KEYS if o.group == k.group and o is not k] if k.group else []
        head += f", with {' and '.join(partners)}" if partners else ""
        comment = f"{head}; {tail}" if tail else head
        blocks.append(f"# {comment[0].upper()}{comment[1:]}\n{k.env}=\n\n")
    return "".join(blocks)


def unquote(raw: str, number: int, name: str) -> str:
    """The value after `=`: quoted text, or unquoted text up to an inline ` #` comment."""
    text = raw.lstrip()
    if text[:1] in ("'", '"'):
        end = text.find(text[0], 1)
        if end < 0:
            raise StoreError(f"line {number}: unterminated quote for {name}")
        rest = text[end + 1 :]
        if rest.strip() and not (rest[0] in " \t" and rest.strip().startswith("#")):
            raise StoreError(f"line {number}: text after the closing quote for {name}")
        return text[1:end]
    return re.split(r"[ \t]#", raw, maxsplit=1)[0].strip()


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
        value = unquote(value, number, name)
        if value:
            found[name] = value
    return found


def half_groups(found: Mapping[str, str]) -> dict[str, tuple[list[str], list[str]]]:
    """Group name to (given, missing) env names, for each group given without all its members."""
    out = {}
    for group in dict.fromkeys(k.group for k in KEYS if k.group):
        members = [k.env for k in KEYS if k.group == group]
        given = [env for env in members if env in found]
        if given and len(given) < len(members):
            out[group] = (given, [env for env in members if env not in found])
    return out


def find_plugin_id(listing: str, wanted: str | None) -> str:
    if wanted:
        return wanted
    try:
        entries = json.loads(listing)
    except ValueError:
        raise StoreError("could not read `claude plugin list --json`; pass --plugin <id>") from None
    installs = [
        e
        for e in entries
        if isinstance(e, dict) and str(e.get("id", "")).startswith(PLUGIN_NAME + "@")
    ]
    enabled = sorted({e["id"] for e in installs if e.get("enabled", True)})
    every = sorted({e["id"] for e in installs})
    for ids in (enabled, every):
        if len(ids) == 1:
            return ids[0]
        if len(ids) > 1:
            break
    if not every:
        raise StoreError(f"{PLUGIN_NAME} is not installed; install it or pass --plugin <id>")
    listed = ", ".join(enabled or every)
    raise StoreError(f"several {PLUGIN_NAME} installs ({listed}); pass --plugin <id>")


def redact(text: str, values: Sequence[str]) -> str:
    forms = {form for v in values for form in (v, json.dumps(v)[1:-1])}
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, "***")
    return text


def run_claude(argv: Sequence[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StoreError(f"`{' '.join(argv[:3])}` failed to run: {type(exc).__name__}") from None


def warn_if_shared(path: Path) -> None:
    if os.name == "posix" and path.stat().st_mode & SHARED_BITS:
        print(f"warning: {path} can be read or changed by others; run chmod 600", file=sys.stderr)


def store(path: Path, plugin: str | None) -> int:
    try:
        text = path.read_text(encoding="utf-8-sig")
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
    partial = half_groups(found)
    for given, missing in partial.values():
        print(
            f"warning: {' and '.join(given)} given without {' and '.join(missing)}", file=sys.stderr
        )
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
        return 2
    if done.returncode != 0:
        secrets = list(values.values())
        print(f"error: claude plugin configure exited {done.returncode}", file=sys.stderr)
        print(redact(done.stderr or "", secrets).strip(), file=sys.stderr)
        return 2
    print(f"Stored in Claude Code's secure storage for {plugin_id}: {', '.join(found)}")
    for group, (_, missing) in partial.items():
        print(f"{group} stays skipped until {' and '.join(missing)} is saved too.")
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
