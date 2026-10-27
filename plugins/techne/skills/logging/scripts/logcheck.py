#!/usr/bin/env python3
"""Check a repo against techne's logging standard (references/standard.md beside this script).

Usage:
    logcheck.py [--format text|github|json] [REPO]
    logcheck.py --summary REPO [REPO ...]

REPO defaults to the current directory's repository. Only tracked files are read, minus
vendored and build folders, and the line rules skip tests and fixtures.

Rules:
    lint-python           ruff does not select the G and LOG families (closest ruff config per file)
    lint-rust             clippy's print_stdout, print_stderr and dbg_macro are not warn or deny
    lint-js               no ESLint no-console or Biome noConsole rule is on
    secret-in-log         a secret-looking name reaches a log or print call
    unbounded-log-file    a log file handler or appender has no size or file-count cap
    stderr-for-errors     a shell error message goes to stdout (in a workflow: not an annotation)
    ci-logs-not-uploaded  a workflow job writes a log file and uploads no artifact on failure
    log-file-tracked      a .log file is committed

A line holding `logcheck: ignore` or `logcheck: ignore[rule, ...]` suppresses findings on the
call or command it is part of. The `## logging` section of .claude/skill-context.md takes
`- ignore: rule, ...` for a whole repo and `- skip: path/, ...` for path prefixes.

Exit status: 0 clean, 1 findings, 2 not a repository. --summary prints one line per repo and
always exits 0.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import stat
import subprocess
import sys
import warnings
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path, PurePosixPath

if sys.version_info < (3, 11):  # noqa: UP036  # the user's system python3 runs this
    sys.exit("logcheck.py needs python3 3.11 or newer (it reads TOML with tomllib)")

import tomllib

sys.dont_write_bytecode = True  # the plugin cache stays as installed
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "_shared"))
from git_env import without_repo_overrides  # noqa: E402  # ty: ignore[unresolved-import]

RULES = (
    "lint-python",
    "lint-rust",
    "lint-js",
    "secret-in-log",
    "unbounded-log-file",
    "stderr-for-errors",
    "ci-logs-not-uploaded",
    "log-file-tracked",
)
VENDORED = {
    "node_modules", "vendor", "third_party", "dist", "build", "site", "target", ".venv", "venv",
    "__pycache__", "coverage", ".next", ".nuxt", ".astro", ".output", "_build",
}  # fmt: skip
TEST_DIRS = {"tests", "test", "__tests__", "spec", "e2e", "fixtures", "fixture", "testdata"}
MAX_BYTES = 1_000_000

# --- secret-looking names --------------------------------------------------------------------

SECRET_WORDS = {
    "password", "passwd", "passphrase", "secret", "token", "apikey", "authorization",
    "cookie", "credential", "credentials", "bearer",
}  # fmt: skip
SECRET_PAIRS = {
    ("api", "key"), ("private", "key"), ("access", "key"), ("secret", "key"),
    ("client", "secret"),
}  # fmt: skip
# A name that also holds one of these describes a secret without being one: token_count.
DESCRIBES = {
    "count", "counts", "len", "length", "size", "type", "types", "name", "names", "kind",
    "path", "paths", "file", "files", "dir", "url", "uri", "env", "var", "field", "label",
    "limit", "budget", "usage", "total", "prefix", "hint", "present", "exists", "missing",
    "set", "ok", "is", "has", "expiry", "expires", "ttl", "scope", "scopes", "id", "ids",
    "per", "char", "chars",
}  # fmt: skip
# A call or method that turns a secret into something safe to log.
SAFE_CALLS = {
    "len", "bool", "type", "isinstance", "hasattr", "id", "redact", "redacted", "mask",
    "masked", "fingerprint", "is_empty", "is_some", "is_none", "count", "length", "size",
    "hash", "startswith", "endswith", "starts_with", "ends_with", "startsWith", "endsWith",
}  # fmt: skip
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def words(name: str) -> list[str]:
    return [w.lower() for part in re.split(r"[^A-Za-z0-9]+", name) for w in _CAMEL.findall(part)]


def describes(name: str) -> bool:
    """The name describes a value (token_count, api_key_set) rather than holding it."""
    return any(w in DESCRIBES for w in words(name))


@lru_cache(maxsize=65536)
def secret_like(name: str) -> bool:
    ws = words(name)
    # The "id" of id_token names the kind of token; it does not describe it as an id.
    ws_described = [
        w for i, w in enumerate(ws) if not (w == "id" and ws[i + 1 : i + 2] == ["token"])
    ]
    if any(w in DESCRIBES for w in ws_described):
        return False
    return any(w in SECRET_WORDS for w in ws) or any(p in SECRET_PAIRS for p in pairwise(ws))


# --- findings and suppression ----------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str


_IGNORE = re.compile(r"logcheck:\s*ignore(?:\[([^\]]*)\])?")


def suppressed(lines: list[str], first: int, last: int, rule: str) -> bool:
    """A `logcheck: ignore` comment on any line from first to last (1-based) covers rule."""
    for text in lines[first - 1 : last]:
        for m in _IGNORE.finditer(text):
            if m.group(1) is None or rule in {r.strip() for r in m.group(1).split(",")}:
                return True
    return False


class Report:
    def __init__(self, ignored: set[str]) -> None:
        self.ignored = ignored
        self.items: set[Finding] = set()

    def add(self, path: str, line: int, rule: str, message: str) -> None:
        if rule not in self.ignored:
            self.items.add(Finding(path, line, rule, message))

    def add_line(
        self, path: str, lines: list[str], span: tuple[int, int], rule: str, message: str
    ) -> None:
        if not suppressed(lines, span[0], span[1], rule):
            self.add(path, span[0], rule, message)


# --- the repository --------------------------------------------------------------------------


class NotARepo(Exception):
    pass


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        env=without_repo_overrides(),
        check=False,
    )
    if done.returncode != 0:
        lines = done.stderr.decode(errors="replace").strip().splitlines()
        raise NotARepo(lines[0] if lines else f"git exited {done.returncode}")
    return done.stdout.decode("utf-8", errors="surrogateescape")


def toplevel(path: Path) -> Path:
    if not path.is_dir():
        raise NotARepo("no such directory")
    return Path(git(path, "rev-parse", "--show-toplevel").strip())


def settings(root: Path) -> tuple[set[str], tuple[str, ...]]:
    """The ignored rules and skipped path prefixes from the skill-context `## logging` section."""
    context = root / ".claude" / "skill-context.md"
    text = read_path(context)
    if text is None:
        if os.path.lexists(context):
            warn(f"{context} is not a readable regular file; its ## logging section is left out")
        return set(), ()
    section = re.search(r"^## logging[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    ignored: set[str] = set()
    skip: list[str] = []
    for line in section.group(1).splitlines() if section else []:
        m = re.match(r"\s*-\s*(ignore|skip)\s*:\s*(.*)", line)
        if not m:
            continue
        if "<" in m.group(2):
            warn(f"## logging: {line.strip()!r} is still the template's placeholder; left out")
            continue
        value = re.split(r"\s+(?:—|--)\s+|\s+\(|\s+#", m.group(2), maxsplit=1)[0]
        items = [v for v in re.split(r"[,\s]+", value) if v]
        if m.group(1) == "ignore":
            for v in items:
                if v in RULES:
                    ignored.add(v)
                else:
                    warn(f"## logging: {v!r} is not a logcheck rule; left out")
        else:
            skip += [v.removeprefix("./") for v in items]
    return ignored, tuple(skip)


def warn(message: str) -> None:
    print(f"logcheck: {message}", file=sys.stderr)


def tracked(root: Path, skip: tuple[str, ...]) -> list[str]:
    paths = [p for p in git(root, "ls-files", "-z").split("\0") if p]
    keep = []
    for p in paths:
        parts = PurePosixPath(p).parts
        if VENDORED & set(parts[:-1]) or p.endswith(".min.js"):
            continue
        if any(p == s.rstrip("/") or p.startswith(s if s.endswith("/") else s + "/") for s in skip):
            continue
        keep.append(p)
    return sorted(keep)


def is_test(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    return bool(
        TEST_DIRS & set(p.parts[:-1])
        or name == "conftest.py"
        or (name.startswith("test_") and name.endswith(".py"))
        or name.endswith(("_test.py", "_test.rs", "_test.go"))
        or re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", name)
    )


def read(root: Path, path: str) -> str | None:
    return read_path(root / path)


def read_path(full: Path) -> str | None:
    """The file's text, or None for a symlink, anything but a regular file, a file over
    MAX_BYTES, or one that is not UTF-8. Every file the check opens goes through here."""
    try:
        info = os.lstat(full)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            return None
        with open(full, "rb") as handle:
            data = handle.read(MAX_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# --- lint-python -----------------------------------------------------------------------------


def _table(data: object, key: str) -> dict:
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


def _toml(path: Path) -> dict | None:
    text = read_path(path)
    if text is None:
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None


def _ruff_table(path: Path) -> dict | None:
    """The ruff settings in path, or None when path holds none (or does not parse)."""
    data = _toml(path)
    if data is None:
        return None
    if path.name == "pyproject.toml":
        tool = data.get("tool")
        ruff = tool.get("ruff") if isinstance(tool, dict) else None
        return ruff if isinstance(ruff, dict) else None
    return data


def ruff_config(root: Path, directory: PurePosixPath) -> Path | None:
    """The config ruff uses for files in directory: the closest one up to the repo root."""
    d = directory
    while True:
        for name in (".ruff.toml", "ruff.toml", "pyproject.toml"):
            candidate = root / d / name
            if candidate.is_file() and _ruff_table(candidate) is not None:
                return candidate
        if d == PurePosixPath("."):
            return None
        d = d.parent


def _str_list(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


RUFF_DEFAULT = frozenset({"E4", "E7", "E9", "F"})


def ruff_selection(config: Path, depth: int = 0) -> tuple[set[str], set[str]]:
    """(selected, ignored) rule selectors after select, extend-select, ignore and `extend`
    chains. Both are returned because "ALL" with "G" ignored still selects "ALL"."""
    table = _ruff_table(config) or {}
    chosen, ignored = set(RUFF_DEFAULT), set()
    parent = table.get("extend")
    if isinstance(parent, str) and depth < 8:
        target = (config.parent / parent).resolve()
        if target.is_file():
            chosen, ignored = ruff_selection(target, depth + 1)
    lint = _table(table, "lint")

    def key(name: str) -> list[str] | None:
        for t in (lint, table):
            if name in t:
                return _str_list(t[name])
        return None

    select = key("select")
    if select is not None:
        chosen = set(select)
    chosen |= set(key("extend-select") or [])
    ignored |= set(key("ignore") or [])
    return chosen, ignored


def check_lint_python(root: Path, files: list[str], report: Report) -> None:
    groups: dict[str, Path | None] = {}
    for f in files:
        if f.endswith(".py"):
            config = ruff_config(root, PurePosixPath(f).parent)
            groups[str(config) if config else ""] = config
    for config in groups.values():
        chosen, ignored = ruff_selection(config) if config else (set(RUFF_DEFAULT), set())
        missing = [
            fam
            for fam in ("G", "LOG")
            if fam in ignored or ("ALL" not in chosen and fam not in chosen)
        ]
        if not missing:
            continue
        rel = config.relative_to(root).as_posix() if config else "pyproject.toml"
        names = ", ".join(f'"{m}"' for m in missing)
        report.add(
            rel,
            1,
            "lint-python",
            f"ruff does not select {names} → add {'it' if len(missing) == 1 else 'them'} to "
            "select (logging format, root logger and exc_info rules)",
        )


# --- lint-rust -------------------------------------------------------------------------------

CLIPPY = ("print_stdout", "print_stderr", "dbg_macro")


def _level(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("level")
    return value if isinstance(value, str) else None


def check_lint_rust(root: Path, files: list[str], report: Report) -> None:
    manifests = [f for f in files if PurePosixPath(f).name == "Cargo.toml"]
    for m in manifests:
        data = _toml(root / m)
        if not data or "package" not in data:
            continue
        lints = _table(data, "lints")
        clippy = _table(lints, "clippy")
        if lints.get("workspace") is True:
            clippy = workspace_clippy(root, PurePosixPath(m).parent)
        missing = [k for k in CLIPPY if _level(clippy.get(k)) not in {"warn", "deny", "forbid"}]
        if missing:
            report.add(
                m,
                1,
                "lint-rust",
                f'clippy does not warn on {", ".join(missing)} → set them to "warn" under '
                "[lints.clippy] (or [workspace.lints.clippy]) so stray prints fail lint",
            )


def workspace_clippy(root: Path, member: PurePosixPath) -> dict:
    """[workspace.lints.clippy] from the closest Cargo.toml with a [workspace], the member's
    own included."""
    for d in (member, *member.parents):
        data = _toml(root / d / "Cargo.toml")
        if data and "workspace" in data:
            return _table(_table(_table(data, "workspace"), "lints"), "clippy")
    return {}


# --- lint-js ---------------------------------------------------------------------------------

JS_EXT = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx", ".jsx", ".vue", ".svelte", ".astro")
ESLINT_ON = re.compile(r"""["']?no-console["']?\s*:\s*\[?\s*(?:["'](?:warn|error)["']|[12]\b)""")
BIOME_ON = re.compile(
    r"""["']noConsole["']\s*:\s*(?:["'](?:on|info|warn|error)["']|"""
    r"""\{[^}]*["']level["']\s*:\s*["'](?:on|info|warn|error)["'])"""
)


