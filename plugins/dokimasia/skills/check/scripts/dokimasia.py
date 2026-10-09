#!/usr/bin/env python3
"""Bibliography guard for any LaTeX project: an offline lint, an online verify, a rendered check.

Named for the Athenian *dokimasia*, the scrutiny of a candidate's credentials before office.

A bibliography is a shared, accumulating asset, so an error in it is an error in everything
downstream, and it is exactly the kind of error that reads as fine. On 2026-08-25 an audit of
one project's file found three: a title truncated before its second half, a singular/plural
error, and an entry whose arXiv record had been retitled at v3 while the file still carried
the v1 title. None were visible in the file. All three were obvious the moment an identifier
was resolved against the source.

That audit was only possible after a backfill, because the identifiers were not reachable
before it: 50 entries carried an arXiv id as prose inside
`journal = {arXiv preprint arXiv:2312.17493}` and only 4 used a real `eprint` field.

There are three passes because they fail differently:

`lint` is offline, deterministic, and fit to run on every push. It checks the properties that
are true of the files alone -- every entry reachable, every identifier well formed, no
duplicate keys, no citation without an entry, no entry nothing accounts for, and no document
citing a paper an optional reading log still stages as unread.

`verify` resolves those identifiers against arXiv and Crossref and compares what comes back to
what the file claims -- title, first-author surname, and year. Title alone was not enough: the
2026-06-14 audit corrected one entry's *authors* and added six missing author lists, and
nothing comparing titles would have caught that class a second time.

It is also the pass that depends on third-party APIs being reachable. Gating a push on that
would buy drift detection at the cost of a bibliography check that fails for reasons having
nothing to do with the bibliography, so run it on a schedule: it reports rather than blocks. A
network failure is explicitly not a finding: an entry that could not be resolved is
unverified, which is not the same as wrong.

`rendered` compares the keys each document cites with the keys its `.bbl` actually contains.

A document may write its reference list by hand in `thebibliography`. It then has no `.bib` and
never builds a `.bbl`, and its `\\bibitem`s are its entries: `rendered` reads them as the
rendered keys, `lint` checks them for duplicates, dangling citations and orphans, and `verify`
resolves the ones that print an arXiv id or a DOI. A printed entry has no fields, so verify
compares it only where it quotes its title, the one field printed styles mark.

Verify outcomes are deliberately distinct, because conflating them is how a blind spot goes
quiet. **verified** resolved and matched. **unresolved** carried an identifier that the API did
not answer for -- transient, says nothing about the entry. **unverifiable** carries no `eprint`
and no `doi` at all, so there is nothing to resolve and no run will ever check it. `lint`
accepts those entries because `url` and `howpublished` are resolvable-by-a-human; `verify`
cannot follow them, and prints them by name every run so the set stays visible rather than
hiding inside a count. **uncompared** is a hand-written entry whose identifier resolved but
which does not quote its title: the work exists, and nothing printed can be matched to it.

Year is compared only where the comparison is sound. An entry whose `journal` says it is an
arXiv preprint is checked against the arXiv posting year, and a DOI entry against the Crossref
issued year or, where the record carries one, its print year: a journal that posts online first
has two years and both are correct to cite by. A venue-dated entry is never checked against its
preprint's arXiv year, because a NeurIPS 2025 paper posted to arXiv in January 2026 is
correctly dated 2025 and flagging it would train everyone to ignore the output.

Configuration is per project: `dokimasia.toml`, or a `[tool.dokimasia]` table in
`pyproject.toml`, at the project root. See `load_config`. Standard library only.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import tomllib
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import NoReturn

#: A field whose presence means the entry can be resolved to a record somewhere.
#: `howpublished` counts because @misc entries carry their URL there by convention.
ID_FIELDS = ("eprint", "doi", "url", "howpublished")

#: Not entries: they hold macros and text, and their first token is not a key. IEEEtran's
#: `@IEEEtranBSTCTL` holds style switches that `\bstctlcite` reads; it is not a reference.
NON_ENTRIES = ("string", "preamble", "comment", "ieeetranbstctl")

_NEW_ARXIV = r"\d{4}\.\d{4,5}"
_OLD_ARXIV = r"[a-z][a-z-]*(?:\.[A-Za-z]{2})?/\d{7}"
ARXIV_ID = re.compile(rf"^(?:{_NEW_ARXIV}|{_OLD_ARXIV})(v\d+)?$")
_PROSE_ARXIV = re.compile(rf"arxiv[:\s]*(?:{_NEW_ARXIV}|{_OLD_ARXIV})", re.I)

HOMEPAGE = "https://github.com/ajbarea/techne"
CONFIG_NAME = "dokimasia.toml"
MAILTO_ENV = "DOKIMASIA_MAILTO"

#: Resolved records are kept for a TTL rather than forever: the whole point of `verify` is
#: catching an upstream retitle, and a cache with no expiry would answer from the copy taken
#: before the retitle happened. At a weekly cadence this re-checks every entry at least
#: fortnightly and leaves most runs hitting no network at all.
CACHE_TTL = 14 * 86400
#: Bumped whenever a cached record gains or loses a field. A cached entry from an older
#: shape is a miss, so the new field is fetched rather than read as absent. Without this,
#: adding `print_year` left every cached record reporting no print year, and the drift it
#: was written to remove survived in exactly the entries the cache was covering.
RECORD_SCHEMA = 2


# --- configuration ---------------------------------------------------------------------


class ConfigError(Exception):
    """A configuration problem. Exit code 2: a typo must not silently disable a check."""


@dataclass(frozen=True)
class Config:
    root: Path
    #: Explicit bibliography paths, or None to take every `*.bib` under root.
    bib: tuple[Path, ...] | None = None
    exclude: frozenset[str] = frozenset()
    cache: Path = Path(".dokimasia-cache.json")
    #: Where a build writes its `.bbl`, relative to each document's directory.
    outdir: str | None = None
    orphans: bool = True
    intake: Path | None = None
    staged_headings: tuple[str, ...] = ("not yet positioned", "do not cite")
    #: Entries whose title deliberately differs from the source record. Only for an upstream
    #: record that is itself wrong: a title differing because ours is out of date is drift.
    title_exempt: dict[str, str] = dc_field(default_factory=dict)
    #: Same contract, for first author and year.
    record_exempt: dict[str, str] = dc_field(default_factory=dict)


_TOP_KEYS = {"bib", "exclude", "cache", "outdir", "orphans", "intake", "exempt"}
_INTAKE_KEYS = {"file", "staged_headings"}
_EXEMPT_KEYS = {"title", "record"}


def _strings(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{where} must be a list of non-empty strings")
    return list(value)


def _reasons(value: object, where: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a table of key = reason")
    for key, reason in value.items():
        if not isinstance(reason, str) or not reason.strip():
            raise ConfigError(f"{where}.{key} needs a non-empty reason")
    return dict(value)


def _unknown(table: dict, allowed: set[str], where: str) -> None:
    for name in sorted(set(table) - allowed):
        raise ConfigError(f"unknown key {name!r} in {where}")


def _clean_exclude(entry: str) -> str:
    """`./a/b/` means `a/b`."""
    entry = entry.strip()
    while entry.startswith("./"):
        entry = entry[2:]
    entry = entry.rstrip("/")
    if not entry or entry == ".":
        raise ConfigError(f"exclude entry {entry!r} names nothing")
    return entry


def parse_config(root: Path, table: dict) -> Config:
    """Build a Config from a parsed TOML table, rejecting anything it does not know."""
    _unknown(table, _TOP_KEYS, "the configuration")
    kwargs: dict = {"root": root}
    if "bib" in table:
        kwargs["bib"] = tuple(root / p for p in _strings(table["bib"], "bib"))
    if "exclude" in table:
        kwargs["exclude"] = frozenset(
            _clean_exclude(e) for e in _strings(table["exclude"], "exclude")
        )
    if "cache" in table:
        if not isinstance(table["cache"], str) or not table["cache"]:
            raise ConfigError("cache must be a non-empty string")
        kwargs["cache"] = Path(table["cache"])
        # The cache is written on every verify, so it may not name a file outside the project.
        target = (root / table["cache"]).resolve()
        if not target.is_relative_to(root):
            raise ConfigError(f"cache {table['cache']!r} must be inside the project root {root}")
    if "outdir" in table:
        if not isinstance(table["outdir"], str) or not table["outdir"]:
            raise ConfigError("outdir must be a non-empty string")
        kwargs["outdir"] = table["outdir"]
    if "orphans" in table:
        if not isinstance(table["orphans"], bool):
            raise ConfigError("orphans must be true or false")
        kwargs["orphans"] = table["orphans"]
    intake = table.get("intake", {})
    if not isinstance(intake, dict):
        raise ConfigError("intake must be a table")
    _unknown(intake, _INTAKE_KEYS, "[intake]")
    if "file" in intake:
        if not isinstance(intake["file"], str) or not intake["file"]:
            raise ConfigError("intake.file must be a non-empty string")
        kwargs["intake"] = root / intake["file"]
    if "staged_headings" in intake:
        headings = _strings(intake["staged_headings"], "intake.staged_headings")
        kwargs["staged_headings"] = tuple(h.lower() for h in headings)
    exempt = table.get("exempt", {})
    if not isinstance(exempt, dict):
        raise ConfigError("exempt must be a table")
    _unknown(exempt, _EXEMPT_KEYS, "[exempt]")
    if "title" in exempt:
        kwargs["title_exempt"] = _reasons(exempt["title"], "exempt.title")
    if "record" in exempt:
        kwargs["record_exempt"] = _reasons(exempt["record"], "exempt.record")
    return Config(**kwargs)


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error


def _config_table(directory: Path) -> dict | None:
    """The configuration table in `directory`, or None. dokimasia.toml wins over pyproject."""
    own = directory / CONFIG_NAME
    if own.is_file():
        return _read_toml(own)
    pyproject = directory / "pyproject.toml"
    if pyproject.is_file():
        text = ""
        try:
            text = pyproject.read_text(encoding="utf-8")
            parsed = tomllib.loads(text)
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            # Someone else's broken pyproject is not ours to fail on, unless it holds our table.
            if "[tool.dokimasia" in text:
                raise ConfigError(f"cannot read {pyproject}: {error}") from error
            return None
        tool = parsed.get("tool", {})
        if isinstance(tool, dict) and "dokimasia" in tool:
            table = tool["dokimasia"]
            if not isinstance(table, dict):
                raise ConfigError("[tool.dokimasia] must be a table")
            return table
    return None


def _git_toplevel(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out) if out else None


def find_root(cwd: Path) -> Path:
    """First ancestor holding a configuration, else the git top-level, else `cwd`.

    The walk stops at the git top-level: a configuration in a directory above the repository
    belongs to some other project.
    """
    top = _git_toplevel(cwd)
    top = top.resolve() if top else None
    for directory in (cwd, *cwd.parents):
        if _config_table(directory) is not None:
            return directory
        if directory == top:
            break
    return top or cwd


def load_config(root: Path | None = None, cwd: Path | None = None) -> Config:
    """Resolve the project root and read its configuration; every key is optional."""
    root = (root or find_root((cwd or Path.cwd()).resolve())).resolve()
    if not root.is_dir():
        raise ConfigError(f"root {root} is not a directory")
    cfg = parse_config(root, _config_table(root) or {})
    if cfg.intake is not None and not cfg.intake.is_file():
        raise ConfigError(f"intake file not found: {cfg.intake}")
    return cfg


# --- files -----------------------------------------------------------------------------


def _walk(cfg: Config, suffix: str) -> list[Path]:
    """Files under root with `suffix`, skipping excluded, hidden and node_modules directories.

    An `exclude` entry with a `/` is a path prefix from the root; a bare name matches a
    directory of that name at any depth.
    """
    names = {e for e in cfg.exclude if "/" not in e}
    prefixes = [e.strip("/") for e in cfg.exclude if "/" in e]
    found: list[Path] = []
    for here, dirs, files in os.walk(cfg.root):
        base = Path(here).relative_to(cfg.root)

        def kept(d: str, base: Path = base) -> bool:
            rel = (base / d).as_posix()
            if d in names or d.startswith(".") or d == "node_modules":
                return False
            return not any(rel == p or rel.startswith(p + "/") for p in prefixes)

        dirs[:] = sorted(d for d in dirs if kept(d))
        # A broken symlink lists like a file and cannot be read.
        found += [
            Path(here) / f
            for f in sorted(files)
            if f.endswith(suffix) and (Path(here) / f).is_file()
        ]
    return found


def note_unmatched_excludes(cfg: Config) -> None:
    """Say which `exclude` entries match no directory, so a typo does not read as a clean run."""
    seen: set[str] = set()
    for here, dirs, _ in os.walk(cfg.root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        base = Path(here).relative_to(cfg.root)
        for d in dirs:
            seen.add(d)
            seen.add((base / d).as_posix())
    for entry in sorted(cfg.exclude):
        if entry not in seen:
            print(f"dokimasia: exclude matched nothing: {entry}")


def bib_files(cfg: Config, hand_written: bool = False) -> list[Path]:
    """The bibliographies to check. None at all is a configuration error unless some
    document writes its reference list by hand, which needs no `.bib`."""
    if cfg.bib is not None:
        missing = [p for p in cfg.bib if not p.is_file()]
        if missing:
            raise ConfigError(f"bib file not found: {missing[0]}")
        return list(cfg.bib)
    found = _walk(cfg, ".bib")
    if not found and not hand_written:
        raise ConfigError(
            f"no .bib files under {cfg.root}, and no document has a hand-written thebibliography"
        )
    return found


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _name(cfg: Config, path: Path) -> str:
    try:
        return path.resolve().relative_to(cfg.root).as_posix()
    except ValueError:
        return str(path)


# --- BibTeX parsing --------------------------------------------------------------------


def _close_brace(text: str, start: int) -> int:
    """Index just past the brace that closes the one opened before `start`.

    A backslash escapes the next character, so `\\{`, `\\}` and `\\\\` are not structural.
    """
    i, depth = start, 1
    while i < len(text) and depth:
        if text[i] == "\\":
            i += 2
            continue
        depth += (text[i] == "{") - (text[i] == "}")
        i += 1
    return min(i, len(text))


def _close_paren(text: str, start: int) -> int:
    """Index just past the `)` that ends a parenthesised entry opened before `start`.

    Braces and quoted strings are skipped, since a field value may hold a `)`.
    """
    i, depth, quoted = start, 0, False
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == '"' and depth <= 0:
            quoted = not quoted
        elif ch == ")" and depth <= 0 and not quoted:
            return i + 1
        i += 1
    return i


def entries(text: str):
    """Yield `(type, key, body)` per entry, brace-matched so nested `{}` survive.

    A regex that stops at the first `}` truncates any entry using brace protection
    (`{LLM}s`), which reads as a title mismatch that is not there. `@string`, `@preamble`
    and `@comment` are skipped whole: their first token is not a key, and a `@comment`
    may quote entries that are not part of the bibliography.
    """
    head = re.compile(r"@(\w+)\s*([{(])")
    pos = 0
    while match := head.search(text, pos):
        kind = match.group(1).lower()
        close = _close_brace if match.group(2) == "{" else _close_paren
        end = close(text, match.end())
        if kind in NON_ENTRIES:
            pos = end
            continue
        key = re.match(r"\s*([^,\s{}]+)\s*,", text[match.end() : end])
        if not key:
            pos = match.end()
            continue
        yield kind, key.group(1), text[match.end() + key.end() : end - 1]
        pos = end


_FIELD_HEAD = re.compile(r"[\s,]*([A-Za-z][\w:.-]*)\s*=\s*")
_BARE = re.compile(r"[^,\s#{}\"]*")
_JOIN = re.compile(r"\s*#\s*")


def _value(body: str, i: int) -> tuple[str, int]:
    """One field value starting at `i` in any BibTeX form, and the index after it."""
    if i >= len(body):
        return "", i
    if body[i] == "{":
        end = _close_brace(body, i + 1)
        return body[i + 1 : end - 1], end
    if body[i] == '"':
        j, depth = i + 1, 0
        while j < len(body) and not (body[j] == '"' and depth == 0):
            if body[j] == "\\":
                j += 1
            else:
                depth += (body[j] == "{") - (body[j] == "}")
            j += 1
        return body[i + 1 : j], j + 1
    bare = _BARE.match(body, i)
    assert bare
    return bare.group(), bare.end()


def parse_fields(body: str) -> dict[str, str]:
    """Top-level fields of an entry body, lower-cased names. Values may be `{..}`, `".."`,
    bare, or a `#` concatenation of those (kept joined, macros unexpanded)."""
    out: dict[str, str] = {}
    i = 0
    while i < len(body):
        head = _FIELD_HEAD.match(body, i)
        if not head:
            comma = body.find(",", i)
            if comma < 0:
                break
            i = comma + 1
            continue
        value, i = _value(body, head.end())
        while (join := _JOIN.match(body, i)) and join.end() < len(body):
            more, i = _value(body, join.end())
            value += more
        out.setdefault(head.group(1).lower(), value)
    return out


def field(body: str, name: str) -> str | None:
    """Return one field value, or None when the entry lacks it."""
    return parse_fields(body).get(name.lower())


_TEX_ACCENT = re.compile(r"\\[`'^\"~=.]\s*(?:\{\s*\\?([A-Za-z])\s*\}|\\?([A-Za-z]))")
_TEX_ACCENT_ALPHA = re.compile(r"\\[cvuHkrbdt]\s*\{\s*([A-Za-z])\s*\}")
_TEX_LETTERS = {
    "ss": "ss",
    "ae": "ae",
    "AE": "AE",
    "oe": "oe",
    "OE": "OE",
    "aa": "a",
    "AA": "A",
    "o": "o",
    "O": "O",
    "l": "l",
    "L": "L",
    "i": "i",
    "j": "j",
}
_TEX_LETTER = re.compile(r"\\(ss|ae|AE|oe|OE|aa|AA|o|O|l|L|i|j)(?![A-Za-z])\s*")
#: Letters canonical decomposition leaves whole, and the Latin ligatures. NFKD would
#: also expand these but folds script l and superscripts into letters, which TeX never does.
_UNICODE_LETTERS = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "st",
        "\ufb06": "st",
        "ø": "o",
        "Ø": "O",
        "ł": "l",
        "Ł": "L",
        "ß": "ss",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "đ": "d",
        "Đ": "D",
        "\u0131": "i",
    }
)


def fold_accents(value: str) -> str:
    """TeX accent macros and Unicode diacritics reduced to their base letters.

    `Gonz{\\'a}lez`, `Gonz\\'alez` and `González` all fold to `Gonzalez`, so an author the
    file writes in TeX matches the source record's Unicode spelling.
    """
    value = _TEX_ACCENT.sub(lambda m: m.group(1) or m.group(2), value)
    value = _TEX_ACCENT_ALPHA.sub(lambda m: m.group(1), value)
    value = _TEX_LETTER.sub(lambda m: _TEX_LETTERS[m.group(1)], value)
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.translate(_UNICODE_LETTERS)


def normalise(value: str | None) -> str:
    """Collapse a title to comparable form: no LaTeX, no punctuation, no case.

    Brace protection and accent macros are presentation, not content, so `{LLM}s` and
    `LLMs` have to compare equal or every correctly-written entry reports as drift.
    """
    # The arXiv Atom feed returns `&amp;` where the entry has `\&`. Left alone, the
    # entity survives as the word "amp" and every title containing an ampersand
    # reports as drift.
    value = fold_accents(html.unescape(value or ""))
    value = re.sub(r"\\[a-zA-Z]+", "", value)
    # Braces are removed rather than treated as separators. Turning them into spaces
    # splits `{LLM}s` into "llm s", which never equals the source record's "LLMs" --
    # every correctly brace-protected entry would report as drift.
    value = value.replace("{", "").replace("}", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


# --- citations -------------------------------------------------------------------------

#: Text LaTeX does not read as markup: comments, `\verb`, and verbatim-like environments.
#: One alternation, leftmost first, so a `%` inside a listing does not comment out its
#: `\end` and a commented `\begin{verbatim}` does not open one. `\\` and `\%` are matched
#: whole so an escaped percent is not a comment.
_INERT = re.compile(
    r"(?P<keep>\\[\\%])"
    r"|%[^\n]*"
    r"|\\verb\*?(?P<d>[^\sA-Za-z*])(?:(?!(?P=d))[^\n])*(?P=d)"
    r"|\\begin\{(?P<env>verbatim\*?|Verbatim\*?|lstlisting|minted)\}.*?\\end\{(?P=env)\}",
    re.S,
)
#: The body of a macro definition is a template, not a use: `\newcommand{\mycite}[1]{\cite{#1}}`.
_DEFINITION = re.compile(
    r"\\(?:(?:re)?newcommand|providecommand|DeclareRobustCommand)\*?\s*"
    r"(?:\{\\[A-Za-z@]+\}|\\[A-Za-z@]+)\s*(?:\[[^\]]*\]\s*)*\{"
    r"|\\(?:gdef|edef|xdef|def)(?![A-Za-z])\s*\\[A-Za-z@]+[^{\n]*\{"
)
_CITE_HEAD = re.compile(r"\\([A-Za-z]*(?i:cite)[A-Za-z]*)\*?")
_CITE_ARGS = re.compile(r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]*)\}")
#: A group after the previous one, with at most one newline between. Text groups that follow
#: (`{\em x}`) are dropped by the key filter.
_MORE_ARGS = re.compile(r"(?:[ \t]*\n?[ \t]*\[[^\]]*\])*[ \t]*\n?[ \t]*\{([^}]*)\}")
#: Commands whose name contains "cite" but whose argument is not a key list.
_NOT_CITES = {
    "citestyle",
    "setcitestyle",
    "citetext",
    "citeindextrue",
    "citeindexfalse",
    "declarecitecommand",
    "bstctlcite",
}
_BAD_KEY = re.compile(r"[\\#{}\s]")
_NOCITE = re.compile(r"\\nocite\s*\{([^}]*)\}")
_INCLUDE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]*)\}")
_INCLUDE_BARE = re.compile(r"\\input\s+([^\s{}\\%]+)")
_IMPORT = re.compile(
    r"\\(import|subimport|inputfrom|subinputfrom|includefrom|subincludefrom)"
    r"\*?\s*\{([^}]*)\}\s*\{([^}]*)\}"
)
_BIBLIOGRAPHY = re.compile(r"\\bibliography\s*\{([^}]*)\}")
_BIBRESOURCE = re.compile(r"\\addbibresource\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_BIBLIOGRAPHY_USE = re.compile(
    r"\\(?:bibliography\s*\{|addbibresource(?![A-Za-z])|printbibliography)"
)
_DOCUMENTCLASS = re.compile(r"\\documentclass")
_SUBFILES = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{subfiles\}")


def strip_comments(text: str) -> str:
    """Drop comments, `\\verb` and verbatim environments; `50\\%` is a percent sign."""

    def drop(match: re.Match[str]) -> str:
        if match.group("keep"):
            return match.group("keep")
        return " " if match.group("env") else ""

    return _INERT.sub(drop, text)


def _without_definitions(text: str) -> str:
    out, pos = [], 0
    while match := _DEFINITION.search(text, pos):
        out.append(text[pos : match.start()])
        pos = _close_brace(text, match.end())
    out.append(text[pos:])
    return "".join(out)


def cite_keys(text: str) -> set[str]:
    """Keys cited by any `...cite...` command, with up to two optional arguments.

    Covers natbib (`\\citep[see][p.~3]{a,b}`), biblatex (`\\parencite`, `\\autocite*`) and
    `\\nocite`, in any capitalisation of `cite`. `\\nocite{*}` names no key; macro
    definition bodies, verbatim text and anything that is not a plain key are skipped.
    """
    text = _without_definitions(strip_comments(text))
    keys: set[str] = set()
    for head in _CITE_HEAD.finditer(text):
        name = head.group(1).lower()
        if name in _NOT_CITES:
            continue
        args = _CITE_ARGS.match(text, head.end())
        while args:
            keys |= {k.strip() for k in args.group(1).split(",") if k.strip()}
            # biblatex `\cites{a}{b}` and `\textcites[..]{a}[..]{b}` chain argument groups.
            args = _MORE_ARGS.match(text, args.end()) if name.endswith("cites") else None
    return {k for k in keys if k != "*" and not _BAD_KEY.search(k)}


def has_nocite_star(text: str) -> bool:
    """Whether `\\nocite{*}` appears outside a comment: every entry then renders."""
    return any(
        "*" in {k.strip() for k in group.split(",")}
        for group in _NOCITE.findall(_without_definitions(strip_comments(text)))
    )


# --- hand-written bibliographies -------------------------------------------------------

_BEGIN_BIB = re.compile(r"\\begin\{thebibliography\}")
_END_BIB = re.compile(r"\\end\{thebibliography\}")
_BIBITEM = re.compile(r"\\bibitem\s*(?:\[.*?\])?\s*\{([^}]*)\}", re.S)
#: The `comment` environment, which LaTeX never typesets. Conditionals are not evaluated:
#: deciding which branch TeX takes needs TeX, and every approximation tried deleted live text
#: along with dead. Reading too much can only add entries; deleting can hide a fabricated one.
_COMMENT_ENV = re.compile(r"\\begin\{comment\}.*?\\end\{comment\}", re.S)
#: A `\newenvironment` body is a template; a `thebibliography` inside one is not a list.
_ENV_DEFINITION = re.compile(
    r"\\(?:re)?newenvironment\*?\s*\{[^}]*\}\s*(?:\[[^\]]*\]\s*)*\{"
    r"|\\(?:New|Renew|Provide|Declare)DocumentEnvironment\s*\{[^}]*\}\s*\{"
)
_INLINE_ARXIV = re.compile(
    r"(?:arxiv(?:\.org/(?:abs|pdf)/|[:.\s]*)|corr\}?,?\s*(?:vol\.\s*)?abs/|\\showeprint\s*\[arxiv\]\s*\{)\s*"
    rf"({_NEW_ARXIV}|{_OLD_ARXIV})(?:v\d+)?",
    re.I,
)
#: A DOI runs to whitespace, a brace, a quote, a comma or a backslash; `;` stays, since SICI
#: DOIs contain it, and trailing punctuation is trimmed after the match.
_INLINE_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s,{}\\\"'`]+)")
#: arXiv's own DataCite prefix: the arXiv id in it is what resolves, not the DOI.
_ARXIV_DOI = "10.48550/"
_URL = re.compile(r"\\url\s*\{[^}]*\}|https?://\S+")
_YEAR = re.compile(r"(?<![\d.])((?:19|20)\d{2})(?!\d)")
#: An arXiv id followed at once by a year, `arXiv:2401.00001 [cs.LG], 2024`: the entry is
#: dated by its preprint, so the arXiv posting year is the one to compare.
_PREPRINT_YEAR = re.compile(
    _INLINE_ARXIV.pattern + r"(?:\s*\[[^\]]*\])?[^A-Za-z0-9]{0,6}((?:19|20)\d{2})(?!\d)", re.I
)
#: The opening of a quoted span: TeX's ``, a straight quote that is not an umlaut (`\"o`),
#: a typographic opening quote, or csquotes' `\enquote{`.
_QUOTE_OPEN = re.compile(r"``|(?<!\\)\"|\u201c|\\enquote\s*\{")
_STRAIGHT_CLOSE = re.compile(r"(?<!\\)\"")
#: `In` before a quoted span means the span names the containing book or proceedings, never
#: the item, wherever `In` sits: `In~`, `In:`, `In Proc.`, `In: Smith (ed.)`.
_IN_WORD = re.compile(r"(?<![A-Za-z])in(?![A-Za-z])", re.I)
#: What separates the first author from the rest of a printed author list.
_AUTHOR_BREAK = re.compile(r",|;|\\?&|\b(?i:and|with|et|und)\b|\\and\b")
#: Particles a printed surname may be split at, `Le Cun` for `LeCun`.
_PARTICLES = {"le", "la", "de", "da", "di", "du", "van", "von", "der", "den", "del", "della"}
_PARTICLES |= {"ten", "ter"}
#: A page range, `1195--1225`, whose ends are not years.
_PAGE_RANGE = re.compile(r"\d+\s*-{1,3}\s*\d+")
#: Words in a printed author segment that are not a surname.
_NOT_NAMES = {"and", "et", "al", "jr", "sr", "ii", "iii", "iv", "eds", "ed"}


@dataclass(frozen=True)
class Bibitem:
    """One entry of a hand-written `thebibliography`: its key and its printed text."""

    file: Path
    key: str
    text: str


def _without_environment_definitions(text: str) -> str:
    """Drop `\\newenvironment` and xparse environment definitions with their bodies.

    The pattern stops inside the first brace group: the begin body for `\\newenvironment`,
    the argument spec for xparse. One or two more groups follow it.
    """
    out, pos = [], 0
    while match := _ENV_DEFINITION.search(text, pos):
        out.append(text[pos : match.start()])
        pos = _close_brace(text, match.end())
        for _ in range(2 if "DocumentEnvironment" in match.group() else 1):
            rest = re.match(r"\s*\{", text[pos:])
            if not rest:
                break
            pos = _close_brace(text, pos + rest.end())
    out.append(text[pos:])
    return "".join(out)


def typeset(text: str) -> str:
    """`text` without comments, macro and environment definitions, or `comment` blocks."""
    clean = _without_environment_definitions(_without_definitions(strip_comments(text)))
    return _COMMENT_ENV.sub(" ", clean)


def opens_bibliography(text: str) -> bool:
    """Whether already-typeset `text` opens a `thebibliography` block."""
    return bool(_BEGIN_BIB.search(text))


def bibitems(text: str, file: Path) -> list[Bibitem]:
    """Every `\\bibitem` in already-typeset `text`.

    Read from each `thebibliography` block, or from the whole file when it opens none, since a
    list is often split: the block in the document, its items in an `\\input` file. An item
    runs to the next `\\bibitem`, the end of its block, or the end of the file.
    """
    starts = [m.end() for m in _BEGIN_BIB.finditer(text)] or [0]
    found = []
    for start in starts:
        region = text[start:]
        end = _END_BIB.search(region)
        region = region[: end.start()] if end else region
        heads = list(_BIBITEM.finditer(region))
        for i, head in enumerate(heads):
            stop = heads[i + 1].start() if i + 1 < len(heads) else len(region)
            words = " ".join(region[head.end() : stop].split())
            found.append(Bibitem(file, head.group(1).strip(), words))
    return found


def inline_ids(text: str) -> tuple[str | None, str | None]:
    """The arXiv id and DOI printed in a hand-written entry, either of which may be absent."""
    arxiv = _INLINE_ARXIV.search(text)
    doi = _INLINE_DOI.search(text.replace("\\_", "_"))
    found = doi.group(1).rstrip(".;)]") if doi else None
    if found and found.lower().startswith(_ARXIV_DOI):
        found = None
    return (arxiv.group(1) if arxiv else None), found


def _included(text: str, doc_dir: Path, here: Path) -> list[Path]:
    """Files `text` pulls in. `\\import`-style commands resolve from the document's
    directory; the `sub` forms from the including file's."""
    clean = strip_comments(text)
    refs = [doc_dir / name.strip() for name in _INCLUDE.findall(clean)]
    refs += [doc_dir / name for name in _INCLUDE_BARE.findall(clean)]
    for command, directory, name in _IMPORT.findall(clean):
        base = here if command.startswith("sub") else doc_dir
        refs.append(base / directory.strip() / name.strip())
    found = []
    for raw in refs:
        for candidate in (raw, raw.with_name(raw.name + ".tex")):
            if candidate.is_file():
                found.append(candidate)
                break
    return found


