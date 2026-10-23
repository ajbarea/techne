"""Fail when a tracked or addable file names one of the repo owner's private repos.

Names come from `gh repo list <owner> --visibility private`, so the list never enters the
repo. A name matches as a whole word, any case, with `-` and `_` also matching a space or
each other. Names listed in `<git-common-dir>/info/private-words` (one per line, `#`
comments) are ordinary words too, and match only as `owner/name` or `name#N`.

Exit 0 when clean or skipped (no gh, signed out, or no private repo visible: CI's token),
1 when a name is found, 2 when gh or git fails another way.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict

SHOWN_PER_NAME = 10


def skip(reason: str) -> int:
    print(f"SKIP: private repo name scan: {reason}", file=sys.stderr)
    return 0


def fail(reason: str) -> int:
    print(f"FAIL: private repo name scan: {reason}", file=sys.stderr)
    return 2


class GhSignedOut(Exception):
    pass


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    if result.returncode == 4:
        raise GhSignedOut
    if result.returncode != 0:
        first = (result.stderr.strip().splitlines() or ["no output"])[0]
        raise RuntimeError(f"gh {' '.join(args[:2])} exited {result.returncode}: {first}")
    return result.stdout


def git(*args: str) -> bytes:
    result = subprocess.run(["git", *args], capture_output=True, timeout=60)
    if result.returncode != 0:
        first = (result.stderr.decode(errors="replace").strip().splitlines() or ["no output"])[0]
        raise RuntimeError(f"git {args[0]} exited {result.returncode}: {first}")
    return result.stdout


def name_pattern(name: str) -> str:
    parts = re.split(r"[-_]", name)
    return "[-_ ]".join(re.escape(p) for p in parts)


def read_words(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return set()
    return {ln.strip().lower() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")}


def build_regex(owner: str, names: list[str], words: set[str]) -> re.Pattern[str]:
    """One alternation; the group name `n<i>` says which private name matched."""
    edge_l, edge_r = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
    alts = []
    for i, name in enumerate(names):
        body = name_pattern(name)
        if name.lower() in words:
            inner = rf"{re.escape(owner)}/{body}{edge_r}|{body}#\d"
        else:
            inner = body + edge_r
        alts.append(rf"(?P<n{i}>{edge_l}(?:{inner}))")
    return re.compile("|".join(alts), re.IGNORECASE)


def files() -> list[bytes]:
    out = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted(set(p for p in out.split(b"\0") if p))


def texts(path: bytes) -> list[str] | None:
    """Lines to scan: a symlink's target or a text file's lines; None for a binary or gone file."""
    if os.path.islink(path):
        return [os.fsdecode(os.readlink(path))]
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:  # gone, a directory (submodule, nested repo) or unreadable
        return None
    if b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", errors="replace").splitlines()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
    if shutil.which("gh") is None:
        return skip("gh is not installed")
    try:
        top = git("rev-parse", "--show-toplevel").decode().strip()
        os.chdir(top)
        words_path = git("rev-parse", "--path-format=absolute", "--git-path", "info/private-words")
        words_path = words_path.decode().strip()
        owner = gh("repo", "view", "--json", "owner", "--jq", ".owner.login").strip()
        listing = gh(
            "repo", "list", owner, "--visibility", "private", "--json", "name", "--limit", "10000"
        )
        names = sorted({r["name"] for r in json.loads(listing)})
        paths = files()
    except GhSignedOut:
        return skip("gh is not signed in")
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as e:
        return fail(str(e))
    if not names:
        return skip(f"no private repo of {owner} is visible to this gh login")
    words = read_words(words_path)
    regex = build_regex(owner, names, words)

    # name -> (path, line), line 0 for the file name itself
    hits: dict[str, list[tuple[str, int]]] = defaultdict(list)

    def named(match: re.Match[str]) -> str:
        return names[int(str(match.lastgroup)[1:])]

    for path in paths:
        shown = os.fsdecode(path)
        for match in regex.finditer(shown):
            hits[named(match)].append((shown, 0))
        for number, line in enumerate(texts(path) or [], 1):
            for match in regex.finditer(line):
                hits[named(match)].append((shown, number))

    if not hits:
        print(f"OK: {len(paths)} files hold none of {owner}'s {len(names)} private repo names")
        return 0
    for name in sorted(hits):
        where = sorted(hits[name])
        print(f"{name!r}, a private repo of {owner}, appears {len(where)} times:")
        for path, number in where[:SHOWN_PER_NAME]:
            print(f"  {path}: in the file name" if number == 0 else f"  {path}:{number}")
        if len(where) > SHOWN_PER_NAME:
            print(f"  ... and {len(where) - SHOWN_PER_NAME} more")
    print(
        "Name each private repo by what it is. Where a name is only an ordinary word, add it to"
        f" {words_path} (one per line, kept out of the repo); it then matches only as"
        f" {owner}/name or name#N."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