def is_js_config(name: str) -> bool:
    return bool(re.match(r"^(eslint\.config|\.eslintrc)(\.[\w]+)?$|^biome\.jsonc?$", name))


def is_js_source(path: str) -> bool:
    name = PurePosixPath(path).name
    return (
        path.endswith(JS_EXT)
        and not name.endswith(".d.ts")
        and ".config." not in name
        and not is_test(path)
    )


def check_lint_js(root: Path, files: list[str], report: Report) -> None:
    """Each package (a package.json folder) holding JS or TS source needs a no-console rule
    in its own folder or one above it. Source outside every package has no lint toolchain to
    add the rule to, so it is left out."""
    packages = {PurePosixPath(f).parent for f in files if PurePosixPath(f).name == "package.json"}
    on = set()
    for f in files:
        name = PurePosixPath(f).name
        if is_js_config(name) or name == "package.json":
            text = read(root, f) or ""
            if ESLINT_ON.search(text) or BIOME_ON.search(text):
                on.add(PurePosixPath(f).parent)
    flagged = set()
    for f in files:
        if not is_js_source(f):
            continue
        dirs = [*PurePosixPath(f).parents]
        package = next((d for d in dirs if d in packages), None)
        if package is None or package in flagged or any(d in on for d in dirs):
            continue
        flagged.add(package)
        report.add(
            (package / "package.json").as_posix(),
            1,
            "lint-js",
            "no lint rule bans console.log → enable ESLint no-console (allow warn and error) "
            "or Biome noConsole, and log through one level-gated logger",
        )