def document_files(doc: Path) -> list[Path]:
    """The document and every file reached through `\\input`, `\\include`, `\\subfile` and
    the `\\import` family, resolved.

    Paths resolve against the document's directory, as LaTeX does. Cycle-safe; a missing
    file is ignored, since the compiler reports it and this is not the compiler.
    """
    seen: dict[Path, None] = {}
    pending = [doc]
    while pending:
        path = pending.pop()
        real = path.resolve()
        if real in seen:
            continue
        seen[real] = None
        pending += _included(_read(path), doc.parent, path.parent)
    return list(seen)


@dataclass(frozen=True)
class Document:
    path: Path
    files: tuple[Path, ...]
    cites: frozenset[str]
    #: `\nocite{*}` outside a comment: every entry of its bibliographies renders.
    nocite_star: bool
    #: Bibliographies the document names, resolved; empty when it names none.
    named: tuple[Path, ...]
    #: Whether it has a bibliography at all, from a command or from its citations.
    needs_bibliography: bool
    #: Whether it writes its reference list by hand in a `thebibliography` block. Such a
    #: document has no `.bib` to draw on and no `.bbl` to build; its items are its entries.
    hand_written: bool = False
    bibitems: tuple[Bibitem, ...] = ()
    #: Keys of a `.bbl` pasted in with `\input`, as arXiv submissions do. That list is build
    #: output, not hand-written: it renders, but its entries live in a `.bib`.
    pasted: frozenset[str] = frozenset()


