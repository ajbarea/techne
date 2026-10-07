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

Three verify outcomes, deliberately distinct, because conflating them is how a blind spot goes
quiet. **verified** resolved and matched. **unresolved** carried an identifier that the API did
not answer for -- transient, says nothing about the entry. **unverifiable** carries no `eprint`
and no `doi` at all, so there is nothing to resolve and no run will ever check it. `lint`
accepts those entries because `url` and `howpublished` are resolvable-by-a-human; `verify`
cannot follow them, and prints them by name every run so the set stays visible rather than
hiding inside a count.

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

#: Not entries: they hold macros and text, and their first token is not a key.
NON_ENTRIES = ("string", "preamble", "comment")

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
    orphans: bool = True
    intake: Path | None = None
    staged_headings: tuple[str, ...] = ("not yet positioned", "do not cite")
    #: Entries whose title deliberately differs from the source record. Only for an upstream
    #: record that is itself wrong: a title differing because ours is out of date is drift.
    title_exempt: dict[str, str] = dc_field(default_factory=dict)
    #: Same contract, for first author and year.
    record_exempt: dict[str, str] = dc_field(default_factory=dict)


_TOP_KEYS = {"bib", "exclude", "cache", "orphans", "intake", "exempt"}
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


def parse_config(root: Path, table: dict) -> Config:
    """Build a Config from a parsed TOML table, rejecting anything it does not know."""
    _unknown(table, _TOP_KEYS, "the configuration")
    kwargs: dict = {"root": root}
    if "bib" in table:
        kwargs["bib"] = tuple(root / p for p in _strings(table["bib"], "bib"))
    if "exclude" in table:
        kwargs["exclude"] = frozenset(_strings(table["exclude"], "exclude"))
    if "cache" in table:
        if not isinstance(table["cache"], str) or not table["cache"]:
            raise ConfigError("cache must be a non-empty string")
        kwargs["cache"] = Path(table["cache"])
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
        tool = _read_toml(pyproject).get("tool", {})
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
    """First ancestor holding a configuration, else the git top-level, else `cwd`."""
    for directory in (cwd, *cwd.parents):
        if _config_table(directory) is not None:
            return directory
    return _git_toplevel(cwd) or cwd


def load_config(root: Path | None = None, cwd: Path | None = None) -> Config:
    """Resolve the project root and read its configuration; every key is optional."""
    root = (root or find_root((cwd or Path.cwd()).resolve())).resolve()
    if not root.is_dir():
        raise ConfigError(f"root {root} is not a directory")
    return parse_config(root, _config_table(root) or {})


# --- files -----------------------------------------------------------------------------


def _walk(cfg: Config, suffix: str) -> list[Path]:
    """Files under root with `suffix`, skipping excluded, hidden and node_modules directories."""
    found: list[Path] = []
    for here, dirs, files in os.walk(cfg.root):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in cfg.exclude and not d.startswith(".") and d != "node_modules"
        )
        found += [Path(here) / f for f in sorted(files) if f.endswith(suffix)]
    return found


def bib_files(cfg: Config) -> list[Path]:
    if cfg.bib is not None:
        missing = [p for p in cfg.bib if not p.is_file()]
        if missing:
            raise ConfigError(f"bib file not found: {missing[0]}")
        return list(cfg.bib)
    found = _walk(cfg, ".bib")
    if not found:
        raise ConfigError(f"no .bib files under {cfg.root}")
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
    """Index just past the brace that closes the one opened before `start`."""
    i, depth = start, 1
    while i < len(text) and depth:
        depth += (text[i] == "{") - (text[i] == "}")
        i += 1
    return i


def entries(text: str):
    """Yield `(type, key, body)` per entry, brace-matched so nested `{}` survive.

    A regex that stops at the first `}` truncates any entry using brace protection
    (`{LLM}s`), which reads as a title mismatch that is not there. `@string`, `@preamble`
    and `@comment` are skipped whole: their first token is not a key, and a `@comment`
    may quote entries that are not part of the bibliography.
    """
    head = re.compile(r"@(\w+)\s*\{")
    pos = 0
    while match := head.search(text, pos):
        kind = match.group(1).lower()
        end = _close_brace(text, match.end())
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