# --- code scanning shared by Rust and JS -----------------------------------------------------


RAW_STRING = re.compile(r'r(#*)"')
RS_CHAR = re.compile(r"'(?:\\(?:x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]{1,6}\}|.)|[^\\'\n])'")


def mask(text: str, lang: str) -> tuple[str, list[tuple[int, int]]]:
    """text with comments blanked and string contents replaced by spaces (newlines kept),
    plus the (start, end) spans of every string literal's contents. JS template literal
    `${...}` expressions are kept as code."""
    out = list(text)
    strings: list[tuple[int, int]] = []
    i, n = 0, len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(i, j)
            i = j
        elif (
            lang == "rs"
            and c == "r"
            and (opener := RAW_STRING.match(text, i))
            and not re.match(r"\w", text[i - 1 : i])
        ):
            hashes = opener.group(1)
            start = i + 2 + len(hashes)
            j = text.find('"' + hashes, start)
            j = n if j == -1 else j
            strings.append((start, j))
            blank(start, j)
            i = j + 1 + len(hashes)
        elif lang == "rs" and c == "'" and (char := RS_CHAR.match(text, i)):
            blank(i + 1, char.end() - 1)
            i = char.end()
        elif c == '"' or (lang == "js" and c in "'`"):
            quote = c
            j = i + 1
            seg = j
            # A JS quote that is not closed on its line is markup or a regex, not a string.
            line_bound = lang == "js" and quote != "`"
            while j < n and text[j] != quote and not (line_bound and text[j] == "\n"):
                if text[j] == "\\":
                    j += 2
                    continue
                if quote == "`" and text.startswith("${", j):
                    strings.append((seg, j))
                    blank(seg, j)
                    depth, j = 1, j + 2
                    while j < n and depth:
                        depth += {"{": 1, "}": -1}.get(text[j], 0)
                        j += 1
                    seg = j
                    continue
                j += 1
            strings.append((seg, min(j, n)))
            blank(seg, min(j, n))
            i = j + 1
        else:
            i += 1
    return "".join(out), strings


BRACKETS = re.compile(r"[()\[\]{};]")