def _bib_path(base: Path, name: str) -> Path:
    path = base / name
    if path.suffix != ".bib":
        path = path.with_name(path.name + ".bib")
    return Path(os.path.normpath(path))


def read_document(doc: Path) -> Document:
    files = document_files(doc)
    cites: set[str] = set()
    names: list[str] = []
    items: list[Bibitem] = []
    pasted: set[str] = set()
    star = uses = hand = False
    for path in files:
        text = _read(path)
        clean = _without_definitions(strip_comments(text))
        cites |= cite_keys(text)
        star = star or has_nocite_star(text)
        for group in _BIBLIOGRAPHY.findall(clean):
            names += [n.strip() for n in group.split(",") if n.strip()]
        names += [n.strip() for n in _BIBRESOURCE.findall(clean)]
        uses = uses or bool(_BIBLIOGRAPHY_USE.search(clean))
        page = typeset(text)
        if path.suffix == ".bbl":
            pasted |= bbl_keys(page)
            continue
        hand = hand or opens_bibliography(page)
        items += bibitems(page, path.resolve())
    named = tuple(
        _bib_path(doc.parent, n)
        for n in dict.fromkeys(names)
        if not n.startswith(("http:", "https:"))
    )
    return Document(
        doc,
        tuple(files),
        frozenset(cites),
        star,
        named,
        bool(cites) or uses or star or hand,
        # A document that uses BibTeX or biblatex is a BibTeX document, as it always was here;
        # a `thebibliography` beside that is not read, whatever conditionals surround it.
        hand and not uses,
        # A file of loose `\bibitem`s counts only as part of a hand-written list.
        tuple(items) if hand and not uses else (),
        frozenset(pasted),
    )