def normalise(value: str | None) -> str:
    """Collapse a title to comparable form: no LaTeX, no punctuation, no case.

    Brace protection and accent macros are presentation, not content, so `{LLM}s` and
    `LLMs` have to compare equal or every correctly-written entry reports as drift.
    """
    # The arXiv Atom feed returns `&amp;` where the entry has `\&`. Left alone, the
    # entity survives as the word "amp" and every title containing an ampersand
    # reports as drift.
    value = html.unescape(value or "")
    value = re.sub(r"\\[a-zA-Z]+", "", value)
    # Braces are removed rather than treated as separators. Turning them into spaces
    # splits `{LLM}s` into "llm s", which never equals the source record's "LLMs" --
    # every correctly brace-protected entry would report as drift.
    value = value.replace("{", "").replace("}", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


# --- citations -------------------------------------------------------------------------

_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%.*")
_CITE_HEAD = re.compile(r"\\([A-Za-z]*cite[A-Za-z]*)\*?")
_CITE_ARGS = re.compile(r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]*)\}")
_MORE_ARGS = re.compile(r"(?:\s*\[[^\]]*\])*\s*\{([^}]*)\}")
#: Commands whose name contains "cite" but whose argument is not a key list.
_NOT_CITES = {
    "citestyle",
    "setcitestyle",
    "citetext",
    "citeindextrue",
    "citeindexfalse",
    "DeclareCiteCommand",
}
_INCLUDE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]*)\}")


def strip_comments(text: str) -> str:
    """Drop unescaped `%` to end of line; `50\\%` is a percent sign, not a comment."""
    return _COMMENT.sub(r"\1", text)


def cite_keys(text: str) -> set[str]:
    """Keys cited by any `...cite...` command, with up to two optional arguments.

    Covers natbib (`\\citep[see][p.~3]{a,b}`), biblatex (`\\parencite`, `\\autocite*`) and
    `\\nocite`. `\\nocite{*}` names no key, and `#1` in a macro definition is not one.
    """
    text = strip_comments(text)
    keys: set[str] = set()
    for head in _CITE_HEAD.finditer(text):
        if head.group(1) in _NOT_CITES:
            continue
        args = _CITE_ARGS.match(text, head.end())
        while args:
            keys |= {k.strip() for k in args.group(1).split(",") if k.strip()}
            # biblatex `\cites{a}{b}` and `\textcites[..]{a}[..]{b}` chain argument groups.
            args = _MORE_ARGS.match(text, args.end()) if head.group(1).endswith("cites") else None
    return {k for k in keys if k != "*" and not k.startswith("#")}


def _included(text: str, base: Path) -> list[Path]:
    found = []
    for name in _INCLUDE.findall(strip_comments(text)):
        raw = base / name.strip()
        for candidate in (raw, raw.with_name(raw.name + ".tex")):
            if candidate.is_file():
                found.append(candidate)
                break
    return found