def bracket_pairs(code: str) -> dict[int, int]:
    """For each opening bracket in code, the index of the bracket that closes it, found in
    one pass. A `(` still open at a `;` outside any `{}` or `[]` ends there, since no valid
    argument list holds one; a bracket never closed ends at the end of its own line."""
    pairs: dict[int, int] = {}
    stack: list[int] = []
    for m in BRACKETS.finditer(code):
        k, c = m.start(), m.group(0)
        if c in "([{":
            stack.append(k)
        elif c == ";":
            while stack and code[stack[-1]] == "(":
                pairs[stack.pop()] = k
        elif stack:
            pairs[stack.pop()] = k
    for k in stack:
        newline = code.find("\n", k)
        pairs[k] = len(code) if newline == -1 else newline
    return pairs


class LineIndex:
    """1-based line numbers of offsets in a text, by binary search."""

    def __init__(self, text: str) -> None:
        self.newlines = [m.start() for m in re.finditer("\n", text)]

    def of(self, offset: int) -> int:
        return bisect_left(self.newlines, offset) + 1


CHAIN = re.compile(r"[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*")


NEXT = re.compile(r"\s*(\S?)(\S?)")
VALUE_START = re.compile(r"\s*[%?&*]*\s*")


COMPARISON = re.compile(r"\s*(?:[=!]==?|[<>]=?)(?!>)")
BEFORE_COMPARISON = re.compile(r"(?:[=!]==?|(?<![=\-<>])[<>]=?)\s*$")


def secret_names(
    code: str,
    span: tuple[int, int],
    pairs: dict[int, int],
    raw_strings: list[str],
    inline: re.Pattern[str],
    lang: str = "rs",
) -> list[str]:
    """Secret-looking names in an argument list: code identifier chains and the names a
    string interpolates (Rust `{name}`, JS template `${name}` is already code). A field
    name (`token = %v`, `{token: v}`) counts only when its value is not a literal or a
    safe call."""
    hits = []
    at, end = span
    while m := CHAIN.search(code, at, end):
        at = m.end()
        parts = [p.strip() for p in m.group(0).split(".")]
        nxt = NEXT.match(code, m.end(), end)
        first, second = (nxt.group(1), nxt.group(2)) if nxt else ("", "")
        if lang == "rs" and first == "!":  # a nested macro name
            continue
        if COMPARISON.match(code, m.end(), end) or BEFORE_COMPARISON.search(
            code, max(span[0], m.start() - 8), m.start()
        ):
            continue  # token == expected, user.password === undefined: a boolean
        if lang == "js" and first == "?" and second not in {".", "?"}:
            continue  # token ? "set" : "unset": the test of a conditional
        if first == "(" and parts[-1] in SAFE_CALLS:
            # len(token), redact(&key), key.len(): the call's result is safe to log.
            paren = code.index("(", m.end(), end)
            at = pairs.get(paren, end) + 1
            continue
        if (first == "=" and second != "=") or (first == ":" and second != ":"):
            if (
                len(parts) == 1
                and secret_like(parts[0])
                and not safe_value(code, nxt.start(1) if nxt else at)
            ):
                hits.append(parts[0])
            continue
        if secret_like(parts[-1]) and not (len(parts) == 1 and first == "("):
            hits.append(parts[-1])
    for s in raw_strings:
        hits += [name for name in inline.findall(s) if secret_like(name)]
    return hits


def safe_value(code: str, eq: int) -> bool:
    """The value after the `=` or `:` at eq is a literal (blanked string, number) or a safe
    call."""
    start = VALUE_START.match(code, eq + 1)
    k = start.end() if start else eq + 1
    if k >= len(code) or code[k] in "\"'`0123456789":
        return True
    call = CHAIN.match(code, k)
    if not call:
        return False
    # tokenCount, token.length, len(token), redact(t)
    last = call.group(0).split(".")[-1].strip()
    return describes(last) or last in SAFE_CALLS


# --- Rust ------------------------------------------------------------------------------------

RS_MACRO = re.compile(
    r"\b(?:(?:tracing|log)\s*::\s*)?(trace|debug|info|warn|error|println|eprintln|print|eprint|dbg)!\s*\("
)
RS_INLINE = re.compile(r"(?<!\{)\{([A-Za-z_]\w*)[^}]*\}")


def without_test_items(code: str) -> str:
    """code with each item under #[cfg(test)] blanked: through its closing brace, or its
    semicolon for `mod tests;`."""
    out = list(code)
    for m in re.finditer(r"#\[cfg\(test\)\]", code):
        brace, semi = code.find("{", m.end()), code.find(";", m.end())
        if brace == -1 and semi == -1:
            continue
        if brace == -1 or (semi != -1 and semi < brace):
            end = semi
        else:
            depth, end = 0, len(code) - 1
            for k in range(brace, len(code)):
                depth += {"{": 1, "}": -1}.get(code[k], 0)
                if depth == 0:
                    end = k
                    break
        for k in range(m.start(), end + 1):
            if out[k] != "\n":
                out[k] = " "
    return "".join(out)