def document_cites(doc: Path) -> set[str]:
    return set(read_document(doc).cites)


def documents(cfg: Config) -> list[Path]:
    """Every `.tex` under root with a `\\documentclass` outside a comment.

    A `subfiles` child compiles on its own but is part of its parent's bibliography.
    """
    found = []
    for path in _walk(cfg, ".tex"):
        text = strip_comments(_read(path))
        if _DOCUMENTCLASS.search(text) and not _SUBFILES.search(text):
            found.append(path)
    return found


# --- optional reading log --------------------------------------------------------------

_BACKTICKED = re.compile(r"`([A-Za-z][A-Za-z0-9_:\-]*)`")


def accounted_keys(cfg: Config) -> set[str]:
    """Keys the intake log names, in any form.

    Deliberately loose: it asks only whether the log mentions the key at all, not
    whether the key is positioned. Positioning is a human judgement.
    """
    if not cfg.intake or not cfg.intake.exists():
        return set()
    return set(_BACKTICKED.findall(cfg.intake.read_text(encoding="utf-8")))


def staged_keys(cfg: Config) -> set[str]:
    """Keys the intake log records as staged-but-unread.

    A section heading carries the status: anything under a `## ` heading matching
    `staged_headings` is recorded but unread. Keys are read until the next `## `.
    """
    if not cfg.intake or not cfg.intake.exists():
        return set()
    keys: set[str] = set()
    staged = False
    for line in cfg.intake.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            staged = any(h in line.lower() for h in cfg.staged_headings)
        elif staged:
            keys |= set(_BACKTICKED.findall(line))
    return keys


