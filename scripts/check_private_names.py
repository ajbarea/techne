"""Fail when a file a commit or push can carry names one of the repo owner's private repos.

Names come from `gh repo list <owner> --visibility private`, so the list never enters the
repo. Scanned: each index entry's staged content and each tracked or addable working-tree
file (`git ls-files --cached --others --exclude-standard`), plus every file name. A name
matches as a whole word, any case, its parts joined by any run of `-`, `_`, `.` or space,
or none (`secret-proj`, `Secret Proj`, `SecretProj`). Names listed in
`<git-common-dir>/info/private-words` (one per line, `#` comments, compared the same way)
are ordinary words too, and match only as the slugs `owner/name` and `name#N`.

Exit 0 when clean or skipped (no gh, or gh cannot list the owner's private repos: signed
out, offline, or CI's token), 1 when a name is found, 2 when git or gh's output fails.
History is not scanned: what was pushed before is already public.
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
SEP = r"[-_.\s]*"
WORD_L, WORD_R = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
# A slug's edges: owner names hold letters, digits and `-`; repo names also `.` and `_`.
OWNER_L = r"(?<![A-Za-z0-9-])"
REPO_L, REPO_R = r"(?<![A-Za-z0-9._/-])", r"(?![A-Za-z0-9._-])"


def skip(reason: str) -> int:
    print(f"SKIP: private repo name scan: {reason}", file=sys.stderr)
    return 0


def fail(reason: str) -> int:
    print(f"FAIL: private repo name scan: {reason}", file=sys.stderr)
    return 2


class GhUnavailable(Exception):
    pass


def first_line(stderr: str | bytes) -> str:
    text = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
    return (text.strip().splitlines() or ["no output"])[0]


def gh(*args: str) -> str:
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as e:
        raise GhUnavailable(f"gh {' '.join(args[:2])} timed out") from e
    if result.returncode == 4:
        raise GhUnavailable("gh is not signed in")
    if result.returncode != 0:
        raise GhUnavailable(
            f"gh {' '.join(args[:2])} exited {result.returncode}: {first_line(result.stderr)}"
        )
    return result.stdout


def git(*args: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(["git", *args], input=stdin, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} exited {result.returncode}: {first_line(result.stderr)}")
    return result.stdout


def key(name: str) -> str:
    return re.sub(r"[-_.\s]+", "", name.lower())


def name_pattern(name: str) -> str:
    return SEP.join(re.escape(part) for part in re.split(r"[-_.\s]+", name) if part)


def read_words(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return set()
    return {key(ln) for ln in lines if ln.strip() and not ln.lstrip().startswith("#")}


def build_regex(owner: str, names: list[str], words: set[str]) -> re.Pattern[str]:
    """One alternation, longest name first so `foo-bar` is not reported as `foo`; the group
    name `n<i>` says which of NAMES matched."""
    alts = []
    for i in sorted(range(len(names)), key=lambda i: -len(names[i])):
        name = names[i]
        if key(name) in words:
            slug = re.escape(name)
            inner = rf"{OWNER_L}{re.escape(owner)}/{slug}{REPO_R}|{REPO_L}{slug}#\d"
        else:
            inner = WORD_L + name_pattern(name) + WORD_R
        alts.append(rf"(?P<n{i}>{inner})")
    return re.compile("|".join(alts), re.IGNORECASE)


def staged() -> dict[bytes, bytes]:
    """Each index entry's content, by path; a symlink's is its target, a submodule has none."""
    entries = []
    for record in git("ls-files", "-s", "-z").split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        mode, sha, _stage = meta.split()
        if mode != b"160000":
            entries.append((path, sha))
    if not entries:
        return {}
    out = git("cat-file", "--batch", stdin=b"".join(sha + b"\n" for _, sha in entries))
    blobs, at = {}, 0
    for path, sha in entries:
        end = out.index(b"\n", at)
        header = out[at:end].split()
        if header[0] != sha or header[1] != b"blob":
            raise RuntimeError(f"git cat-file: unexpected {out[at:end]!r}")
        size = int(header[2])
        blobs[path] = out[end + 1 : end + 1 + size]
        at = end + 2 + size
    return blobs


def on_disk(path: bytes) -> bytes | None:
    """A working-tree file's content: a symlink's target; None for a gone or odd file."""
    try:
        if os.path.islink(path):
            return os.readlink(path)
        with open(path, "rb") as f:
            return f.read()
    except OSError:  # gone, a directory (submodule, nested repo) or unreadable
        return None


def sources() -> list[tuple[bytes, list[bytes]]]:
    """Each path with every distinct content a commit or push could carry for it."""
    found: dict[bytes, list[bytes]] = defaultdict(list)
    for path, data in staged().items():
        found[path].append(data)
    listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for path in {p for p in listed.split(b"\0") if p}:
        data = on_disk(path)
        if data is not None and data not in found[path]:
            found[path].append(data)
    return sorted(found.items())


def lines(data: bytes) -> list[str] | None:
    """Text split on newlines only, so numbers match `git grep -n`; None for binary."""
    if b"\0" in data[:8000]:
        return None
    return [line.decode("utf-8", errors="replace") for line in data.split(b"\n")]


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
        files = sources()
    except GhUnavailable as e:
        return skip(str(e))
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as e:
        return fail(str(e))
    except subprocess.TimeoutExpired as e:
        return fail(f"{e.cmd[0]} timed out")
    if not names:
        return skip(f"no private repo of {owner} is visible to this gh login")
    regex = build_regex(owner, names, read_words(words_path))

    # name -> {(path, line)}, line 0 for the file name itself
    hits: dict[str, set[tuple[str, int]]] = defaultdict(set)

    def named(match: re.Match[str]) -> str:
        return names[int(str(match.lastgroup)[1:])]

    scanned = 0
    for path, contents in files:
        shown = os.fsdecode(path)
        for match in regex.finditer(shown):
            hits[named(match)].add((shown, 0))
        texts = [t for t in (lines(data) for data in contents) if t is not None]
        scanned += bool(texts)
        for text in texts:
            for number, line in enumerate(text, 1):
                for match in regex.finditer(line):
                    hits[named(match)].add((shown, number))

    if not hits:
        print(f"OK: {scanned} text files hold none of {owner}'s {len(names)} private repo names")
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