def scan_rust(path: str, text: str, report: Report) -> None:
    lines = text.splitlines()
    index = LineIndex(text)
    code, strings = mask(text, "rs")
    code = without_test_items(code)
    pairs = bracket_pairs(code)
    starts = [a for a, _ in strings]
    for m in RS_MACRO.finditer(code):
        open_at = m.end() - 1
        end = pairs.get(open_at, len(code))
        inside = strings[bisect_right(starts, open_at) : bisect_left(starts, end)]
        raw = [text[a:b] for a, b in inside]
        if secret_names(code, (open_at + 1, end), pairs, raw, RS_INLINE):
            span = (index.of(m.start()), index.of(end))
            report.add_line(path, lines, span, "secret-in-log", SECRET_MSG)
    unbounded = (
        (r"\brolling\s*::\s*(daily|hourly|minutely|never)\s*\(", ROLLING_MSG),
        (r"\bRollingFileAppender\s*::\s*new\s*\(", ROLLING_MSG),
        (r"\bRotationStrategy\s*::\s*KeepAll\b", KEEPALL_MSG),
        (r"\bRotation\s*::\s*NEVER\b", NEVER_MSG),
    )
    for pattern, message in unbounded:
        for m in re.finditer(pattern, code):
            line = index.of(m.start())
            report.add_line(path, lines, (line, line), "unbounded-log-file", message)
    builders = (
        r"\bRollingFileAppender\s*::\s*builder\s*\(\s*\)"
        r"|\brolling\s*::\s*Builder\s*::\s*new\s*\(\s*\)"
    )
    for m in re.finditer(builders, code):
        stop = code.find(";", m.end())
        stop = len(code) if stop == -1 else stop
        if ".max_log_files" not in re.sub(r"\s+", "", code[m.end() : stop]):
            span = (index.of(m.start()), index.of(stop))
            report.add_line(path, lines, span, "unbounded-log-file", BUILDER_MSG)


SECRET_MSG = "a secret-looking value reaches a log call → log a redacted form, a length or nothing"
ROLLING_MSG = (
    "this tracing-appender constructor keeps every file it rolls → use "
    "RollingFileAppender::builder() with .max_log_files(n)"
)
BUILDER_MSG = "RollingFileAppender::builder() without .max_log_files(n) keeps every file"
NEVER_MSG = (
    "Rotation::NEVER writes one file that never rotates → use DAILY or HOURLY with "
    ".max_log_files(n)"
)
KEEPALL_MSG = "RotationStrategy::KeepAll keeps every rotated file → use KeepSome(n)"

# --- JS and TS -------------------------------------------------------------------------------

JS_CALL = re.compile(
    r"(?<![\w$])([A-Za-z_$][\w$]*)\s*\.\s*(log|info|debug|warn|error|trace|fatal)\s*\("
)


def scan_js(path: str, text: str, report: Report) -> None:
    lines = text.splitlines()
    index = LineIndex(text)
    code, _ = mask(text, "js")
    pairs = bracket_pairs(code)
    for m in JS_CALL.finditer(code):
        receiver = m.group(1)
        if receiver != "console" and not {"log", "logger"} & set(words(receiver)):
            continue
        open_at = m.end() - 1
        end = pairs.get(open_at, len(code))
        if secret_names(code, (open_at + 1, end), pairs, [], RS_INLINE, "js"):
            span = (index.of(m.start()), index.of(end))
            report.add_line(path, lines, span, "secret-in-log", SECRET_MSG)


# --- Python ----------------------------------------------------------------------------------

LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log"}
HANDLERS = {"FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler"}


def terminal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return terminal(node.func)
    return None


def is_py_log_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == "print"
    if not isinstance(func, ast.Attribute):
        return False
    receiver = terminal(func.value) or ""
    if func.attr in LOG_METHODS and {"log", "logger", "logging"} & set(words(receiver)):
        return True
    if func.attr == "echo" and receiver in {"click", "typer"}:
        return True
    if func.attr in {"print", "log"} and receiver == "console":
        return True
    return func.attr == "write" and receiver in {"stderr", "stdout"}


PREDICATE = re.compile(r"^(?:is|has)_|^(?:is|has)[A-Z]|^is(?:alnum|alpha|digit|lower|upper|space)$")


def py_secret(node: ast.AST) -> bool:
    if isinstance(node, ast.Compare | ast.Constant):
        return False
    if isinstance(node, ast.IfExp):  # "set" if token else "unset": the test is not logged
        return py_secret(node.body) or py_secret(node.orelse)
    if isinstance(node, ast.Call):
        name = terminal(node.func) or ""
        if name in SAFE_CALLS or PREDICATE.match(name):
            return False
        receiver = [node.func.value] if isinstance(node.func, ast.Attribute) else []
        parts = [*receiver, *node.args, *(k.value for k in node.keywords)]
        return any(py_secret(p) for p in parts)
    if isinstance(node, ast.Name):
        return secret_like(node.id)
    if isinstance(node, ast.Attribute):
        return secret_like(node.attr)
    if isinstance(node, ast.Dict):  # extra={"token": tok}
        for k, v in zip(node.keys, node.values, strict=True):
            named = (
                isinstance(k, ast.Constant) and isinstance(k.value, str) and secret_like(k.value)
            )
            if (named and not safe_py_value(v)) or py_secret(v):
                return True
        return False
    if isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and secret_like(key.value):
            return True
        return py_secret(node.value)
    return any(py_secret(child) for child in ast.iter_child_nodes(node))


def safe_py_value(node: ast.expr) -> bool:
    """A value is safe to log under a secret-looking name: a literal, a comparison, a safe
    call, a name that describes the secret (token_count), or an if-expression whose
    branches are all safe."""
    if isinstance(node, ast.Constant | ast.Compare):
        return True
    if isinstance(node, ast.IfExp):
        return safe_py_value(node.body) and safe_py_value(node.orelse)
    if isinstance(node, ast.Call):
        return (terminal(node.func) or "") in SAFE_CALLS
    if isinstance(node, ast.Name | ast.Attribute):
        return describes(terminal(node) or "")
    return False


def _arg(call: ast.Call, name: str, position: int) -> ast.expr | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return call.args[position] if len(call.args) > position else None


def _zero(node: ast.expr | None) -> bool:
    """Missing, or a literal 0. A variable counts as set."""
    return node is None or (isinstance(node, ast.Constant) and node.value == 0)


def handler_message(kind: str, get: dict[str, ast.expr | None]) -> str | None:
    if kind == "FileHandler":
        return (
            "logging.FileHandler grows without a cap → use "
            "RotatingFileHandler(maxBytes=..., backupCount=...)"
        )
    if kind == "RotatingFileHandler" and (_zero(get["maxBytes"]) or _zero(get["backupCount"])):
        return "RotatingFileHandler never rotates unless maxBytes and backupCount are both set"
    if kind == "TimedRotatingFileHandler" and _zero(get["backupCount"]):
        return "TimedRotatingFileHandler without backupCount keeps every file → set backupCount"
    return None