# --- lint ------------------------------------------------------------------------------

Parsed = dict[Path, list[tuple[str, str, str]]]


def _parse_bibs(cfg: Config, hand_written: bool = False) -> Parsed:
    return {p.resolve(): list(entries(_read(p))) for p in bib_files(cfg, hand_written)}


def _all_entries(cfg: Config, hand_written: bool = False) -> list[tuple[Path, str, str, str]]:
    return [
        (path, kind, key, body)
        for path, found in _parse_bibs(cfg, hand_written).items()
        for kind, key, body in found
    ]


def _unique_bibitems(docs: list[Document]) -> list[Bibitem]:
    """Every hand-written entry once, though a shared file may be reached by two documents.

    Keyed on the text as well as the key: a key printed twice is a lint finding, and each
    copy still has to be resolved, since the second may carry a different identifier.
    """
    seen: dict[tuple[Path, str, str], Bibitem] = {}
    for doc in docs:
        for item in doc.bibitems:
            seen.setdefault((item.file, item.key, item.text), item)
    return list(seen.values())


def _identifier_findings(key: str, body: str) -> list[str]:
    fields = parse_fields(body)
    prose_id = _PROSE_ARXIV.search(fields.get("journal", ""))
    if not set(fields) & set(ID_FIELDS):
        return [
            f"arXiv id present but only in prose: {key}"
            if prose_id
            else f"no resolvable identifier: {key}"
        ]
    found = []
    eprint = fields.get("eprint")
    if eprint is not None and not ARXIV_ID.match(eprint.strip()):
        found.append(f"malformed eprint: {key} = {eprint!r}")
    doi = fields.get("doi")
    if doi is not None and not doi.strip().startswith("10."):
        found.append(f"malformed doi: {key} = {doi!r}")
    url = fields.get("url")
    if url is not None and not url.strip().startswith("http"):
        found.append(f"malformed url: {key} = {url!r}")
    if prose_id and eprint is None:
        found.append(f"arXiv id present but only in prose: {key}")
    return found


def lint(cfg: Config) -> int:
    """Offline checks. Returns the number of findings; prints one line each.

    A document is checked against the bibliographies it names (`\\bibliography`,
    `\\addbibresource`), or against all of them when it names none. A key repeated across
    two files is a duplicate only where one document uses both.
    """
    note_unmatched_excludes(cfg)
    docs = [read_document(p) for p in documents(cfg)]
    parsed = _parse_bibs(cfg, any(d.hand_written for d in docs))
    universe = list(parsed)
    items = _unique_bibitems(docs)
    reached = {f for d in docs for f in d.files}
    loose = [p for p in _walk(cfg, ".tex") if p.resolve() not in reached]
    loose_cites: set[str] = set()
    for path in loose:
        loose_cites |= cite_keys(_read(path))

    findings: list[str] = []

    def add(message: str) -> None:
        if message not in findings:
            findings.append(message)

    def uses(doc: Document) -> list[Path]:
        if doc.named:
            return [p.resolve() for p in doc.named]
        if doc.hand_written:
            return []
        return universe if doc.needs_bibliography else []

    def entries_of(files: list[Path]) -> list[tuple[Path, str]]:
        found = []
        for file in files:
            if file not in parsed and file.is_file():
                parsed[file] = list(entries(_read(file)))
            found += [(file, key) for _, key, _ in parsed.get(file, [])]
        return found

    for doc in docs:
        for path in doc.named:
            if not path.is_file():
                add(f"missing bibliography: {_name(cfg, doc.path)} -> {_name(cfg, path)}")

    scopes = [uses(doc) for doc in docs] or [universe]
    covered = {f for scope in scopes for f in scope}
    scopes += [[f] for f in universe if f not in covered]
    for scope in scopes:
        homes: dict[str, list[str]] = {}
        for file, key in entries_of(scope):
            homes.setdefault(key, []).append(_name(cfg, file))
        for key, where in sorted(homes.items()):
            if len(where) > 1:
                files = ", ".join(sorted(set(where)))
                add(f"duplicate key: {key} appears {len(where)} times ({files})")

    for file in universe:
        for _, key, body in parsed[file]:
            for message in _identifier_findings(key, body):
                add(message)

    for doc in docs:
        counts: dict[str, int] = {}
        for item in doc.bibitems:
            counts[item.key] = counts.get(item.key, 0) + 1
        for key, count in sorted(counts.items()):
            if count > 1:
                add(f"duplicate \\bibitem: {key} appears {count} times (in {_name(cfg, doc.path)})")

    keys = {key for _, key in entries_of(universe)} | {item.key for item in items}
    for table, exempt in (("title", cfg.title_exempt), ("record", cfg.record_exempt)):
        for key in sorted(set(exempt) - keys):
            add(f"exemption for missing entry: {key} (exempt.{table})")

    for doc in docs:
        defined = {key for _, key in entries_of(uses(doc))} | {i.key for i in doc.bibitems}
        for key in sorted(doc.cites - defined):
            add(
                f"dangling citation: \\cite{{{key}}} has no entry (cited by {_name(cfg, doc.path)})"
            )
    for key in sorted(loose_cites - keys):
        add(f"dangling citation: \\cite{{{key}}} has no entry")

    cited = loose_cites.union(*(d.cites for d in docs))
    star_docs: dict[str, set[str]] = {}
    if cfg.orphans:
        accounted = accounted_keys(cfg)
        # A .bbl pasted into a .tex reads as hand-written, yet cites a .bib's entries.
        hand_cites = set().union(*(d.cites for d in docs if d.hand_written))
        for file in universe:
            users = [d for d in docs if file in uses(d)]
            stars = [_name(cfg, d.path) for d in users if d.nocite_star]
            if stars:
                star_docs[_name(cfg, file)] = set(stars)
                continue
            seen_here = loose_cites.union(*(d.cites for d in users), hand_cites)
            for _, key, _ in parsed[file]:
                if key not in seen_here and key not in accounted:
                    add(
                        f"orphan entry: {key} is cited nowhere and the intake log does not "
                        f"name it (in {_name(cfg, file)})"
                    )
        # A hand-written list prints every item whether or not anything cites it, so
        # \nocite{*} changes nothing there and covers nothing.
        for doc in docs:
            for item in doc.bibitems:
                if item.key not in doc.cites and item.key not in accounted:
                    add(
                        f"orphan \\bibitem: {item.key} is printed in {_name(cfg, doc.path)} "
                        f"but cited nowhere in it"
                    )

    staged = staged_keys(cfg)
    for key in sorted(staged & cited):
        add(
            f"cited but unread: {key} is cited in a document while the intake log still "
            f"stages it as unpositioned -- read it and position it, or drop the citation"
        )

    for line in findings:
        print(f"dokimasia: {line}", file=sys.stderr)
    if star_docs:
        who = sorted(set().union(*star_docs.values()))
        print(
            f"dokimasia: \\nocite{{*}} in {', '.join(who)} cites every entry of "
            f"{', '.join(sorted(star_docs))}, so the orphan check covers nothing there"
        )
    blind = [i for i in items if inline_ids(i.text) == (None, None)]
    if blind:
        # Not a finding: printed reference styles routinely drop the DOI, so requiring one
        # would fail nearly every hand-written list. verify names each of these.
        print(
            f"dokimasia: info: {len(blind)} of {len(items)} hand-written entries print no arXiv "
            f"id or DOI, so verify cannot check them"
        )
    hand = f" ({len(items)} hand-written)" if items else ""
    print(
        f"dokimasia: {sum(len(parsed[f]) for f in universe) + len(items)} entries{hand}, "
        f"{len(staged & keys)} staged unread, {len(findings)} finding(s)"
    )
    return len(findings)