def document_files(doc: Path) -> list[Path]:
    """The document and every file reached through `\\input`, `\\include`, `\\subfile`.

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
        pending += _included(_read(path), doc.parent)
    return list(seen)


def document_cites(doc: Path) -> set[str]:
    keys: set[str] = set()
    for path in document_files(doc):
        keys |= cite_keys(_read(path))
    return keys


def documents(cfg: Config) -> list[Path]:
    """Every `.tex` under root with a `\\documentclass` outside a comment."""
    return [
        p for p in _walk(cfg, ".tex") if re.search(r"\\documentclass", strip_comments(_read(p)))
    ]


def all_cited_keys(cfg: Config) -> set[str]:
    """Every key any `.tex` under root cites, including fragments no document includes."""
    keys: set[str] = set()
    for path in _walk(cfg, ".tex"):
        keys |= cite_keys(_read(path))
    return keys


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


def _all_entries(cfg: Config) -> list[tuple[Path, str, str, str]]:
    return [
        (path, kind, key, body)
        for path in bib_files(cfg)
        for kind, key, body in entries(_read(path))
    ]


def lint(cfg: Config) -> int:
    """Offline checks. Returns the number of findings; prints one line each."""
    parsed = _all_entries(cfg)
    findings: list[str] = []

    homes: dict[str, list[str]] = {}
    for path, _, key, _ in parsed:
        homes.setdefault(key, []).append(_name(cfg, path))
    for key, where in sorted(homes.items()):
        if len(where) > 1:
            findings.append(f"duplicate key: {key} appears {len(where)} times ({', '.join(where)})")

    for _, _, key, body in parsed:
        fields = parse_fields(body)
        journal = fields.get("journal", "")
        prose_id = _PROSE_ARXIV.search(journal)
        if not set(fields) & set(ID_FIELDS):
            findings.append(
                f"arXiv id present but only in prose: {key}"
                if prose_id
                else f"no resolvable identifier: {key}"
            )
            continue
        eprint = fields.get("eprint")
        if eprint is not None and not ARXIV_ID.match(eprint.strip()):
            findings.append(f"malformed eprint: {key} = {eprint!r}")
        doi = fields.get("doi")
        if doi is not None and not doi.strip().startswith("10."):
            findings.append(f"malformed doi: {key} = {doi!r}")
        url = fields.get("url")
        if url is not None and not url.strip().startswith("http"):
            findings.append(f"malformed url: {key} = {url!r}")
        if prose_id and eprint is None:
            findings.append(f"arXiv id present but only in prose: {key}")

    keys = set(homes)
    for table, exempt in (("title", cfg.title_exempt), ("record", cfg.record_exempt)):
        for key in sorted(set(exempt) - keys):
            findings.append(f"exemption for missing entry: {key} (exempt.{table})")

    cited = all_cited_keys(cfg)  # one walk of the .tex tree, not two
    for key in sorted(cited - keys):
        findings.append(f"dangling citation: \\cite{{{key}}} has no entry")
    if cfg.orphans:
        for key in sorted(keys - cited - accounted_keys(cfg)):
            findings.append(
                f"orphan entry: {key} is cited nowhere and the intake log does not name it"
            )

    staged = staged_keys(cfg)
    for key in sorted(staged & cited):
        findings.append(
            f"cited but unread: {key} is cited in a document while the intake log still "
            f"stages it as unpositioned -- read it and position it, or drop the citation"
        )

    for line in findings:
        print(f"dokimasia: {line}", file=sys.stderr)
    print(
        f"dokimasia: {len(parsed)} entries, {len(staged & keys)} staged unread, "
        f"{len(findings)} finding(s)"
    )
    return len(findings)


# --- rendered --------------------------------------------------------------------------

_BIBITEM = re.compile(r"\\bibitem\s*(?:\[.*?\])?\s*\{([^}]*)\}", re.S)
_ENTRY = re.compile(r"\\entry\s*\{([^}]*)\}\s*\{")


def bbl_keys(text: str) -> set[str]:
    """Keys a `.bbl` renders: `\\bibitem[label]{key}` (BibTeX) or `\\entry{key}{` (biber)."""
    return {k.strip() for k in _BIBITEM.findall(text) + _ENTRY.findall(text)}


def rendered(cfg: Config, docs: list[Path] | None = None, require_built: bool = False) -> int:
    """Assert every key each document cites appears in its own `.bbl`.

    Compares against the keys that document cites, not against every key in the shared
    bibliography: a count of all entries scores a skeleton using `\\nocite{*}` full marks
    and fails a document that cites a normal subset. Keys are parsed out of the `.bbl`
    rather than substring-matched, so `li2020` does not pass because `li2020b` rendered.
    A document with no `.bbl` is not built: named, never silently passed.
    """
    docs = documents(cfg) if not docs else docs
    problems = 0
    checked = 0
    unbuilt: list[str] = []
    for doc in docs:
        name = _name(cfg, doc)
        bbl = doc.with_suffix(".bbl")
        if not bbl.exists():
            unbuilt.append(name)
            print(f"dokimasia: {name}: not built, no {bbl.name}")
            continue
        checked += 1
        cites = document_cites(doc)
        missing = sorted(cites - bbl_keys(_read(bbl)))
        print(f"dokimasia: {name}: {len(cites) - len(missing)}/{len(cites)} cited keys rendered")
        for key in missing:
            print(f"dokimasia: {name}: \\cite{{{key}}} did not render", file=sys.stderr)
        problems += len(missing)
    names = f" ({', '.join(unbuilt)})" if unbuilt else ""
    print(f"dokimasia: rendered: {checked} documents checked, {len(unbuilt)} not built{names}")
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


def verify(cfg: Config, delay: float = 3.0) -> int:
    """Resolve identifiers and compare titles. Returns the number of mismatches.

    Unresolvable entries are counted separately and never reported as findings. An
    API that is down, rate limiting, or simply missing a record says nothing about
    whether the entry is right.
    """
    drift = checked = exempted = cached = 0
    unresolved: list[str] = []
    unverifiable: list[str] = []
    #: Why each unresolved entry was unresolved, so a blocked run reads as a blocked run.
    why: dict[str, int] = {}
    now = time.time()
    cache_path = cfg.root / cfg.cache
    try:
        store = json.loads(cache_path.read_text())
    except Exception:
        store = {}
    if not isinstance(store, dict):
        store = {}
    for _, _, key, body in _all_entries(cfg):
        fields = parse_fields(body)
        claimed = fields.get("title")
        eprint, doi = fields.get("eprint"), fields.get("doi")
        ident = (eprint or doi or "").strip()
        if not ident:
            # `url` and `howpublished` satisfy lint but there is nothing here to
            # resolve, so no run of verify will ever check this entry. Named below.
            unverifiable.append(key)
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
            unresolved.append(key)
            reason = (record or {}).get("failed") or "no matching record"
            why[reason] = why.get(reason, 0) + 1
            continue
        checked += 1

        reasons = [r for r in (cfg.title_exempt.get(key), cfg.record_exempt.get(key)) if r]
        for reason in reasons:
            print(f"dokimasia: exempt: {key} -- {reason}")
        exempted += bool(reasons)

        findings: list[tuple[str, str, str]] = []
        if key not in cfg.title_exempt:
            # Crossref records routinely drop a subtitle, so a claimed title that merely
            # extends what came back is not drift; a diverging one is.
            got, want = normalise(record["title"]), normalise(claimed)
            if got != want and not want.startswith(got):
                findings.append(("title", str(claimed), record["title"]))
        if key not in cfg.record_exempt:
            authors = fields.get("author")
            source_authors = record.get("authors") or []
            if not _matches_author(authors, source_authors):
                findings.append(("first author", str(authors), source_authors[0]))
            claimed_year = fields.get("year", "").strip()
            actual_year = record.get("year")
            journal = fields.get("journal", "").lower()
            # Only where the two dates mean the same thing. See the module docstring.
            comparable = record.get("source") == "crossref" or "arxiv preprint" in journal
            accepted = {y for y in (actual_year, record.get("print_year")) if y is not None}
            if (
                comparable
                and claimed_year.isdigit()
                and accepted
                and int(claimed_year) not in accepted
            ):
                findings.append(("year", claimed_year, "/".join(str(y) for y in sorted(accepted))))

        for what, mine, theirs in findings:
            drift += 1
            print(f"dokimasia: {what} drift: {key}", file=sys.stderr)
            print(f"    file  : {mine}", file=sys.stderr)
            print(f"    source: {theirs}", file=sys.stderr)
    try:
        cache_path.write_text(json.dumps(store, indent=0, sort_keys=True))
    except OSError:
        pass
    print(
        f"dokimasia: verified {checked}, exempt {exempted}, unresolved {len(unresolved)}, "
        f"unverifiable {len(unverifiable)}, drift {drift} ({cached} from cache)"
    )
    if unverifiable:
        print("dokimasia: unverifiable -- no eprint or doi, so verify can never check these:")
        for key in sorted(unverifiable):
            print(f"    {key}")
    if unresolved:
        # Naming the reason is what separates "the bibliography has 67 bad identifiers"
        # from "the host stopped answering a third of the way in", which look identical
        # in a list of keys.
        breakdown = ", ".join(f"{reason} x{count}" for reason, count in sorted(why.items()))
        print(f"dokimasia: unresolved -- identifier present, lookup did not answer ({breakdown}):")
        for key in sorted(unresolved):
            print(f"    {key}")
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