def scan_python(path: str, text: str, report: Report) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return
    lines = text.splitlines()
    for node in ast.walk(tree):
        span = (getattr(node, "lineno", 1), getattr(node, "end_lineno", None) or 1)
        if isinstance(node, ast.Call):
            if is_py_log_call(node):
                args = [*node.args, *(k.value for k in node.keywords)]
                # structlog style: log.info("login", password=pw) logs the value under the name.
                named = [k for k in node.keywords if k.arg and secret_like(k.arg)]
                if any(py_secret(a) for a in args) or any(
                    not safe_py_value(k.value) for k in named
                ):
                    report.add_line(path, lines, span, "secret-in-log", SECRET_MSG)
            kind = terminal(node.func)
            if kind in HANDLERS:
                message = handler_message(
                    kind,
                    {
                        "maxBytes": _arg(node, "maxBytes", 2),
                        "backupCount": _arg(node, "backupCount", 3),
                    },
                )
                if message:
                    report.add_line(path, lines, span, "unbounded-log-file", message)
            if kind == "basicConfig" and any(k.arg == "filename" for k in node.keywords):
                message = (
                    "basicConfig(filename=...) writes one file without a cap → attach a "
                    "RotatingFileHandler instead"
                )
                report.add_line(path, lines, span, "unbounded-log-file", message)
        elif isinstance(node, ast.Dict):
            entries = {
                k.value: v
                for k, v in zip(node.keys, node.values, strict=True)
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            cls = entries.get("class")
            if isinstance(cls, ast.Constant) and isinstance(cls.value, str):
                kind = cls.value.rsplit(".", 1)[-1]
                if kind in HANDLERS:
                    message = handler_message(
                        kind,
                        {
                            "maxBytes": entries.get("maxBytes"),
                            "backupCount": entries.get("backupCount"),
                        },
                    )
                    if message:
                        report.add_line(path, lines, span, "unbounded-log-file", message)


# --- shell and workflow run blocks -----------------------------------------------------------

SH_OPERATORS = re.compile(r"\|\||&&|;|\||\$\(|\(|\)|`")
ERROR_START = re.compile(
    r"^(?:-[neE]+\s+)*(?:\S+:\s*)?(?:error|fatal|fail|failed|failure|warn|warning)\s*:",
    re.I,
)
GROUP_TO_STDERR = re.compile(r"\}\s*(?:1?>&2|>\s*/dev/stderr)")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")
TO_STDERR = re.compile(r"(?:^|\s)(?:1?>&2|>\s*/dev/stderr)")
TO_FILE = re.compile(r"(?:^|[^&\d])>>?\s*(?!&)(?!/dev/std(?:out|err))\S")
EXPANSION = re.compile(r"\$\{?(?!#)([A-Za-z_][A-Za-z0-9_]*)")
GHA_SECRET = re.compile(r"\$\{\{\s*secrets\.")


def unquote(text: str) -> str:
    return re.sub(r"""["']""", "", text)


def outside_quotes(text: str, keep_double: bool = False) -> str:
    """text with quoted contents blanked: single-quoted always, double-quoted unless
    keep_double (the shell expands $NAME inside double quotes, not inside single ones)."""
    out, quote, escaped = [], "", False
    for c in text:
        if escaped:  # \' or \" outside quotes is a literal character
            out.append(" ")
            escaped = False
        elif c == "\\" and not quote:
            out.append(" ")
            escaped = True
        elif quote:
            out.append(c if quote == '"' and keep_double else " ")
            if c == quote:
                quote = ""
        elif c in "'\"":
            quote = c
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)


def commands(line: str) -> list[tuple[str, str]]:
    """(command text, the operator that ends it) for each command on a shell line, splitting
    on operators outside quotes. The comment after an unquoted # is dropped."""
    out, buf, quote = [], [], ""
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = ""
            elif c == "\\" and quote == '"' and i + 1 < len(line):
                buf.append(line[i + 1])
                i += 1
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif c == "#" and (not buf or buf[-1].isspace()):
            break
        else:
            m = SH_OPERATORS.match(line, i)
            if m and not (m.group(0) == "|" and line.startswith("|&", i)):
                op = m.group(0)
                if not (op == "(" and buf and buf[-1] == "$"):
                    out.append(("".join(buf), op))
                    buf = []
                    i += len(op)
                    continue
            buf.append(c)
        i += 1
    out.append(("".join(buf), ""))
    return out


def logical_lines(texts: dict[int, str]) -> list[tuple[str, tuple[int, int]]]:
    """Join each line ending in a backslash with the next one, so a command continued over
    several lines is read whole. texts maps 1-based line numbers to their shell text."""
    numbers = sorted(texts)
    out = []
    k = 0
    while k < len(numbers):
        first = last = numbers[k]
        text = texts[first]
        while text.rstrip().endswith("\\") and k + 1 < len(numbers) and numbers[k + 1] == last + 1:
            k += 1
            last = numbers[k]
            text = text.rstrip()[:-1] + " " + texts[last].strip()
        out.append((text, (first, last)))
        k += 1
    return out