# --- rendered --------------------------------------------------------------------------

_ENTRY = re.compile(r"\\entry\s*\{([^}]*)\}\s*\{")


def bbl_keys(text: str) -> set[str]:
    """Keys a `.bbl` renders: `\\bibitem[label]{key}` (BibTeX) or `\\entry{key}{` (biber)."""
    return {k.strip() for k in _BIBITEM.findall(text) + _ENTRY.findall(text)}


def _bbl_for(cfg: Config, doc: Path) -> Path:
    """The `.bbl` in the configured build directory, else beside the `.tex`.

    The build directory wins: `latexmk -outdir` leaves any `.bbl` beside the source stale.
    """
    beside = doc.with_suffix(".bbl")
    if cfg.outdir:
        built = doc.parent / cfg.outdir / beside.name
        if built.exists():
            return built
    return beside


def _unreached(cfg: Config, docs: list[Path]) -> list[str]:
    """One line per document directory holding `.tex` files no document's includes reach."""
    reached = {f for d in documents(cfg) for f in document_files(d)}
    tex = [p.resolve() for p in _walk(cfg, ".tex")]
    lines, seen = [], set()
    for doc in docs:
        here = doc.parent.resolve()
        if here in seen:
            continue
        seen.add(here)
        stray = sorted(p for p in tex if p.is_relative_to(here) and p not in reached)
        if stray:
            names = [_name(cfg, p) for p in stray]
            more = f", and {len(names) - 10} more" if len(names) > 10 else ""
            noun = "file" if len(names) == 1 else "files"
            lines.append(
                f"dokimasia: info: {_name(cfg, here)}/: {len(names)} .tex {noun} reached by "
                f"no document ({', '.join(names[:10])}{more}); an include form this tool "
                f"does not follow would hide citations there"
            )
    return lines


def rendered(cfg: Config, docs: list[Path] | None = None, require_built: bool = False) -> int:
    """Assert every key each document cites appears in its own `.bbl`.

    Compares against the keys that document cites, not against every key in the shared
    bibliography: a count of all entries scores a skeleton using `\\nocite{*}` full marks
    and fails a document that cites a normal subset. Keys are parsed out of the `.bbl`
    rather than substring-matched, so `li2020` does not pass because `li2020b` rendered.
    A document with no `.bbl` is not built: named, never silently passed. One that cites
    nothing and names no bibliography has nothing to render and is listed apart. One that
    writes its list by hand in `thebibliography` never has a `.bbl`: its `\\bibitem` keys are
    what renders.
    """
    note_unmatched_excludes(cfg)
    docs = documents(cfg) if not docs else docs
    problems = 0
    checked = 0
    unbuilt: list[str] = []
    bare: list[str] = []
    for doc in docs:
        name = _name(cfg, doc)
        info = read_document(doc)
        bbl = _bbl_for(cfg, doc)
        # A hand-written list renders without a build, and so does a pasted `.bbl` under
        # another stem. A document that also names a `.bib` still needs its `.bbl`.
        built = bbl.exists()
        if (info.hand_written or (info.pasted and not built)) and (built or not info.named):
            checked += 1
            cites = info.cites
            shown = {item.key for item in info.bibitems} | info.pasted
            # LaTeX reads the .bbl only for a document that names a .bib; beside a
            # hand-written list it is stale output from some earlier build.
            if built and info.named:
                shown |= bbl_keys(_read(bbl))
            missing = sorted(cites - shown)
            kind = "hand-written thebibliography" if info.hand_written else "pasted .bbl"
            print(
                f"dokimasia: {name}: {len(cites) - len(missing)}/{len(cites)} cited keys "
                f"rendered ({kind})"
            )
            for key in missing:
                print(f"dokimasia: {name}: \\cite{{{key}}} did not render", file=sys.stderr)
            problems += len(missing)
            continue
        if not bbl.exists():
            if info.needs_bibliography:
                unbuilt.append(name)
                print(f"dokimasia: {name}: not built, no {bbl.name}")
            else:
                bare.append(name)
                print(f"dokimasia: {name}: no bibliography, nothing to render")
            continue
        checked += 1
        cites = info.cites
        missing = sorted(cites - bbl_keys(_read(bbl)))
        print(f"dokimasia: {name}: {len(cites) - len(missing)}/{len(cites)} cited keys rendered")
        for key in missing:
            print(f"dokimasia: {name}: \\cite{{{key}}} did not render", file=sys.stderr)
        problems += len(missing)
    for line in _unreached(cfg, docs):
        print(line)
    names = f" ({', '.join(unbuilt)})" if unbuilt else ""
    extra = f", {len(bare)} without a bibliography" if bare else ""
    print(
        f"dokimasia: rendered: {checked} documents checked, {len(unbuilt)} not built{names}{extra}"
    )
    return problems + (len(unbuilt) if require_built else 0)


# --- verify ----------------------------------------------------------------------------

#: How long to wait before retrying, by attempt. A throttled host needs longer than a blip:
#: arXiv answers a burst of lookups with 406 for a while and then serves the same request
#: unchanged, so three retries two seconds apart all land inside the same block.
BACKOFF = (5, 20, 60)
#: Statuses that mean "you, later" rather than "no such record". arXiv uses 406 for this.
THROTTLED = (406, 429, 503)


def _mailto() -> str:
    return os.environ.get(MAILTO_ENV, "").strip()


def user_agent() -> str:
    mail = _mailto()
    return f"dokimasia/1.0 (+{HOMEPAGE}" + (f"; mailto:{mail})" if mail else ")")


def _get(url: str, tries: int = 3) -> tuple[str | None, str]:
    """The body, or None and a reason. The reason is the point.

    Returning a bare None made a throttled host and a missing record the same event, so a run
    that fetched nothing reported every entry as unverifiable and read as a bibliography
    problem. Callers pass the reason up so the summary can say which it was.
    """
    reason = "no attempt"
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent()})
            return urllib.request.urlopen(request, timeout=30).read().decode(), ""
        except urllib.error.HTTPError as error:
            reason = f"HTTP {error.code}"
            throttled = error.code in THROTTLED
        except Exception as error:
            reason = type(error).__name__
            throttled = False
        if attempt == tries - 1:
            return None, reason
        time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)] if throttled else 2 * (attempt + 1))
    return None, reason


def _loose(title: str | None) -> str:
    """Case-folded text with markup braces dropped and whitespace collapsed; keeps every script."""
    text = unicodedata.normalize("NFC", html.unescape(title or ""))
    return " ".join(text.replace("{", "").replace("}", "").casefold().split())


def titles_match(claimed: str | None, source: str | None) -> bool:
    """Whether the file's title agrees with the source record's.

    Crossref records routinely drop a subtitle, so a claimed title that merely extends what
    came back is not drift; a diverging one is. A title with no Latin letters normalises to
    nothing, so it is compared as text instead: `startswith("")` would call anything a match.
    """
    got, want = normalise(source), normalise(claimed)
    if not got:
        got, want = _loose(source), _loose(claimed)
    return got == want or (bool(got) and want.startswith(got))


def surname(author_field: str | None) -> str:
    """The first listed author's surname, normalised, from a BibTeX author field.

    Handles both BibTeX orders (`Yin, Dong` and `Dong Yin`) and brace-wrapped corporate
    authors. Only the first author is taken: comparing full lists means comparing
    `and others` truncations and accent macros against whatever the API returns, which
    produces noise rather than findings.
    """
    first = re.split(r"\s+and\s+", (author_field or "").strip())[0].strip()
    if first.startswith("{"):
        return normalise(first)
    parts = first.split()
    return normalise(first.split(",")[0] if "," in first else parts[-1] if parts else "")


def _matches_author(claimed: str | None, actual: list[str]) -> bool:
    """True when the claimed first-author surname appears in the source's first author.

    Compared by final token rather than by equality, so a multi-part surname survives:
    the file's `De Vaan, Mathijs` and the API's `Mathijs De Vaan` agree on `vaan`.
    """
    want = surname(claimed).split()
    if not want or not actual:
        return True  # nothing to compare is not a mismatch
    return want[-1] in normalise(actual[0]).split()


