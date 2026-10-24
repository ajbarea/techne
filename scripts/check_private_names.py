"""Fail when anything a commit or push can carry names one of the repo owner's private repos.

Names come from `gh repo list <owner> --visibility private`, so the list never enters the
repo. Scanned: each index entry's staged content; each tracked or addable working-tree
file (`git ls-files --cached --others --exclude-standard`); every blob, path and commit
message in commits no remote has (`git rev-list HEAD --not --remotes`); the branch name;
and every file name. A name matches as a whole word or CamelCase part, any case, its parts
(split at `-`, `_`, `.`, spaces and case changes) joined by any run of `-`, `_`, `.` or
space, or none (`secret-proj`, `Secret Proj`, `SecretProjClient`). Names listed in
`<git-common-dir>/info/private-words` (one per line, `#` comments, compared the same way)
are ordinary words too, and match only as the slugs `owner/name` and `name#N`.

Exit 0 when clean or skipped (no gh, or gh cannot list the owner's private repos: signed
out, offline, or CI's token), 1 when a name is found, 2 when git, gh's output or the words
file fails. Pushed history is not scanned: it is already public.
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
PARTS = re.compile(r"[-_.\s]+|(?<=[a-z0-9])(?=[A-Z])")
# A word edge: no letter or digit beside the match, or a lower-to-upper case change.
CAMEL_L, CAMEL_R = r"(?-i:(?<=[a-z0-9])(?=[A-Z]))", r"(?-i:(?<=[a-z0-9])(?=[A-Z]))"
WORD_L = rf"(?:(?<![A-Za-z0-9])|{CAMEL_L})"
WORD_R = rf"(?:(?![A-Za-z0-9])|{CAMEL_R})"
# A slug's edges: owner names hold letters, digits and `-`; repo names also `.` and `_`.
# A slug may end a sentence or a clone URL: `acme/name.` and `acme/name.git`.
OWNER_L = r"(?<![A-Za-z0-9-])"
REPO_L = r"(?<![A-Za-z0-9._/-])"
REPO_R = r"(?:\.git)?(?![A-Za-z0-9_-]|\.[A-Za-z0-9_-])"
BOMS = (b"\xff\xfe", b"\xfe\xff")


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


def git(*args: str, stdin: bytes | None = None, check: bool = True) -> bytes:
    result = subprocess.run(["git", *args], input=stdin, capture_output=True, timeout=120)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {args[0]} exited {result.returncode}: {first_line(result.stderr)}")
    return result.stdout if result.returncode == 0 else b""


def parts(name: str) -> list[str]:
    return [part for part in PARTS.split(name) if part]


def key(name: str) -> str:
    return "".join(parts(name)).lower()


def name_pattern(name: str) -> str:
    return SEP.join(re.escape(part) for part in parts(name))


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


def read_blobs(shas: list[bytes]) -> list[bytes]:
    """The contents of SHAS, in order, through one `git cat-file --batch`."""
    if not shas:
        return []
    out = git("cat-file", "--batch", stdin=b"".join(sha + b"\n" for sha in shas))
    blobs, at = [], 0
    for sha in shas:
        end = out.index(b"\n", at)
        header = out[at:end].split()
        if header[0] != sha or header[1] != b"blob":
            raise RuntimeError(f"git cat-file: unexpected {out[at:end]!r}")
        size = int(header[2])
        blobs.append(out[end + 1 : end + 1 + size])
        at = end + 2 + size
    return blobs


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
    return dict(zip([p for p, _ in entries], read_blobs([s for _, s in entries]), strict=True))


def on_disk(path: bytes) -> bytes | None:
    """A working-tree file's content: a symlink's target; None for a gone or odd file."""
    try:
        if os.path.islink(path):
            return os.readlink(path)
        with open(path, "rb") as f:
            return f.read()
    except OSError:  # gone, a directory (submodule, nested repo) or unreadable
        return None


def unpushed() -> tuple[list[tuple[bytes, bytes | None]], list[tuple[str, bytes]]]:
    """Objects and commit messages in commits no remote has: (path, blob content or None for
    a tree) per object with a path, and (short sha, message) per commit."""
    if not git("rev-parse", "-q", "--verify", "HEAD", check=False):
        return [], []
    objects = []
    for line in git("rev-list", "--objects", "HEAD", "--not", "--remotes").splitlines():
        sha, _, path = line.partition(b" ")
        if path:
            objects.append((sha, path))
    kinds = git(
        "cat-file", "--batch-check=%(objecttype)", stdin=b"".join(s + b"\n" for s, _ in objects)
    )
    is_blob = [kind == b"blob" for kind in kinds.splitlines()]
    blobs = iter(read_blobs([s for (s, _), blob in zip(objects, is_blob, strict=True) if blob]))
    found = [
        (path, next(blobs) if blob else None)
        for (_, path), blob in zip(objects, is_blob, strict=True)
    ]
    log = git("log", "-z", "--format=%h%n%B", "HEAD", "--not", "--remotes")
    messages = []
    for entry in log.split(b"\0"):
        if entry.strip():
            sha, _, body = entry.partition(b"\n")
            messages.append((sha.decode(), body))
    return found, messages


def sources() -> list[tuple[str, list[bytes]]]:
    """Each label (a path, a history path, a commit, the branch) with every distinct content
    a commit or push could carry under it; the label itself is scanned too."""
    found: dict[str, list[bytes]] = defaultdict(list)

    def add(label: str, data: bytes | None) -> None:
        if data is not None and data not in found[label]:
            found[label].append(data)
        found.setdefault(label, [])

    for path, data in staged().items():
        add(os.fsdecode(path), data)
    listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for path in {p for p in listed.split(b"\0") if p}:
        add(os.fsdecode(path), on_disk(path))
    objects, messages = unpushed()
    for path, data in objects:
        label = os.fsdecode(path)
        if data is None or data not in found.get(label, []):
            add(f"{label} (an unpushed commit)", data)
    for sha, body in messages:
        add(f"commit {sha} message", body)
    branch = git("symbolic-ref", "-q", "--short", "HEAD", check=False).decode().strip()
    if branch:
        add(f"branch {branch}", None)
    return sorted(found.items())


def lines(data: bytes) -> list[str] | None:
    """Text split on newlines only, so numbers match `git grep -n`; None for binary."""
    if data.startswith(BOMS):
        return data.decode("utf-16", errors="replace").split("\n")
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
        words = read_words(words_path)
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
    regex = build_regex(owner, names, words)

    # name -> {(label, line)}, line 0 for the label itself
    hits: dict[str, set[tuple[str, int]]] = defaultdict(set)

    def named(match: re.Match[str]) -> str:
        return names[int(str(match.lastgroup)[1:])]

    scanned = 0
    for label, contents in files:
        for match in regex.finditer(label):
            hits[named(match)].add((label, 0))
        texts = [t for t in (lines(data) for data in contents) if t is not None]
        scanned += bool(texts)
        for text in texts:
            for number, line in enumerate(text, 1):
                for match in regex.finditer(line):
                    hits[named(match)].add((label, number))

    if not hits:
        print(f"OK: {scanned} texts hold none of {owner}'s {len(names)} private repo names")
        return 0
    for name in sorted(hits):
        where = sorted(hits[name])
        print(f"{name!r}, a private repo of {owner}, appears {len(where)} times:")
        for label, number in where[:SHOWN_PER_NAME]:
            print(f"  {label}: in its name" if number == 0 else f"  {label}:{number}")
        if len(where) > SHOWN_PER_NAME:
            print(f"  ... and {len(where) - SHOWN_PER_NAME} more")
    print(
        "Name each private repo by what it is. Where a name is only an ordinary word, add it to"
        f" {words_path} (one per line, kept out of the repo); it then matches only as"
        f" {owner}/name or name#N. A name in an unpushed commit or message needs a rebase."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