def scan_shell_line(
    path: str,
    lines: list[str],
    line: str,
    span: tuple[int, int],
    workflow: bool,
    report: Report,
    grouped: bool = False,
) -> None:
    """grouped: the line sits in a `{ ...; } >&2` group, so all its output goes to stderr."""
    if not grouped and GROUP_TO_STDERR.search(outside_quotes(line)):
        grouped = True
    for cmd, op in commands(line):
        m = re.match(r"\s*(?:then\s+|do\s+|else\s+|\{\s*)?(echo|printf)\b(.*)", cmd)
        if not m or "::add-mask::" in cmd:
            continue
        rest = m.group(2)
        bare = outside_quotes(rest)
        to_stderr = grouped or bool(TO_STDERR.search(bare))
        if op == "|" or (TO_FILE.search(bare) and not to_stderr):
            continue
        # Secrets reach a shell as environment variables, named in capitals; a lowercase
        # $token is a local word (a parsed field, a platform name).
        expanded = EXPANSION.findall(outside_quotes(rest, True))
        names = [n for n in expanded if n.isupper() and secret_like(n)]
        if names or (workflow and GHA_SECRET.search(rest)):
            report.add_line(path, lines, span, "secret-in-log", SECRET_MSG)
        text = unquote(rest.strip())
        if text.startswith("::") or (to_stderr and not workflow):
            continue
        if ERROR_START.match(text):
            message = (
                'error text goes to the plain log → print it with echo "::error::..." so the '
                "run's annotations name it"
                if workflow
                else "error text goes to stdout → send it to stderr with >&2"
            )
            report.add_line(path, lines, span, "stderr-for-errors", message)


def is_shell(path: str, text: str) -> bool:
    if path.endswith((".sh", ".bash")):
        return True
    first = text.split("\n", 1)[0]
    return "." not in PurePosixPath(path).name and bool(
        re.match(r"#!\s*\S*(?:/|\s)(?:env\s+)?(?:ba|z|da|k)?sh\b", first)
    )


ARITHMETIC = re.compile(r"\$?\(\([^)]*\)\)")
HEREDOC_START = re.compile(r"(?<!<)<<-?(?!<)")


def code_part(line: str) -> str:
    """line with quoted text blanked (same length) and any comment cut off."""
    bare = outside_quotes(line)
    comment = re.search(r"(?:^|\s)#", bare)
    return (bare[: comment.start()] if comment else bare).rstrip()


def shell_text(texts: dict[int, str]) -> tuple[dict[int, str], set[int]]:
    """texts without heredoc bodies, and the lines inside a multi-line `{ ... } >&2` group."""
    kept: dict[int, str] = {}
    grouped: set[int] = set()
    opened: list[int] = []
    numbers = sorted(texts)
    k = 0
    while k < len(numbers):
        n = numbers[k]
        line = texts[n]
        kept[n] = line
        bare = code_part(line)
        if bare.endswith("{"):
            opened.append(n)
        elif bare.lstrip().startswith("}") and opened:
            first = opened.pop()
            if GROUP_TO_STDERR.search(bare):
                grouped |= {m for m in numbers if first < m < n}
        # Find << in the code part (no quotes, comment or arithmetic), then read the
        # delimiter, which may itself be quoted, from the line at the same place.
        at = HEREDOC_START.search(ARITHMETIC.sub(lambda a: " " * len(a.group(0)), bare))
        doc = HEREDOC.match(line, at.start()) if at else None
        if doc:
            word = doc.group(2)
            k += 1
            while k < len(numbers) and texts[numbers[k]].strip() != word:
                k += 1
        k += 1
    return kept, grouped


def scan_shell(path: str, text: str, report: Report) -> None:
    lines = text.splitlines()
    kept, grouped = shell_text(dict(enumerate(lines, 1)))
    for line, span in logical_lines(kept):
        scan_shell_line(path, lines, line, span, False, report, span[0] in grouped)


# --- workflows -------------------------------------------------------------------------------

RUN_KEY = re.compile(r"^(\s*)(?:-\s+)?run:\s*(.*)$")
WRITES_LOG = re.compile(
    r"\btee\s+(?:-a\s+)?[\"']?[^\s|;&\"']*\.log\b|>>?\s*[\"']?[^\s|;&\"']*\.log\b|--log-file[= ]"
)
UPLOAD = re.compile(r"\buses:\s*[\"']?actions/upload-artifact@")
ON_FAILURE = re.compile(r"^\s*(?:-\s+)?if:.*(?:failure\(\)|always\(\)|!\s*cancelled\(\))")


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def run_blocks(lines: list[str]) -> list[dict[int, str]]:
    """The shell text of each `run:` key, by 1-based line number, one dict per key."""
    blocks: list[dict[int, str]] = []
    i = 0
    while i < len(lines):
        m = RUN_KEY.match(lines[i])
        if not m:
            i += 1
            continue
        value = m.group(2).strip()
        if re.fullmatch(r"[|>][+-]?\d*", value):
            key_indent = indent(lines[i])
            found: dict[int, str] = {}
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or indent(lines[j]) > key_indent):
                if lines[j].strip():
                    found[j + 1] = lines[j]
                j += 1
            blocks.append(found)
            i = j
        else:
            if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            if value:
                blocks.append({i + 1: value})
            i += 1
    return blocks


def jobs(lines: list[str]) -> list[tuple[str, int, int]]:
    """(name, first line index, end index) for each job under the top-level `jobs:` key."""
    start = next((i for i, ln in enumerate(lines) if re.match(r"^jobs:\s*(#.*)?$", ln)), None)
    if start is None:
        return []
    body = [
        i
        for i in range(start + 1, len(lines))
        if lines[i].strip() and not lines[i].lstrip().startswith("#")
    ]
    end_jobs = next((i for i in body if indent(lines[i]) == 0), len(lines))
    body = [i for i in body if i < end_jobs]
    if not body:
        return []
    job_indent = indent(lines[body[0]])
    heads = [
        i for i in body if indent(lines[i]) == job_indent and re.match(r"\s*[\w.-]+\s*:", lines[i])
    ]
    return [
        (lines[h].strip().split(":", 1)[0], h, heads[k + 1] if k + 1 < len(heads) else end_jobs)
        for k, h in enumerate(heads)
    ]