def _unparseable() -> dict:
    return {"failed": "unparseable response"}


def _arxiv_record(eprint: str) -> dict | None:
    body, reason = _get(f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(eprint)}")
    if not body:
        return {"failed": reason or "empty response"}
    # A 200 that is not a feed (a proxy's error page, a captive portal) is a failed lookup.
    # Only a valid feed with no entry means arXiv has no such record.
    if "<feed" not in body:
        return _unparseable()
    found = re.findall(r"<entry>(.*?)</entry>", body, re.S)
    if not found:
        return None
    entry = found[0]
    title = re.search(r"<title>(.*?)</title>", entry, re.S)
    published = re.search(r"<published>(\d{4})", entry)
    return {
        "title": " ".join(title.group(1).split()) if title else None,
        "authors": [
            " ".join(a.split()) for a in re.findall(r"<author>\s*<name>(.*?)</name>", entry, re.S)
        ],
        "year": int(published.group(1)) if published else None,
        "source": "arxiv",
    }


def _crossref_url(doi: str) -> str:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    mail = _mailto()
    return f"{url}?mailto={urllib.parse.quote(mail)}" if mail else url


def _crossref_record(doi: str) -> dict | None:
    body, reason = _get(_crossref_url(doi))
    if not body:
        return {"failed": reason or "empty response"}
    try:
        message = json.loads(body)["message"]
    except Exception:
        return _unparseable()
    if not isinstance(message, dict):
        return _unparseable()
    return crossref_fields(message)


def crossref_fields(message: dict) -> dict:
    """The comparable fields of one Crossref record. Separate from the fetch so it is testable."""
    titles = message.get("title") or []
    return {
        "title": titles[0] if titles else None,
        "authors": [
            " ".join(filter(None, (a.get("given"), a.get("family")))) or a.get("name", "")
            for a in message.get("author") or []
        ],
        "year": _crossref_year(message, "issued"),
        # A journal that posts online first has two years, and both are correct to cite by.
        # Springer gave "Ethics in the mining of software repositories" an issued date of
        # 2021-11-02 and a print date of 2022-01, and the entry cites it as EMSE 27(1), 2022,
        # which is what the journal's own citation says. Reporting that as drift every run is
        # how a scheduled check teaches its reader to ignore it.
        "print_year": _crossref_year(message, "published-print"),
        "source": "crossref",
    }


def _crossref_year(message: dict, field: str) -> int | None:
    parts = (message.get(field) or {}).get("date-parts") or [[None]]
    return parts[0][0] if parts and parts[0] else None


def _cacheable(record: dict | None) -> bool:
    """Whether a resolution result is worth keeping. A failed lookup is not a record, and
    caching one would freeze a throttled minute into the next fortnight of runs."""
    return isinstance(record, dict) and not record.get("failed")


def _cache_entry(record: dict, now: float) -> dict:
    """What gets stored for one resolved identifier. Paired with `_cache_hit`: an entry this
    writes must be one that reads back as a hit, which is what the schema stamp is for."""
    return {"record": record, "at": now, "schema": RECORD_SCHEMA}


def _cache_hit(hit: object, now: float) -> bool:
    """Whether a stored entry may be reused: same record shape, not a dict of nothing, not stale."""
    if not isinstance(hit, dict) or not isinstance(hit.get("record"), dict):
        return False
    if hit.get("schema") != RECORD_SCHEMA:
        return False
    return now - hit.get("at", 0) < CACHE_TTL


def _load_cache(path: Path) -> dict:
    """The stored records. A file that is not a JSON object is refused, never overwritten:
    it may be something else that happens to sit at the configured path."""
    if not path.exists():
        return {}
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"cache file {path} is unreadable ({error}); fix or remove it") from error
    if not isinstance(store, dict):
        raise ConfigError(f"cache file {path} is not a JSON object; fix or remove it")
    return store


@dataclass(frozen=True)
class _Reference:
    """One thing verify can resolve: a `.bib` entry's fields, or a hand-written entry's text."""

    key: str
    #: How the entry is named in output. A hand-written key also names its document, since
    #: two papers may each print their own `smith2020`.
    label: str
    eprint: str | None
    doi: str | None
    fields: dict[str, str] | None = None
    item: Bibitem | None = None


def _references(cfg: Config) -> list[_Reference]:
    docs = [read_document(p) for p in documents(cfg)]
    refs = []
    for _, _, key, body in _all_entries(cfg, any(d.hand_written for d in docs)):
        fields = parse_fields(body)
        refs.append(_Reference(key, key, fields.get("eprint"), fields.get("doi"), fields=fields))
    for item in _unique_bibitems(docs):
        eprint, doi = inline_ids(item.text)
        label = f"{item.key} ({_name(cfg, item.file)})"
        refs.append(_Reference(item.key, label, eprint, doi, item=item))
    return refs


def _accepted_years(record: dict) -> set[int]:
    """Every year the source dates the work by: a journal that posts online first has two."""
    return {y for y in (record.get("year"), record.get("print_year")) if y is not None}


def _bib_findings(
    cfg: Config, key: str, fields: dict[str, str], record: dict
) -> list[tuple[str, str, str]]:
    findings: list[tuple[str, str, str]] = []
    claimed = fields.get("title")
    if key not in cfg.title_exempt:
        # Crossref records routinely drop a subtitle, so a claimed title that merely
        # extends what came back is not drift; a diverging one is.
        if not titles_match(claimed, record["title"]):
            findings.append(("title", str(claimed), record["title"]))
    if key not in cfg.record_exempt:
        authors = fields.get("author")
        source_authors = record.get("authors") or []
        if not _matches_author(authors, source_authors):
            findings.append(("first author", str(authors), source_authors[0]))
        claimed_year = fields.get("year", "").strip()
        journal = fields.get("journal", "").lower()
        # Only where the two dates mean the same thing. See the module docstring.
        comparable = record.get("source") == "crossref" or "arxiv preprint" in journal
        accepted = _accepted_years(record)
        if comparable and claimed_year.isdigit() and accepted and int(claimed_year) not in accepted:
            findings.append(("year", claimed_year, "/".join(str(y) for y in sorted(accepted))))
    return findings


def _quoted_span(text: str, opening: re.Match[str]) -> tuple[str, int] | None:
    """The text inside a quote that opens at `opening`, and the index after its close."""
    kind = opening.group()
    if kind == "``":
        depth, i = 1, opening.end()
        while i < len(text) and depth:
            depth += text.startswith("``", i) - text.startswith("''", i)
            i += 2 if text.startswith(("``", "''"), i) else 1
        return (text[opening.end() : i - 2], i) if not depth else None
    if kind == "\u201c":
        end = text.find("\u201d", opening.end())
        return (text[opening.end() : end], end + 1) if end >= 0 else None
    if kind.startswith("\\enquote"):
        end = _close_brace(text, opening.end())
        return text[opening.end() : end - 1], end
    ending = _STRAIGHT_CLOSE.search(text, opening.end())
    return (text[opening.end() : ending.start()], ending.end()) if ending else None


def quoted_title(text: str) -> tuple[int, str] | None:
    """The printed title, where the entry quotes it, and where it starts; else None.

    IEEE, Chicago, MLA and the like quote the title and close it with punctuation, `Title,''`.
    Only the first quoted span can be the title. When it is not one (a quoted word inside an
    unquoted title, a nickname, a chapter quoted without punctuation) or it follows `In`, the
    entry has no title this can compare: looking further would find the quoted book a
    fabricated chapter borrowed its DOI from. Nested TeX quotes are counted, so
    ``On ``robust'' estimation,'' is one title.
    """
    opening = _QUOTE_OPEN.search(text)
    if not opening or _IN_WORD.search(text[: opening.start()]):
        return None
    span = _quoted_span(text, opening)
    if span is None:
        return None
    inner, close = span
    after = text[close:].lstrip()[:1]
    if inner.rstrip()[-1:] in (",", ".", "?", "!") or after in (",", "."):
        return opening.start(), inner
    return None


def _first_surnames(authors: str) -> set[str]:
    """Spellings of the first author's surname in a printed author list.

    The last word of the first segment that is not an initial or a suffix, joined to the word
    before it only when that word is a particle, since `Le Cun` and `LeCun` are one name.
    Joining any two words would let a given name and surname, `Jian Li`, pass as another
    author's `Jianli`. `J.~Doe, A.~Roe` and `Doe, J.` give `doe`.
    """
    first = _AUTHOR_BREAK.split(authors, maxsplit=1)[0]
    words = [w for w in normalise(first).split() if len(w) > 1 and w not in _NOT_NAMES]
    if not words:
        return set()
    if len(words) > 1 and words[-2] in _PARTICLES:
        return {words[-1], words[-2] + words[-1]}
    return {words[-1]}


