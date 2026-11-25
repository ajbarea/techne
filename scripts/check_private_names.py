"""Fail when anything a commit or push can carry names one of the repo owner's private repos.

Names come from `gh repo list <owner> --visibility private`, so the list never enters the
repo. Scanned: each index entry's staged content; each tracked or addable working-tree
file (`git ls-files --cached --others --exclude-standard`); every blob, path and commit
message in commits no remote has (`git rev-list HEAD --not --remotes`, plus every path
those commits add, delete or rename); the branch name; and every file name. A name matches
as a whole word or CamelCase part, any case, its parts (split at `-`, `_`, `.`, spaces and
case changes) joined by any run of `-`, `_`, `.` or whitespace, a line break included, or
none (`secret-proj`, `Secret Proj`, `SecretProjClient`). Names listed in
`<git-common-dir>/info/private-words` (one per line, `#` comments, compared the same way)
are ordinary words too, and match only as the slugs `owner/name` and `name#N`.

With --push REV... it scans only what a push sends: the commits, files, paths and messages
reachable from REV (a commit, a ref, or rev-list's --branches, --tags, --all, --glob=) that no
remote has, and the names of the refs pushed (REV's own, and each --ref NAME); the index and
working tree are left out, so an untracked file never blocks a push. --pre-push REMOTE URL
is git's pre-push hook: it reads git's `<local ref> <sha> <remote ref> <sha>` lines on stdin
and scans each pushed sha and both ref names, skipping deletions, against what REMOTE's
tracking refs hold (a commit another remote has still goes to this one); a push to a URL no
remote is configured for scans the whole history. As the hook it takes the owner from the URL
and refuses the push (exit 2) when gh cannot list the private repos, instead of skipping.

Exit 0 when clean or skipped (no gh, or gh cannot list the owner's private repos: signed
out, offline, or CI's token), 1 when a name is found, 2 when git, gh's output or the words
file fails. Pushed history is not scanned: it is already on a remote. Runs on the system
python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import bisect
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
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            env={k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")},
        )
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
    # With no input, stdin is /dev/null: a config reading /dev/stdin reads nothing of ours.
    result = subprocess.run(
        ["git", *args],
        input=stdin,
        stdin=None if stdin is not None else subprocess.DEVNULL,
        capture_output=True,
        timeout=120,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {args[0]} exited {result.returncode}: {first_line(result.stderr)}")
    return result.stdout if result.returncode == 0 else b""


def paired(a: list, b: list) -> list[tuple]:
    """zip(A, B, strict=True), which python 3.9 lacks."""
    if len(a) != len(b):
        raise RuntimeError(f"git returned {len(b)} records for {len(a)} objects")
    return list(zip(a, b))  # noqa: B905  # 3.9 has no strict=; the length check above is it


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


def build_prefilter(owner: str, names: list[str], words: set[str]) -> re.Pattern[str]:
    """Each name without its edges, a listed word as `owner/name` or `name#`: every match of
    build_regex holds one, so a text this finds nothing in is skipped before build_regex
    runs over it."""
    slug = re.escape(owner) + "/{0}|{0}#"
    alts = [slug.format(re.escape(n)) if key(n) in words else name_pattern(n) for n in names]
    return re.compile("|".join(alts), re.IGNORECASE)


def read_blobs(shas: list[bytes], kind: bytes = b"blob") -> list[bytes]:
    """The contents of SHAS (objects of type KIND), in order, through one `git cat-file --batch`."""
    if not shas:
        return []
    out = git("cat-file", "--batch", stdin=b"".join(sha + b"\n" for sha in shas))
    blobs, at = [], 0
    for sha in shas:
        end = out.index(b"\n", at)
        header = out[at:end].split()
        if header[0] != sha or header[1] != kind:
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
    return dict(paired([p for p, _ in entries], read_blobs([s for _, s in entries])))


def on_disk(path: bytes) -> bytes | None:
    """A working-tree file's content: a symlink's target; None for a gone or odd file."""
    try:
        if os.path.islink(path):
            return os.readlink(path)
        with open(path, "rb") as f:
            return f.read()
    except OSError:  # gone, a directory (submodule, nested repo) or unreadable
        return None


def unpushed(
    revs: tuple[str, ...] = ("HEAD",), held: tuple[str, ...] = ("--remotes",)
) -> tuple[list[tuple[bytes, bytes | None]], list[tuple[str, bytes]]]:
    """Objects and commit messages in commits reachable from REVS that the remote-tracking refs
    HELD selects (every remote's, or one remote's) do not have: (path, blob content or None for
    a tree) per object with a path, and (short sha, message) per commit."""
    if revs == ("HEAD",) and not git("rev-parse", "-q", "--verify", "HEAD", check=False):
        return [], []
    span = [*revs, *(("--not", *held) if held else ()), "--"]  # `--`: a ref is never a path
    objects = []
    for line in git("rev-list", "--objects", *span).splitlines():
        sha, _, path = line.partition(b" ")
        if path:
            objects.append((sha, path))
    kinds = git(
        "cat-file", "--batch-check=%(objecttype)", stdin=b"".join(s + b"\n" for s, _ in objects)
    )
    typed = paired(objects, kinds.splitlines())
    pairs = [(obj, kind == b"blob") for obj, kind in typed]
    blobs = iter(read_blobs([s for (s, _), blob in pairs if blob]))
    found = [(path, next(blobs) if blob else None) for (_, path), blob in pairs]
    # An annotated tag's message goes out with the tag.
    tags = [(s, path) for (s, path), kind in typed if kind == b"tag"]
    # rev-list names each object once, under one path: a renamed file's old name, or a file
    # whose content a remote already has, appears only in the commits' path lists.
    changed = git("log", "-z", "--format=", "--name-only", "--no-renames", "-m", *span)
    found += [(path.strip(b"\n"), None) for path in set(changed.split(b"\0")) if path.strip()]
    log = git("log", "-z", "--format=%h%n%B", *span)
    messages = []
    for entry in log.split(b"\0"):
        if entry.strip():
            sha, _, body = entry.partition(b"\n")
            messages.append((sha.decode(), body))
    for (_, path), body in paired(tags, read_blobs([s for s, _ in tags], b"tag")):
        messages.append((f"tag {os.fsdecode(path)}", body))
    return found, messages


def ref_names(revs: tuple[str, ...], refs: tuple[str, ...]) -> set[str]:
    """The names a push publishes: REFS, each named rev, and every ref a --branches, --tags,
    --all or --glob= rev selects."""
    names = set(refs)
    patterns = []
    for rev in revs:
        if rev in ("--branches", "--all"):
            patterns.append("refs/heads/")
        if rev in ("--tags", "--all"):
            patterns.append("refs/tags/")
        if rev.startswith("--glob="):
            patterns.append(rev[len("--glob=") :])
        elif not rev.startswith("-"):
            names.add(rev)
    if patterns:
        listed = git("for-each-ref", "--format=%(refname)", *patterns).decode()
        names.update(n for n in listed.splitlines() if n)
    return names


def target_refs(remote: str) -> tuple[str, ...]:
    """The rev-list arguments for what the push's target already holds: a named remote's
    tracking refs (another remote's copy does not make a commit public there), the remote a
    URL is configured for, else nothing, so the whole history is scanned. With no target
    (the default and --push scans), every remote's refs."""
    if not remote:
        return ("--remotes",)
    names = git("remote").decode().split()
    if remote not in names:
        urls = git("config", "--get-regexp", r"^remote\..*\.(push)?url$", check=False).decode()
        matches = {
            key[len("remote.") : key.rindex(".")]
            for key, _, url in (line.partition(" ") for line in urls.splitlines())
            if url == remote
        }
        remote = matches.pop() if len(matches) == 1 else ""
        if not remote:
            return ()
    return (f"--remotes={remote}",)


def sources(
    push: tuple[str, ...] | None = None, refs: tuple[str, ...] = (), remote: str = ""
) -> list[tuple[str, list[bytes]]]:
    """Each label (a path, a history path, a commit, a ref) with every distinct content a
    commit or push could carry under it; the label itself is scanned too. PUSH, when given,
    is the revisions a push sends: only what they reach is scanned, with the pushed ref names."""
    found: dict[str, list[bytes]] = defaultdict(list)

    def add(label: str, data: bytes | None) -> None:
        if data is not None and data not in found[label]:
            found[label].append(data)
        found.setdefault(label, [])

    if push is not None:
        held = target_refs(remote)
        objects, messages = unpushed(push, held) if push else ([], [])
        for path, data in objects:
            add(f"{os.fsdecode(path)} (a pushed commit)", data)
        for sha, body in messages:
            add(sha if sha.startswith("tag ") else f"commit {sha} message", body)
        for name in ref_names(push, refs):
            add(f"ref {name}", None)
        return sorted(found.items())
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
        add(sha if sha.startswith("tag ") else f"commit {sha} message", body)
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


ZERO_SHA = re.compile(r"^0+$")


def url_owner(url: str) -> str:
    """The owner in a GitHub remote URL (https, ssh with or without a port, or scp form), or
    "" for any other host."""
    from urllib.parse import urlsplit

    if "://" in url:
        parts = urlsplit(url)
        host, path = (parts.hostname or "").lower(), parts.path
    else:  # scp form: [user@]host:path
        found = re.match(r"^(?:[^@/]+@)?([^:/]+):(.*)$", url)
        host, path = (found.group(1).lower(), found.group(2)) if found else ("", "")
    if host not in ("github.com", "www.github.com", "ssh.github.com"):
        return ""
    owner = path.lstrip("/").split("/", 1)[0]
    return owner if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", owner) else ""


def parse_args(argv: list[str]) -> tuple[tuple[str, ...] | None, tuple[str, ...], str]:
    """(revisions a push sends, or None for the default scan; ref names it publishes; the
    remote the pre-push hook names, or "")."""
    if not argv:
        return None, (), ""
    revs: list[str] = []
    refs: list[str] = []
    if argv[0] == "--pre-push":  # git passes REMOTE URL; the refs come on stdin
        for line in sys.stdin.read().splitlines():
            fields = line.split()
            if len(fields) != 4:
                raise ValueError(f"unexpected pre-push line {line!r}")
            local_ref, local_sha, remote_ref, _ = fields
            if ZERO_SHA.match(local_sha):
                continue  # a deletion sends nothing
            revs.append(local_sha)
            refs += [local_ref, remote_ref]
        return tuple(revs), tuple(refs), argv[1] if len(argv) > 1 else ""
    if argv[0] != "--push":
        raise ValueError(f"unknown argument {argv[0]!r}; use --push REV... or --pre-push")
    rest = iter(argv[1:])
    for arg in rest:
        if arg == "--ref":
            refs.append(next(rest, ""))
        else:
            revs.append(arg)
    return tuple(revs), tuple(r for r in refs if r), ""


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
    args = sys.argv[1:] if argv is None else argv
    try:
        push, refs, remote = parse_args(args)
    except ValueError as e:
        return fail(str(e))
    # As the pre-push hook, a scan that cannot run refuses the push: anything that hides gh
    # (PATH, HOME, a bad token, a proxy) would otherwise let a push out unscanned.
    pre_push = bool(args) and args[0] == "--pre-push"
    url = args[2] if pre_push and len(args) > 2 else ""

    def unavailable(reason: str) -> int:
        if not pre_push:
            return skip(reason)
        fix = (
            "Install gh (https://cli.github.com) and sign in with `gh auth login`"
            if "not installed" in reason
            else "Check `gh auth status` (sign in with `gh auth login`)"
        )
        return fail(
            f"{reason}, so this push was refused unscanned. {fix}; if you are sure the push"
            " names no private repo, push with --no-verify."
        )

    if shutil.which("gh") is None:
        return unavailable("gh is not installed")
    try:
        top = git("rev-parse", "--show-toplevel").decode().strip()
        # git runs a hook with GIT_DIR relative to where it started; keep it valid past chdir.
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            if os.environ.get(name):
                os.environ[name] = os.path.abspath(os.environ[name])
        os.chdir(top)
        words_path = git("rev-parse", "--path-format=absolute", "--git-path", "info/private-words")
        words_path = words_path.decode().strip()
        words = read_words(words_path)
        # The repo's own owner (gh ignores GH_REPO here) and, as the hook, the owner of the URL
        # git pushes to: a push to another account still scans for this owner's names.
        owner = gh("repo", "view", "--json", "owner", "--jq", ".owner.login").strip()
        owners = list(dict.fromkeys(o for o in (owner, url_owner(url)) if o))
        listed = {}
        for each in owners:
            listing = gh(
                "repo",
                "list",
                each,
                "--visibility",
                "private",
                "--json",
                "name",
                "--limit",
                "10000",
            )
            listed[each] = sorted({r["name"] for r in json.loads(listing)})
        files = sources(push, refs, remote)
    except GhUnavailable as e:
        return unavailable(str(e))
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as e:
        return fail(str(e))
    except subprocess.TimeoutExpired as e:
        return fail(f"{e.cmd[0]} timed out")
    if pre_push:
        # Only the owner's own login sees every private repo; another account (a second one
        # of the same person, a collaborator) sees some or none, so the scan would miss names.
        try:
            login = gh("api", "user", "--jq", ".login").strip()
        except GhUnavailable as e:
            return unavailable(str(e))
        if login not in owners:
            return unavailable(
                f"gh is signed in as {login}, who may not see every private repo of "
                f"{', '.join(owners)}"
            )
    if not any(listed.values()):
        return skip(f"no private repo of {', '.join(owners)} is visible to this gh login")

    # name -> {(label, line)}, line 0 for the label itself; owner by name, for the report
    hits: dict[str, set[tuple[str, int]]] = defaultdict(set)
    owner_of: dict[str, str] = {}
    scanned = sum(any(lines(d) is not None for d in contents) for _, contents in files)
    for each, names in listed.items():
        if not names:
            continue
        regex, prefilter = build_regex(each, names, words), build_prefilter(each, names, words)

        def named(match: re.Match[str], names: list[str] = names) -> str:
            return names[int(str(match.lastgroup)[1:])]

        for label, contents in files:
            for match in regex.finditer(label):
                hits[named(match)].add((label, 0))
                owner_of[named(match)] = each
            texts = [t for t in (lines(data) for data in contents) if t is not None]
            for whole in ("\n".join(t) for t in texts):
                if not prefilter.search(whole):
                    continue
                # The whole text at once, so a name wrapped across lines still matches.
                breaks = [m.start() for m in re.finditer("\n", whole)]
                for match in regex.finditer(whole):
                    line = bisect.bisect_left(breaks, match.start()) + 1
                    hits[named(match)].add((label, line))
                    owner_of[named(match)] = each
    names = [n for ns in listed.values() for n in ns]

    if not hits:
        print(
            f"OK: {scanned} texts hold none of {' and '.join(owners)}'s {len(names)} private"
            " repo names"
        )
        return 0
    for name in sorted(hits):
        where = sorted(hits[name])
        print(f"{name!r}, a private repo of {owner_of[name]}, appears {len(where)} times:")
        for label, number in where[:SHOWN_PER_NAME]:
            print(f"  {label}: in its name" if number == 0 else f"  {label}:{number}")
        if len(where) > SHOWN_PER_NAME:
            print(f"  ... and {len(where) - SHOWN_PER_NAME} more")
    print(
        "Name each private repo by what it is. Where a name is only an ordinary word, add it to"
        f" {words_path} (one per line, kept out of the repo); it then matches only as"
        f" {owner}/name or name#N. A name in an unpushed commit or message needs a rebase."
    )  # logcheck: ignore[stderr-for-errors] ends the findings report, which is the result
    return 1


if __name__ == "__main__":
    sys.exit(main())