def uploads_on_failure(lines: list[str], start: int, end: int) -> bool:
    """An upload-artifact step under an if: failure(), always() or !cancelled() between line
    index start (the first step that writes a log) and end."""
    for i in range(start, end):
        if not UPLOAD.search(lines[i]):
            continue
        # The step is the nearest list item above at a smaller indent, through its last line.
        head = next(
            (
                h
                for h in range(i, start - 1, -1)
                if re.match(r"^\s*-\s", lines[h]) and indent(lines[h]) <= indent(lines[i])
            ),
            i,
        )
        step_indent = indent(lines[head])
        tail = head + 1
        while tail < end and (not lines[tail].strip() or indent(lines[tail]) > step_indent):
            tail += 1
        if any(ON_FAILURE.match(lines[k]) for k in range(head, tail)):
            return True
    return False


def scan_workflow(path: str, text: str, report: Report) -> None:
    lines = text.splitlines()
    shell: dict[int, str] = {}
    for block in run_blocks(lines):
        kept, _ = shell_text(block)
        shell.update(kept)
        for line, span in logical_lines(kept):
            scan_shell_line(path, lines, line, span, True, report)
    for name, start, end in jobs(lines):
        writes = [n for n in shell if start < n <= end and WRITES_LOG.search(lines[n - 1])]
        if writes and not uploads_on_failure(lines, writes[0], end):
            report.add_line(
                path,
                lines,
                (writes[0], writes[0]),
                "ci-logs-not-uploaded",
                f"job {name} writes a log file but uploads none when it fails → add "
                "actions/upload-artifact with if: failure()",
            )


# --- the check -------------------------------------------------------------------------------


def check(root: Path) -> list[Finding]:
    ignored, skip = settings(root)
    files = tracked(root, skip)
    report = Report(ignored)
    check_lint_python(root, files, report)
    check_lint_rust(root, files, report)
    check_lint_js(root, files, report)
    check_log_files(files, report)
    for f in files:
        name = PurePosixPath(f).name
        if f.endswith(".log"):
            continue
        workflow = f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))
        if is_test(f) and not workflow:
            continue
        if not (workflow or f.endswith((".py", ".rs", ".sh", ".bash", *JS_EXT)) or "." not in name):
            continue
        text = read(root, f)
        if text is None:
            continue
        try:
            if workflow:
                scan_workflow(f, text, report)
            elif f.endswith(".py"):
                scan_python(f, text, report)
            elif f.endswith(".rs"):
                scan_rust(f, text, report)
            elif is_js_source(f):
                scan_js(f, text, report)
            elif is_shell(f, text):
                scan_shell(f, text, report)
        except (RecursionError, ValueError, IndexError) as e:
            warn(f"{f}: not checked ({type(e).__name__}: {e})")
    return sorted(report.items)


def check_log_files(files: list[str], report: Report) -> None:
    """One finding per folder of committed log files: the closest folder named log or logs
    above them, else their own folder."""
    groups: dict[PurePosixPath, list[str]] = {}
    for f in files:
        if f.endswith(".log") and not is_test(f):
            path = PurePosixPath(f)
            home = next((d for d in path.parents if d.name in {"log", "logs"}), path.parent)
            groups.setdefault(home, []).append(f)
    for home, logs in groups.items():
        where = home.as_posix()
        if len(logs) == 1:
            message = "a log file is committed → delete it and ignore *.log"
        else:
            message = (
                f"{len(logs)} log files are committed under {where}/ → delete them and ignore *.log"
            )
        if where != ".":
            message += (
                f', or, if they are kept as evidence, add "- skip: {where}/" under ## logging'
            )
        report.add(min(logs), 1, "log-file-tracked", message)


def plural(n: int) -> str:
    return f"{n} finding" if n == 1 else f"{n} findings"


def gh_escape(value: str, prop: bool) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if prop else value


def summary_line(arg: str) -> str:
    path = Path(arg)
    try:
        root = toplevel(path)
    except NotARepo:
        return f"{path.name or arg}: not a git repository at {arg}"
    try:
        found = check(root)
    except Exception as e:  # one broken repo never stops the others
        first = (str(e).splitlines() or [""])[0]
        return f"{root.name}: check failed: {type(e).__name__}: {first}"
    if not found:
        return f"{root.name}: logging standard ✓"
    counts: dict[str, int] = {}
    for f in found:
        counts[f.rule] = counts.get(f.rule, 0) + 1
    parts = ", ".join(f"{r} {n}" for r, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])))
    return f"{root.name}: {plural(len(found))} ({parts}) → run /techne:logging there"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a repo against techne's logging standard.")
    parser.add_argument("repos", nargs="*", metavar="REPO")
    parser.add_argument("--format", choices=("text", "github", "json"), default="text")
    parser.add_argument("--summary", action="store_true", help="one line per repo; exits 0")
    args = parser.parse_args(argv)
    if args.summary:
        for repo in args.repos or ["."]:
            print(summary_line(repo))
        return 0
    if len(args.repos) > 1:
        parser.error("give one REPO, or use --summary for several")
    target = args.repos[0] if args.repos else "."
    try:
        root = toplevel(Path(target))
    except NotARepo as e:
        print(f"logcheck: not a git repository at {target}: {e}", file=sys.stderr)
        return 2
    found = check(root)
    if args.format == "json":
        print(json.dumps([asdict(f) for f in found], indent=2))
    elif args.format == "github":
        for f in found:
            title = gh_escape(f"logcheck {f.rule}", True)
            props = f"file={gh_escape(f.path, True)},line={f.line},title={title}"
            print(f"::warning {props}::{gh_escape(f.message, False)}")
        print(plural(len(found)) if found else "logging standard ✓")
    else:
        for f in found:
            print(f"{f.path}:{f.line}: {f.rule}: {f.message}")
        print(plural(len(found)) if found else "logging standard ✓")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