def _family_names(name: str) -> set[str]:
    """Spellings of a source author's family name: the last word, joined to the word before
    it when that is a particle. Any other word may be a given name, and a fabricated author
    printed surname-first, `LIU Kaiming`, would match the real `Kaiming He` on it."""
    words = [w for w in normalise(name).split() if w not in _NOT_NAMES]
    if len(words) > 1 and words[-2] in _PARTICLES:
        return {words[-1], words[-2] + words[-1]}
    return set(words[-1:])


def _printed_findings(
    cfg: Config, key: str, text: str, record: dict
) -> list[tuple[str, str, str]] | None:
    """Drift for a hand-written entry, or None when its title cannot be found to compare.

    Only a quoted title is compared, by the rule a `.bib` title is held to. A printed entry
    has no fields, and every attempt to find an unquoted title in free text either passed a
    fabricated title wrapped around a real one or reported correct entries as drift: a
    verifier that guesses is worse than one that says it did not look. The author list is
    what precedes the title, and its first surname must be in the source's first author, as
    for a `.bib` entry; a title printed first leaves no author to compare. A year is compared
    where the record is Crossref's, and against arXiv only where a year follows the arXiv id,
    which is how a preprint is dated. Any printed year matching is enough for Crossref, since
    the text may also carry an access date.
    """
    found = quoted_title(text)
    if found is None:
        return None
    at, title = found
    findings: list[tuple[str, str, str]] = []
    if key not in cfg.title_exempt and not titles_match(title, record["title"]):
        findings.append(("title", " ".join(title.split()), record["title"]))
    if key in cfg.record_exempt:
        return findings
    shown = text if len(text) <= 200 else text[:197] + "..."
    source_authors = record.get("authors") or []
    surnames = _first_surnames(text[:at])
    if source_authors and surnames and not surnames & _family_names(source_authors[0]):
        findings.append(("first author", shown, source_authors[0]))
    accepted = _accepted_years(record)
    if record.get("source") == "crossref":
        bare = _INLINE_DOI.sub(" ", _INLINE_ARXIV.sub(" ", _URL.sub(" ", text)))
        bare = _PAGE_RANGE.sub(" ", bare)
        claimed = {int(y) for y in _YEAR.findall(bare)}
    else:
        # A year after a later version, `arXiv:1412.6980v9, 2017`, dates that version, not
        # the first posting the record carries.
        claimed = {
            int(m.group(2))
            for m in _PREPRINT_YEAR.finditer(text)
            if not re.search(r"v(?:[2-9]|\d{2,})\b", m.group(0))
        }
    if claimed and accepted and not claimed & accepted:
        mine = "/".join(str(y) for y in sorted(claimed))
        findings.append(("year", mine, "/".join(str(y) for y in sorted(accepted))))
    return findings


def verify(cfg: Config, delay: float = 3.0) -> int:
    """Resolve identifiers and compare titles. Returns the number of mismatches.

    Unresolvable entries are counted separately and never reported as findings. An
    API that is down, rate limiting, or simply missing a record says nothing about
    whether the entry is right. A hand-written entry is resolved only through an arXiv id
    or DOI printed in it, never by searching for its title: a search hit is weaker evidence
    than a resolved identifier, and counting it as verified would blur what verified means.
    """
    note_unmatched_excludes(cfg)
    drift = checked = exempted = cached = 0
    unresolved: list[str] = []
    unverifiable: list[str] = []
    uncompared: list[str] = []
    #: Why each unresolved entry was unresolved, so a blocked run reads as a blocked run.
    why: dict[str, int] = {}
    now = time.time()
    cache_path = cfg.root / cfg.cache
    store = _load_cache(cache_path)
    refs = _references(cfg)
    any_printed = any(ref.item is not None for ref in refs)
    for ref in refs:
        key, eprint, doi = ref.key, ref.eprint, ref.doi
        ident = (eprint or doi or "").strip()
        if not ident:
            # `url` and `howpublished` satisfy lint but there is nothing here to
            # resolve, so no run of verify will ever check this entry. Named below.
            unverifiable.append(ref.label)
            continue
        hit = store.get(ident)
        record = None
        if isinstance(hit, dict) and _cache_hit(hit, now):
            record, cached = hit["record"], cached + 1
        else:
            if eprint:
                record = _arxiv_record(eprint.strip())
                time.sleep(delay)
            if record is None and doi:
                record = _crossref_record(doi.strip())
                time.sleep(1)
            # A lookup that failed is not a record. Caching it would freeze a throttled
            # minute into the next fortnight of runs.
            if record is not None and _cacheable(record):
                store[ident] = _cache_entry(record, now)
        if record is None or record.get("title") is None:
            unresolved.append(ref.label)
            reason = (record or {}).get("failed") or "no matching record"
            why[reason] = why.get(reason, 0) + 1
            continue
        if ref.item is not None:
            compared = _printed_findings(cfg, key, ref.item.text, record)
            if compared is None:
                # The identifier resolved, so the work exists; whether this entry describes
                # it is a question the printed text does not let us answer.
                uncompared.append(ref.label)
                continue
            findings = compared
        else:
            findings = _bib_findings(cfg, key, ref.fields or {}, record)
        checked += 1

        reasons = [r for r in (cfg.title_exempt.get(key), cfg.record_exempt.get(key)) if r]
        for reason in reasons:
            print(f"dokimasia: exempt: {ref.label} -- {reason}")
        exempted += bool(reasons)

        for what, mine, theirs in findings:
            drift += 1
            print(f"dokimasia: {what} drift: {ref.label}", file=sys.stderr)
            print(f"    file  : {mine}", file=sys.stderr)
            print(f"    source: {theirs}", file=sys.stderr)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(store, indent=0, sort_keys=True))
    except OSError as error:
        print(f"dokimasia: cache not written: {cache_path}: {error}", file=sys.stderr)
    # The count appears only where hand-written entries exist, so a .bib project's summary
    # line reads as it always has.
    unmatched = f", uncompared {len(uncompared)}" if any_printed else ""
    print(
        f"dokimasia: verified {checked}, exempt {exempted}, unresolved {len(unresolved)}, "
        f"unverifiable {len(unverifiable)}{unmatched}, drift {drift} ({cached} from cache)"
    )
    if uncompared:
        print(
            "dokimasia: uncompared -- the identifier resolved, but the entry does not quote its "
            "title, so nothing printed can be matched to the source; check these by hand:"
        )
        for label in sorted(uncompared):
            print(f"    {label}")
    if unverifiable:
        printed = " (for a hand-written entry, none printed)" if any_printed else ""
        print(
            f"dokimasia: unverifiable -- no eprint or doi{printed}, "
            "so verify can never check these:"
        )
        for label in sorted(unverifiable):
            print(f"    {label}")
    if unresolved:
        # Naming the reason is what separates "the bibliography has 67 bad identifiers"
        # from "the host stopped answering a third of the way in", which look identical
        # in a list of keys.
        breakdown = ", ".join(f"{reason} x{count}" for reason, count in sorted(why.items()))
        print(f"dokimasia: unresolved -- identifier present, lookup did not answer ({breakdown}):")
        for label in sorted(unresolved):
            print(f"    {label}")
        if any(f"HTTP {code}" in why for code in THROTTLED):
            print(
                "dokimasia: at least one host was throttling this run, so these say nothing "
                "about the entries; rerun later rather than editing them"
            )
    return drift


# --- command line ----------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        print(f"dokimasia: {message}", file=sys.stderr)
        raise SystemExit(2)


def _resolve_docs(cfg: Config, names: list[str]) -> list[Path]:
    docs = []
    for name in names:
        for candidate in (Path(name), cfg.root / name):
            if candidate.is_file():
                docs.append(candidate.resolve())
                break
        else:
            raise ConfigError(f"no such document: {name}")
    return docs


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="dokimasia", description="Bibliography guard for LaTeX projects.")
    parser.add_argument("--root", type=Path, help="project root (default: found from the cwd)")
    parser.add_argument(
        "--require-built", action="store_true", help="rendered: a document with no .bbl fails"
    )
    parser.add_argument("mode", nargs="?", default="lint", choices=("lint", "verify", "rendered"))
    parser.add_argument("docs", nargs="*", metavar="DOC.tex", help="rendered: documents to check")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.root)
        if args.mode == "lint":
            return 1 if lint(cfg) else 0
        if args.mode == "verify":
            return 1 if verify(cfg) else 0
        return 1 if rendered(cfg, _resolve_docs(cfg, args.docs), args.require_built) else 0
    except ConfigError as error:
        print(f"dokimasia: config error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
