#!/usr/bin/env python3
"""Cleanup check: finished work lives in git and GitHub, not in growing files.

Usage:
    cleanup.py check [--ci] [--only PART ...] [--transient GLOB ...] [--keep GLOB ...] ROOT ...
    cleanup.py done-log ROOT
    cleanup.py prune [--apply] ROOT

check reports, per repo root, one line per finding (or one passing line):
  roadmap    ROADMAP.md has a done-log section (Completed, Shipped, Done, Changelog, ...)
             or runs past its line budget
  impl       IMPL.md runs past its line budget
  agents     an agent instruction file (AGENTS.md, CLAUDE.md, .claude/CLAUDE.md,
             CLAUDE.local.md, .github/copilot-instructions.md, .claude/skill-context.md)
             (or a repo `agent_file` glob, such as a memory index) runs past its line or
             byte budget
  rules      a rule or lesson (a `### slug:` entry in a `rules` file) whose newest Reviewed,
             Since or Incidents date is over review_days old, or a rules file without
             entries and without a `reviewed:` date: rules are pruned as well as added
  flaky      a retry or flaky marker in a test or test config (pytest-rerunfailures, @flaky,
             retries:, retryTimes, a retry action) without `quarantine: until YYYY-MM-DD`
             within quarantine_days, or past it: fix the test or delete it
  transient  a file matched by a transient glob has no `owner` plus `expires` or
             `reviewed` frontmatter (its own, for a markdown file, else the nearest
             README.md above it), or is past it
--ci exits 1 when any finding is printed; without it check always exits 0, as the other
sisters checks do. --no-dates checks only what no calendar date decides (a pull-request gate);
expiry, review age and quarantine ends then run on a schedule and in sisters check 18.
--only limits the parts run. --transient and --keep add to the repo's
own globs.

done-log prints each done-log section of ROOT/ROADMAP.md with its line span, so its
lessons and open follow-ups can be harvested before it is deleted. prune deletes those
sections: a dry run without --apply. It refuses a ROADMAP.md that is not a tracked,
unmodified regular file (the deleted text must stay in git history), a repo whose
`## cleanup` section says `- prune: off`, and a sister marked `registered_report = true`
in ~/.claude/techne.toml.

Budgets and globs come from the `## cleanup` section of ROOT/.claude/skill-context.md:
    - roadmap_lines: 300
    - impl_lines: 50
    - agent_lines: 200
    - agent_bytes: 25000
    - agent_file: projects/*/memory/MEMORY.md
    - review_days: 90
    - quarantine_days: 30
    - rules: plugins/techne/_shared/lessons/*.md
    - transient: review/**
    - keep: review/README.md
    - prune: off (registered report)
"""

# research(2026-11): agent instruction files under 200 lines ("Longer files consume more context
# and reduce adherence", https://code.claude.com/docs/en/memory), and 25,000 bytes, the one byte
# cap that page gives for context loaded every session (MEMORY.md's first 25KB); instruction bloat
# becomes deterministic checks (https://www.thoughtworks.com/radar/techniques/agent-instruction-bloat,
# https://addyosmani.com/blog/audit-your-agent-files/); owner + review date frontmatter with a
# threshold check (https://microsoft.github.io/hve-core/docs/contributing/documentation-maintenance,
# https://www.mintlify.com/library/how-to-keep-documentation-up-to-date-with-regular-reviews);
# history is the record, changelogs are generated
# (https://rufuspollock.com/2026-02-25-changelogs-lightweight-best-practice). The Claude Code team
# "turn misses into rules - and routinely prune them" and delete flaky tests rather than retry
# (Osmani, "How the Claude Code team thinks about verification", 2026-11); a quarantine carries
# an owner, an issue and an end date CI enforces, 30 days by default
# (https://oneuptime.com/blog/post/2026-07-28-quarantine-flaky-tests/view,
# https://handbook.gitlab.com/handbook/engineering/testing/quarantine-process/); retries kept
# 4,962 of 5,000 buggy builds green (https://devops.com/your-ci-retries-are-hiding-real-bugs).

from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULTS = {
    "roadmap_lines": 300,
    "impl_lines": 50,
    "agent_lines": 200,
    "agent_bytes": 25000,
    "review_days": 90,
    "quarantine_days": 30,
}
AGENT_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "CLAUDE.local.md",
    ".github/copilot-instructions.md",
    ".claude/skill-context.md",
)
PARTS = ("roadmap", "impl", "agents", "transient", "rules", "flaky")
MAX_READ = 4 << 20  # Claude Code skips an instruction file over 4 MiB; nothing here is larger
FRONT_MAX = 8192  # frontmatter sits in a file's first lines
# Folders no glob means: version control, environments and build output. Skipped in every walk.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "site",
    "dist",
    "build",
    "target",
}
GROUP_AT = 3  # past this many unowned files in one folder, one line names the folder

# A heading that is a log of finished work: the keyword is the whole heading, with at most a
# "recently"-style prefix and a time qualifier ("this week", "since 11-15", "(2026)", a date).
# "Complete the migration", "History and motivation" or "Archive format" are not logs.
DONE_HEADING = re.compile(
    r"^(?:(?:recently|already|previously)\s+|what(?:'s|\s+has|\s+was)?\s+)?"
    r"(?:completed|shipped|done|finished|landed|released|archived?|history|change\s*log|"
    r"release\s+notes)"
    r"(?:\s+(?:this|last)\s+(?:week|month|quarter|year)|\s+since\b.*|\s+in\s+\S+|"
    r"\s*\(.*\)|\s+20\d\d\b.*|\s+\d{1,2}-\d{2}\b.*|\s*:)?\s*$"
)
# CommonMark 0.31.2: an ATX heading has 0-3 spaces of indent (4.2); a backtick fence's info
# string has no backtick, and a fence closes only on the same character, at least as long,
# with nothing after it (4.5); a setext underline follows a paragraph line (4.3).
ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
OPEN_FENCE = re.compile(r"^ {0,3}(`{3,}(?=[^`]*$)|~{3,})")
CLOSE_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
BREAK = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*\r?$")  # a kept line ending passes
INDENTED = re.compile(r"^(?: {4}|\t)")
NOT_PARAGRAPH = re.compile(r"^ {0,3}(?:(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)|>|<)")
LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
# Lines prune will not cut across, since a Markdown reader may take them for a heading the scanner
# misjudged: a block quote, an HTML block, an indented heading-like `#` line (list content or
# code; `  #378)` is neither), and a
# setext-style underline right after a non-blank line.
UNMODELLED = re.compile(r"^(?: {0,3}(?:>|<[A-Za-z!/?])|[ \t]+#{1,6}(?:[ \t]|$))")
# HTML blocks (CommonMark 4.6): types 1-5 end at a marker, which may sit on the first line;
# types 6-7 end at a blank line. Block quotes are read the same way, to a blank line.
HTML_ENDS = (
    (
        re.compile(r"^ {0,3}<(?:script|pre|style|textarea)(?:[\s>]|$)", re.I),
        re.compile(r"</(?:script|pre|style|textarea)>", re.I),
    ),
    (re.compile(r"^ {0,3}<!--"), re.compile(r"-->")),
    (re.compile(r"^ {0,3}<\?"), re.compile(r"\?>")),
    (re.compile(r"^ {0,3}<![A-Za-z]"), re.compile(r">")),
    (re.compile(r"^ {0,3}<!\[CDATA\["), re.compile(r"\]\]>")),
)
BLOCK_START = re.compile(r"^ {0,3}(?:<[A-Za-z!/?]|>)")
# A link reference or footnote definition (CommonMark 4.7, GFM footnotes), in a list item too:
# it is global, so cutting it breaks every reference to it outside the cut.
LINK_DEF = re.compile(r"^[ \t]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)*\[(?:[^\]\\]|\\.)+\]:")
# One the scanner can vouch for: a label and a destination with no title on one line. It starts
# no paragraph, so the line under it is never its setext underline; any other definition-like
# line may be a paragraph instead, and is a hazard.
SIMPLE_DEF = re.compile(
    r"^ {0,3}\[[^\]\[\\]*[^\]\[\\\s][^\]\[\\]*\]:[ \t]+(?:<[^<>\n\\]*>|[^\s<>()\\]+)[ \t]*$"
)
# Line breaks str.splitlines honours and CommonMark does not: a prune refuses a text with one.
ODD_BREAKS = re.compile("[\v\f\x1c\x1d\x1e\x85\u2028\u2029]")


class Unreadable(Exception):
    pass


def read_text(path: Path, limit: int = MAX_READ, head: bool = False) -> str | None:
    """PATH's text, or None when there is none. Only a regular file is read, opened without
    blocking and checked through its descriptor, so a FIFO cannot hang the check. With HEAD,
    the first LIMIT bytes are returned instead of refusing a longer file."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    except (FileNotFoundError, NotADirectoryError):
        if os.path.islink(path):
            raise Unreadable("is a link to a missing file") from None
        return None
    except OSError as exc:
        raise Unreadable(exc.strerror or str(exc)) from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise Unreadable("is not a regular file")
        raw = f.read(limit + (0 if head else 1))
    if len(raw) > limit:
        raise Unreadable(f"is over {limit} bytes")
    return raw.decode("utf-8", errors="surrogateescape")


def byte_count(text: str) -> int:
    return len(text.encode("utf-8", errors="surrogateescape"))


def line_count(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


# --- config -------------------------------------------------------------------------------


class Config:
    def __init__(self) -> None:
        self.budgets = dict(DEFAULTS)
        self.transient: list[str] = []
        self.keep: list[str] = []
        self.agent_files: list[str] = []
        self.rules: list[str] = []
        self.prune_off: str | None = None
        self.errors: list[str] = []


def load_config(root: Path) -> Config:
    """The `## cleanup` section of ROOT/.claude/skill-context.md. A key that cannot be read is
    a finding, never a silent default."""
    cfg = Config()
    path = root / ".claude" / "skill-context.md"
    try:
        text = read_text(path)
    except Unreadable as exc:
        cfg.errors.append(f".claude/skill-context.md {exc} → make it a regular file")
        return cfg
    if text is None:
        return cfg
    section = re.search(r"^## cleanup[ \t]*(?:\r?\n|\Z)(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not section:
        return cfg
    for raw in section.group(1).splitlines():
        m = re.match(r"^\s*(?:[-*+]\s+)?(?:\*\*|__)?([A-Za-z_]+)\s*:(?:\*\*|__)?\s*(.*?)\s*$", raw)
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2)
        if key in DEFAULTS:
            if not re.fullmatch(r"[1-9][0-9]{0,5}", value):
                cfg.errors.append(
                    f"## cleanup: {key} {value!r} is not a whole number → write one, such as "
                    f"{DEFAULTS[key]}"
                )
                continue
            cfg.budgets[key] = int(value)
        elif key in ("transient", "keep", "agent_file", "rules"):
            if value.startswith("<"):  # the template's placeholder, not yet filled in
                continue
            if not value:
                cfg.errors.append(f"## cleanup: {key} has no glob → write one or delete the line")
                continue
            lists = {
                "transient": cfg.transient,
                "keep": cfg.keep,
                "agent_file": cfg.agent_files,
                "rules": cfg.rules,
            }
            lists[key].append(value)
        elif key == "prune":
            word = value.lower().strip("*_` ").split(" ")[0]
            if word == "off":
                cfg.prune_off = value
            elif word != "on":
                cfg.errors.append(f"## cleanup: prune {value!r} is neither off nor on → write one")
        else:
            cfg.errors.append(f"## cleanup: unknown key {key!r} → see cleanup.py's usage")
    return cfg


# --- globs --------------------------------------------------------------------------------


def glob_regex(glob: str) -> re.Pattern[str]:
    """A repo-relative glob: `**` crosses folders, `*` and `?` do not. A glob naming a folder
    (`review` or `review/`) covers everything under it."""
    g = glob.strip()
    while g.startswith("./"):
        g = g[2:]
    g = g.rstrip("/")
    out, i = [], 0
    while i < len(g):
        c = g[i]
        if g.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif g.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("(?:" + "".join(out) + ")(?:/.*)?\\Z")


def walk_files(root: Path):
    """Every file under ROOT as a repo-relative POSIX path, skipping SKIP_DIRS; one pass."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel = os.path.relpath(dirpath, root)
        prefix = "" if rel == "." else rel.replace(os.sep, "/") + "/"
        for name in sorted(filenames):
            yield prefix + name


# --- frontmatter --------------------------------------------------------------------------


def frontmatter(path: Path) -> dict[str, str] | None:
    """The `key: value` lines between a leading `---` and the next `---`, or None. Read through
    read_text, so a FIFO or a link to a device is never opened for a blocking read."""
    try:
        head = read_text(path, FRONT_MAX, head=True)
    except Unreadable:
        return None
    if head is None:
        return None
    lines = head.removeprefix("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            return fields
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*$", line)
        if m:
            fields[m.group(1).lower()] = m.group(2).strip("'\"")
    return None  # no closing fence within the first FRONT_MAX bytes


GOVERNING = ("owner", "expires", "reviewed")


def parse_date(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value) if re.fullmatch(r"\d{4}-\d\d-\d\d", value) else None
    except ValueError:
        return None


def freshness(fields: dict[str, str], today: dt.date | None, review_days: int) -> str | None:
    """Why FIELDS do not keep a file current, or None when they do. With TODAY None only what
    no date decides is checked: an owner, a date present and well formed."""
    if not fields.get("owner"):
        return "no owner"
    expires, reviewed = fields.get("expires"), fields.get("reviewed")
    if not expires and not reviewed:
        return "no expires or reviewed date"
    if expires:
        day = parse_date(expires)
        if day is None:
            return f"expires {expires!r} is not a YYYY-MM-DD date"
        if today is not None and day < today:
            return f"expired {day.isoformat()} (owner {fields['owner']})"
    if reviewed:
        day = parse_date(reviewed)
        if day is None:
            return f"reviewed {reviewed!r} is not a YYYY-MM-DD date"
        if today is not None and (today - day).days > review_days:
            owner = fields["owner"]
            return f"last reviewed {day.isoformat()}, over {review_days} days ago (owner {owner})"
    return None


def is_expired(fields: dict[str, str], today: dt.date | None) -> bool:
    """Whether FIELDS carry an `expires` date before TODAY: the one state a tool may delete on."""
    day = parse_date(fields.get("expires", ""))
    return today is not None and bool(fields.get("owner")) and day is not None and day < today


# --- checks -------------------------------------------------------------------------------


BLANK = re.compile("")  # the end of a block that closes at a blank line


class Scan:
    """One pass over a Markdown text: its ATX and setext headings outside code fences, as
    (line index, level, title), the indexes of every line inside a fence, and whether a line
    holds a shape the scanner does not model (a block quote or an HTML block)."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.heads: list[tuple[int, int, str]] = []
        self.fenced: set[int] = set()
        self.underlines: set[int] = set()  # setext underlines, which look like thematic breaks
        self.atx: set[int] = set()  # lines that are ATX headings
        # Lines whose reading the scanner cannot vouch for: block quotes, HTML, and a fence
        # opened with indent or inside a list item (CommonMark may close it with the item).
        self.hazards: set[int] = set()
        self.doubt_from: int | None = None  # the first such fence: every line past it is unsure
        self.open_fence: int | None = None  # where a fence opened that never closes
        fence: str | None = None
        block: re.Pattern[str] | None = None  # an HTML or quote block's end; BLANK: a blank line
        doubtful = False  # the open fence began indented or inside a list item
        para: int | None = None  # where the open paragraph started
        in_list = False  # inside a list item, until a blank line
        for i, raw in enumerate(self.lines):
            line = raw.expandtabs(4)
            if fence is not None:
                self.fenced.add(i)
                if doubtful:  # where CommonMark ends this fence is not certain
                    self.hazards.add(i)
                m = CLOSE_FENCE.match(line)
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                    fence, self.open_fence = None, None
                continue
            if block is not None:  # inside an HTML block or a block quote: no heading is read
                if block is BLANK and not line.strip():
                    block = None
                    para, in_list = None, False
                    continue
                self.hazards.add(i)
                # CommonMark may end a quote or a paragraph-like HTML line before the blank
                # line, so a fence or an HTML opener here may start a real block, one that
                # can run past blank lines: what follows is unsure.
                opens = OPEN_FENCE.match(line) or any(s.match(line) for s, _ in HTML_ENDS)
                if opens and self.doubt_from is None:
                    self.doubt_from = i
                if block is not BLANK and block.search(line):
                    block = None
                continue
            if not line.strip():
                para, in_list = None, False
                continue
            if BLOCK_START.match(line):
                self.hazards.add(i)
                ends = [e for s, e in HTML_ENDS if s.match(line)]
                if ends and ends[0].search(line):
                    para, in_list = None, False
                    continue  # a one-line block, such as <!-- reviewed: ... -->
                block = ends[0] if ends else BLANK
                para, in_list = None, False
                continue
            if UNMODELLED.match(raw):
                self.hazards.add(i)
            m = OPEN_FENCE.match(line)
            if m:
                doubtful = in_list or line[0] == " "
                if doubtful:
                    self.hazards.add(i)
                    if self.doubt_from is None:
                        self.doubt_from = i
                fence, para, in_list = m.group(1), None, False
                self.fenced.add(i)
                self.open_fence = i
                continue
            if INDENTED.match(line):
                continue  # code, a list item's content, or a paragraph's continuation
            u = SETEXT.match(line)
            if u and para is not None:
                title = " ".join(x.strip() for x in self.lines[para:i])
                self.heads.append((para, 1 if u.group(1)[0] == "=" else 2, title))
                self.underlines.add(i)
                para = None
                continue
            h = ATX.match(line)
            if h:
                self.heads.append((i, len(h.group(1)), (h.group(2) or "").strip()))
                self.atx.add(i)
                para, in_list = None, False
            elif BREAK.match(line):
                para, in_list = None, False
            elif NOT_PARAGRAPH.match(line):
                para, in_list = None, in_list or LIST_ITEM.match(line) is not None
            elif in_list:
                para = None  # a lazy continuation of a list item, never a setext heading
            elif para is None and SIMPLE_DEF.match(line):
                continue  # a link reference definition, which no underline makes a heading
            elif para is None:
                if LINK_DEF.match(line):
                    self.hazards.add(i)
                para = i

    def unfenced(self):
        """(1-based line number, line) for every line outside a code fence."""
        for i, line in enumerate(self.lines):
            if i not in self.fenced:
                yield i + 1, line


def done_sections(text: str, scan: Scan | None = None) -> list[tuple[int, int, str]]:
    """(first line, last line, heading) of each done-log section, 1-based and inclusive. A
    section runs to the next heading of its level or higher. A done-log nested in another is
    part of it."""
    scan = scan or Scan(text)
    heads = scan.heads
    found: list[tuple[int, int, str]] = []
    for n, (i, level, title) in enumerate(heads):
        if found and i < found[-1][1]:
            continue  # inside a done-log already found
        if not DONE_HEADING.match(normal_title(title)):
            continue
        end = len(scan.lines)
        for j, lv, _ in heads[n + 1 :]:
            if lv <= level:
                end = j
                break
        found.append((i + 1, end, title))
    return found


def normal_title(title: str) -> str:
    """A heading's words, lowercased, with markup, emoji and leading numbering removed."""
    t = re.sub(r"[`*_~\[\]]", "", title).lower()
    t = re.sub(r"^[^a-z]+", "", t)  # emoji, ✅, "3.", "—"
    return re.sub(r"\s+", " ", t).strip()


def check_roadmap(root: Path, cfg: Config) -> list[str]:
    try:
        text = read_text(root / "ROADMAP.md")
    except Unreadable as exc:
        return [f"ROADMAP.md {exc} → make it a regular file"]
    if text is None:
        return []
    out = [
        f"ROADMAP.md:{a} '{t}' keeps a log of finished work (lines {a}-{b}) → harvest its "
        "lessons and open follow-ups, then delete it (/techne:sisters clean); git and "
        "GitHub hold the record"
        for a, b, t in done_sections(text)
    ]
    n, budget = line_count(text), cfg.budgets["roadmap_lines"]
    if n > budget:
        out.append(
            f"ROADMAP.md has {n} lines, over its {budget}-line budget → cut shipped scope "
            "and history; keep milestones, next-up order, design rules and backlog"
        )
    if out and roster_refusal(root) == REGISTERED:
        return []  # its text is never edited, so no finding could be cleared; done-log shows it
    return out


def check_impl(root: Path, cfg: Config) -> list[str]:
    try:
        text = read_text(root / "IMPL.md")
    except Unreadable as exc:
        return [f"IMPL.md {exc} → make it a regular file"]
    if text is None:
        return []
    n, budget = line_count(text), cfg.budgets["impl_lines"]
    if n > budget:
        return [
            f"IMPL.md has {n} lines, over its {budget}-line budget → rewrite it as the "
            "current slice: done, next, verify"
        ]
    return []


def agent_paths(root: Path, cfg: Config) -> list[str]:
    """The fixed instruction files plus the repo's own `agent_file` globs, each once, in order."""
    return [
        *AGENT_FILES,
        *(f for f in matching_files(root, cfg.agent_files) if f not in AGENT_FILES),
    ]


def check_agents(root: Path, cfg: Config) -> list[str]:
    out = []
    lines_max, bytes_max = cfg.budgets["agent_lines"], cfg.budgets["agent_bytes"]
    fix = "move what a hook or check can enforce into one, and cut what the code shows"
    for rel in agent_paths(root, cfg):
        try:
            text = read_text(root / rel)
        except Unreadable as exc:
            out.append(f"{rel} {exc} → make it a regular file")
            continue
        if text is None:
            continue
        n, size = line_count(text), byte_count(text)
        if n > lines_max:
            out.append(
                f"{rel} has {n} lines, over the {lines_max}-line budget for agent instructions → "
                + fix
            )
        if size > bytes_max:
            out.append(
                f"{rel} has {size} bytes, over the {bytes_max}-byte budget for agent "
                "instructions → " + fix
            )
    return out


class Transient:
    """What the transient check found: unowned files by folder, and for each governing file
    (a note's own frontmatter or a README.md above) why it is stale and the files it governs."""

    def __init__(self) -> None:
        self.bare: dict[str, list[str]] = {}
        self.stale: dict[str, str] = {}
        self.governs: dict[str, list[str]] = {}
        self.expired: set[str] = set()  # governing files whose `expires` date has passed


def transient_status(root: Path, cfg: Config, today: dt.date | None) -> Transient:
    found = Transient()
    if not cfg.transient:
        return found
    want = [glob_regex(g) for g in cfg.transient]
    keep = [glob_regex(g) for g in cfg.keep]
    cache: dict[str, dict[str, str] | None] = {}

    def fm(rel: str) -> dict[str, str] | None:
        if rel not in cache:
            cache[rel] = frontmatter(root / rel)
        return cache[rel]

    def cover(rel: str) -> tuple[str, dict[str, str]] | None:
        """The file whose frontmatter governs REL: its own (markdown), else the nearest README.md
        in a folder above it, below the root."""
        if rel.lower().endswith(".md"):
            own = fm(rel)
            if own is not None and any(k in own for k in GOVERNING):
                return rel, own
        parts = rel.split("/")[:-1]
        while parts:
            readme = "/".join(parts) + "/README.md"
            if readme != rel and os.path.isfile(root / readme):
                got = fm(readme)
                if got is not None and any(k in got for k in GOVERNING):
                    return readme, got
            parts.pop()
        return None

    for rel in walk_files(root):
        if not any(r.match(rel) for r in want) or any(r.match(rel) for r in keep):
            continue
        got = cover(rel)
        if got is None:
            folder, _, name = rel.rpartition("/")
            found.bare.setdefault(folder, []).append(name)
            continue
        where, fields = got
        found.governs.setdefault(where, []).append(rel)
        why = freshness(fields, today, cfg.budgets["review_days"])
        if why:
            found.stale.setdefault(where, why)
        if is_expired(fields, today):
            found.expired.add(where)
    return found


def check_transient(root: Path, cfg: Config, today: dt.date | None) -> list[str]:
    status = transient_status(root, cfg, today)
    bare, stale = status.bare, status.stale
    out = []
    for folder, names in sorted(bare.items()):
        prefix = folder + "/" if folder else ""
        notes = [n for n in names if n.lower().endswith(".md") and n != "README.md"]
        if not folder or (len(names) == len(notes) and len(notes) <= GROUP_AT):
            out += [
                f"{prefix}{n} has no owner + expires frontmatter → add it, or harvest the file "
                "into the repo that owns it and delete it"
                for n in names
            ]
            continue
        shown = ", ".join(names[:GROUP_AT]) + (", ..." if len(names) > GROUP_AT else "")
        out.append(
            f"{prefix} holds {len(names)} file(s) with no owner + expires ({shown}) → add a "
            "README.md there with that frontmatter, or harvest the files into the repo that owns "
            "them and delete them"
        )
    for where, why in sorted(stale.items()):
        out.append(
            f"{where}: {why} → harvest into the repo that owns it and delete, "
            "or re-review and move the date"
        )
    return out


def check(
    root: Path,
    parts: tuple[str, ...],
    extra_t: list[str],
    extra_k: list[str],
    today: dt.date | None,
) -> list[str]:
    if not root.is_dir():
        return [f"not a folder: {root}"]
    cfg = load_config(root)
    cfg.transient += extra_t
    cfg.keep += extra_k
    out = list(cfg.errors)
    if "roadmap" in parts:
        out += check_roadmap(root, cfg)
    if "impl" in parts:
        out += check_impl(root, cfg)
    if "agents" in parts:
        out += check_agents(root, cfg)
    if "transient" in parts:
        out += check_transient(root, cfg, today)
    if "rules" in parts:
        out += check_rules(root, cfg, today)
    if "flaky" in parts:
        out += check_flaky(root, cfg, today)
    return out


# --- rules and flaky tests ------------------------------------------------------------------

ENTRY = re.compile(r"^### (?:\d+\.\s+)?([a-z0-9][a-z0-9-]*):\s")
DATED_FIELD = re.compile(r"^\s*[-*]\s+\*\*(Reviewed|Since|Incidents):\*\*(.*)$")
RETIRED = re.compile(r"^\s*[-*]\s+\*\*Retired:\*\*")
ISO = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
FILE_REVIEWED = re.compile(r"(?:^reviewed:\s*|<!--\s*reviewed:\s*)(20\d\d-\d\d-\d\d)", re.M)


def matching_files(root: Path, globs: list[str]) -> list[str]:
    """Repo-relative files under ROOT that match any of GLOBS, each once, in order."""
    out: list[str] = []
    for glob in globs:
        pattern = glob_regex(glob)
        fixed = re.split(r"[*?]", glob, maxsplit=1)[0]
        base = fixed.rsplit("/", 1)[0] if "/" in fixed else ""
        start = root / base if base and (root / base).is_dir() else root
        prefix = (base + "/") if start != root else ""
        for rel in walk_files(start):
            rel = prefix + rel
            if pattern.match(rel) and rel not in out:
                out.append(rel)
    return out


def rule_entries(text: str) -> list[tuple[int, str, dt.date | None, bool]]:
    """(line, slug, newest Reviewed / Since / Incidents date, retired) for each `### slug:`
    entry outside code fences."""
    entries: list[list | None] = []
    for i, line in Scan(text).unfenced():
        if line.startswith("#"):
            e = ENTRY.match(line)
            entries.append([i, e.group(1), None, False] if e else None)
            continue
        if not entries or entries[-1] is None:
            continue
        if RETIRED.match(line):
            entries[-1][3] = True
        f = DATED_FIELD.match(line)
        if f:
            for day in (parse_date(d) for d in ISO.findall(f.group(2))):
                if day and (entries[-1][2] is None or day > entries[-1][2]):
                    entries[-1][2] = day
    return [tuple(e) for e in entries if e is not None]


def check_rules(root: Path, cfg: Config, today: dt.date | None) -> list[str]:
    """Each rule or lesson is reviewed, not only added: an entry whose newest Reviewed, Since
    or Incidents date is over review_days old, or that has none, is a finding. A rules file
    with no `### slug:` entries needs a file-level `reviewed:` date instead."""
    out, days = [], cfg.budgets["review_days"]
    for rel in matching_files(root, cfg.rules):
        try:
            text = read_text(root / rel) or ""
        except Unreadable as exc:
            out.append(f"{rel} {exc} → make it a regular file")
            continue
        entries = rule_entries(text)
        if not entries:
            m = FILE_REVIEWED.search("\n".join(text.splitlines()[:30]))
            day = parse_date(m.group(1)) if m else None
            if day is None:
                out.append(
                    f"{rel} has no reviewed date → add "
                    f"`<!-- reviewed: {today or 'YYYY-MM-DD'} -->` once its "
                    "rules have been reviewed (cut each one a check now enforces)"
                )
            elif today is not None and (today - day).days > days:
                out.append(
                    f"{rel} last reviewed {day}, over {days} days ago → prune it: cut each rule "
                    f"a check enforces or the code shows, then set reviewed: {today}"
                )
            continue
        for line, slug, day, retired in entries:
            if retired:
                continue
            if day is None:
                out.append(
                    f"{rel}:{line} '{slug}' has no Since, Reviewed or Incidents date → add "
                    f"`- **Reviewed:** {today or 'YYYY-MM-DD'}` if it still earns its place, "
                    "or retire it"
                )
            elif today is not None and (today - day).days > days:
                out.append(
                    f"{rel}:{line} '{slug}' last dated {day}, over {days} days ago → still "
                    f"earning its place? add `- **Reviewed:** {today}`, or delete it (git keeps it)"
                )
    return out


# Retries and flaky markers: each hides a failure until it is quarantined with an end date.
FLAKY_ANY = (
    r"pytest\.mark\.flaky|@flaky\b|--reruns\b|\breruns\s*=|rerunfailures|"
    r"retryTimes\s*\(|\.retries\s*\(|"
    r"nick-fields/retry|wretry|\b(?:skip|xfail)\b[^\n]*\bflak(?:y|iness|es)\b"
)
FLAKY = re.compile(FLAKY_ANY)
# A JS, YAML or JSON test config's retry key set to anything but 0: `retries: 2`,
# `retries: process.env.CI ? 2 : 0` (npm init playwright), vitest `retry:`, JSON `"retries": 2`.
# Not read in workflows (actions/github-script's `retries` input retries API calls) or Python.
FLAKY_KEYED = re.compile(
    FLAKY_ANY + r"""|\bretr(?:y|ies)["']?[ \t]*:[ \t]*(?!(?:0|false|null|undefined)\b)[^\s,}#]"""
)
QUARANTINE = re.compile(r"quarantine[d]?:?\s*(?:until|expires?)?\s*(20\d\d-\d\d-\d\d)", re.I)
TEST_FILE = re.compile(
    r"(?:^|/)(?:test_[^/]*\.(?:py|sh|bash)|[^/]*_test\.(?:py|go|sh)|conftest\.py|"
    r"[^/]*\.(?:test|spec)\.[cm]?[jt]sx?|pyproject\.toml|pytest\.ini|tox\.ini|setup\.cfg|"
    r"(?:playwright|jest|vitest|cypress)\.config\.[cm]?[jt]s|package\.json|requirements[^/]*\.txt|"
    r"\.github/workflows/[^/]*\.ya?ml)$"
)


def candidate_tests(root: Path) -> list[str]:
    """Test files and test configs: git's tracked files when ROOT is a repo, else a walk that
    skips environments and build output. One pass, no process per file."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        check=False,
    )
    if out.returncode == 0:
        files = [p for p in os.fsdecode(out.stdout).split("\0") if p]
    else:
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            rel = os.path.relpath(dirpath, root)
            prefix = "" if rel == "." else rel.replace(os.sep, "/") + "/"
            files += [prefix + n for n in sorted(filenames)]
    return [f for f in files if TEST_FILE.search(f)]


def check_flaky(root: Path, cfg: Config, today: dt.date | None) -> list[str]:
    """A retry or flaky marker in a test or its config needs `quarantine: until YYYY-MM-DD`
    (with its issue) on its line or the two above, at most quarantine_days ahead; past that
    date the test is fixed or deleted, never retried until it passes."""
    out, limit = [], cfg.budgets["quarantine_days"]
    for rel in candidate_tests(root):
        try:
            text = read_text(root / rel)
        except Unreadable:
            continue
        keyed = not rel.endswith(".py") and not rel.startswith(".github/workflows/")
        flaky = FLAKY_KEYED if keyed else FLAKY
        if not text or not flaky.search(text):
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not flaky.search(line):
                continue
            q = next(filter(None, map(QUARANTINE.search, lines[max(0, i - 2) : i + 1])), None)
            day = parse_date(q.group(1)) if q else None
            where = f"{rel}:{i + 1}"
            if day is None:
                out.append(
                    f"{where} retries or marks a test flaky with no quarantine end → fix the "
                    f"test or delete it; to buy time, add `quarantine: until "
                    f"{today + dt.timedelta(days=limit) if today else 'YYYY-MM-DD'} #<issue>` "
                    "beside it"
                )
            elif today is None:
                continue
            elif day < today:
                out.append(
                    f"{where} quarantine ended {day} → fix the test or delete it (git keeps it); "
                    "a retry teaches the agent to rerun until green"
                )
            elif (day - today).days > limit:
                out.append(
                    f"{where} quarantine runs to {day}, past the {limit}-day limit → fix it "
                    "sooner, or delete it"
                )
    return out


# --- prune --------------------------------------------------------------------------------


def git_out(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, env=env, check=False
    )


def main_worktree(root: Path) -> Path:
    """The main worktree of the repo ROOT is in (a linked worktree resolves to it), else ROOT."""
    out = git_out(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    if common is not None and common.name == ".git":
        return common.parent.resolve()
    return root.resolve()


REGISTERED = "techne.toml marks it registered_report: its text is never edited → change nothing"


def roster_refusal(root: Path) -> str | None:
    """Why ~/.claude/techne.toml forbids a prune at ROOT, or None. It forbids one for a sister
    marked `registered_report = true` (REGISTERED), matched by its main worktree under
    workspace_root, its folder name or its origin's repo name, so a linked worktree or another
    clone is caught too; for a repo under workspace_root that is no sister; and when the roster
    cannot be read."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import techne_config
    finally:
        sys.path.pop(0)
    try:
        cfg = techne_config.load()
        roster = techne_config.sisters(cfg) if cfg is not None else []
    except techne_config.ConfigError as exc:
        return f"the sister roster cannot be read ({exc}) → fix ~/.claude/techne.toml"
    if cfg is None:
        return None  # no roster on this machine: nothing is marked
    main = main_worktree(root)
    url = git_out(root, "remote", "get-url", "origin").stdout.strip()
    path = re.sub(r"/\.git$", "", url.rstrip("/"), flags=re.I)  # a local path to a .git folder
    origin = re.sub(r"\.git$", "", re.split(r"[/:]", path)[-1], flags=re.I)
    ws = techne_config.workspace_root(cfg)
    # GitHub names ignore case, so every name compares lowercased. A name alone matches, owner
    # or not (a GitHub slug match is one of these), which only ever refuses more.
    names = {n.lower() for n in (main.name, origin) if n}
    hits = [
        s
        for s in roster
        if s["name"].lower() in names or techne_config.matches(cfg, s, {main}, None)
    ]
    if any(s.get("registered_report") is True for s in hits):
        return REGISTERED
    if not hits and ws is not None and main.is_relative_to(ws.resolve()):
        return f"{main.name} is under workspace_root but in no [[sisters]] entry → add it first"
    return None


def span_hazard(scan: Scan, a: int, b: int) -> str | None:
    """Why the 1-based span A..B is not safe to cut, or None. It looks from the nearest
    non-blank line above the span to the line after it: a fence that never closes runs to the
    end in CommonMark, a line the scanner cannot vouch for (Scan.hazards) may end or start a
    block it misreads, and an underline may make the line above it a heading."""
    lines = scan.lines
    if scan.open_fence is not None and a - 1 <= scan.open_fence < b:
        return f"line {scan.open_fence + 1} opens a code fence that never closes"
    if scan.doubt_from is not None and b > scan.doubt_from:
        return (
            f"line {scan.doubt_from + 1} opens a block CommonMark may end elsewhere (a fence "
            "indented or in a list item, or a fence or HTML inside a quote or HTML block), so "
            "what follows is unsure"
        )
    top = a - 1
    while top > 1 and not lines[top - 1].strip():
        top -= 1
    for n in range(max(top, 1), min(b + 1, len(lines)) + 1):
        line = lines[n - 1]
        if a <= n <= b and n - 1 not in scan.fenced and LINK_DEF.match(line):
            return (
                f"line {n} defines a link target ({line.strip()[:40]!r}) that links outside the "
                "cut may use; move it above the done-log first"
            )
        if n - 1 in scan.hazards:
            return f"line {n} ({line.strip()[:40]!r}) is a shape the scanner does not model"
        if n >= a and SETEXT.match(line) and n > 1 and lines[n - 2].strip():
            return f"line {n} underlines the line above it, which a reader may take for a heading"
    return None


def prune_refusal(root: Path, cfg: Config) -> str | None:
    if cfg.errors:
        return f"its ## cleanup section has an error ({cfg.errors[0]})"
    if cfg.prune_off:
        return f"## cleanup says prune: {cfg.prune_off} → harvest by hand, or change nothing"
    roster = roster_refusal(root)
    if roster:
        return roster
    path = root / "ROADMAP.md"
    if os.path.islink(path) or not path.is_file():
        return "ROADMAP.md is not a regular file"
    tracked = git_out(root, "ls-files", "--error-unmatch", "--", "ROADMAP.md")
    if tracked.returncode != 0:
        return (
            "ROADMAP.md is not tracked by git, so a deletion could not be recovered "
            "→ commit it first"
        )
    dirty = git_out(root, "status", "--porcelain", "--", "ROADMAP.md")
    if dirty.returncode != 0 or dirty.stdout.strip():
        return (
            "ROADMAP.md has uncommitted changes → commit or drop them first, "
            "so the prune is its own diff"
        )
    return None


def without(text: str, spans: list[tuple[int, int, str]]) -> str:
    """TEXT with SPANS removed. Only the edges of each cut change: blank lines there collapse to
    one, and a thematic break left dangling before a cut (doubled with the next one, or at the
    end) goes. Everything else, frontmatter and code fences included, stays byte for byte."""
    lines = text.splitlines(keepends=True)
    scan = Scan(text)
    front = -1  # the last line of a leading frontmatter block, which no edge rule touches
    if lines and lines[0].strip() == "---":
        front = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), -1)
    cuts: list[list[int]] = []
    for a, b in sorted((a - 1, b) for a, b, _ in spans):
        if cuts and a <= cuts[-1][1]:  # back to back: one cut, so no edge forms between them
            cuts[-1][1] = max(cuts[-1][1], b)
        else:
            cuts.append([a, b])
    segs, start = [], 0
    for a, b in cuts:
        segs.append(list(range(start, a)))
        start = b
    segs.append(list(range(start, len(lines))))

    def blank(i: int) -> bool:
        return not lines[i].strip()

    def rule(i: int) -> bool:
        return i > front and i not in scan.underlines and BREAK.match(lines[i]) is not None

    def plain_break(i: int) -> bool:
        """A break no reader takes for an underline: first, or under a blank, an ATX heading
        or another break."""
        return i == 0 or blank(i - 1) or i - 1 in scan.atx or BREAK.match(lines[i - 1]) is not None

    out = segs[0]
    before: dict[int, str] = {}  # a blank line written before a kept line, with its ending
    for right in segs[1:]:
        # A span ends at the next heading or the end, so only the left side can hold blanks.
        gap = out[-1] if out and blank(out[-1]) else None
        while out and blank(out[-1]):
            out.pop()
        if out and rule(out[-1]) and plain_break(out[-1]) and (not right or rule(right[0])):
            out.pop()
            while out and blank(out[-1]):
                out.pop()
        if right and out and gap is not None:
            out.append(gap)  # one blank line where there was any, with its own line ending
        elif right and out and right[0] not in scan.atx:
            # A setext heading's title right under a list item or paragraph would join it; the
            # cut heading kept them apart, so a blank line now does.
            before[right[0]] = "\r\n" if lines[out[-1]].endswith("\r\n") else "\n"
        out += right
    # Every kept line keeps its own ending, so a file with no final newline still has none.
    return "".join(before.get(i, "") + lines[i] for i in out)


def slug(title: str) -> str:
    """GitHub's anchor for a heading: lowercased, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", re.sub(r"[`*_~]", "", title).lower()).replace(" ", "-")


def dangling(scan: Scan, spans: list[tuple[int, int, str]], limit: int = 8):
    """(1-based line, title) for kept lines outside a fence that still point at a cut heading,
    by its exact title or its `#anchor`, at most LIMIT of them."""
    cut = {i for a, b, _ in spans for i in range(a - 1, b)}
    marks = []
    for _, _, t in spans:
        bare = re.sub(r"[`*_~]", "", t).strip()
        if bare:
            marks.append(
                (
                    re.compile(
                        rf"(?<![\w-])(?:{re.escape(bare)}\b|#{re.escape(slug(t))}(?![\w-]))"
                    ),
                    bare,
                )
            )
    found = 0
    for n, line in scan.unfenced():
        if n - 1 in cut:
            continue
        for rx, bare in marks:
            if rx.search(line):
                yield n, bare
                found += 1
                break
        if found >= limit:
            return


def prune(root: Path, apply: bool) -> int:
    root = root.resolve()
    if not os.path.lexists(root / "ROADMAP.md"):
        print(f"{root.name}: no ROADMAP.md, so nothing to prune ✓")
        return 0
    cfg = load_config(root)
    why = prune_refusal(root, cfg)
    if why:
        print(f"{root.name}: refused: {why}")
        return 1
    path = root / "ROADMAP.md"
    text = read_text(path)
    if text is None:  # gone since the refusal checks ran
        print(f"{root.name}: refused: ROADMAP.md is gone")
        return 1
    scan = Scan(text)
    spans = done_sections(text, scan)
    if not spans:
        print(f"{root.name}: ROADMAP.md keeps no done-log ✓")
        return 0
    if ODD_BREAKS.search(text):
        print(f"{root.name}: refused: ROADMAP.md holds a line break CommonMark does not split on")
        return 1
    for a, b, t in spans:
        hazard = span_hazard(scan, a, b)
        if hazard:
            print(f"{root.name}: refused: ROADMAP.md:{a}-{b} '{t}': {hazard} → delete it by hand")
            return 1
    for a, b, t in spans:
        print(f"{root.name}: {'deleting' if apply else 'would delete'} ROADMAP.md:{a}-{b} '{t}'")
    for n, title in dangling(scan, spans):
        print(
            f"{root.name}: note: ROADMAP.md:{n} names '{title}', which the prune removes "
            "→ reword it"
        )
    if not apply:
        print(f"{root.name}: dry run; harvest first (cleanup.py done-log), then --apply")
        return 0
    if read_text(path) != text:  # moved while we worked
        print(f"{root.name}: refused: ROADMAP.md changed during the prune; nothing written")
        return 1
    fd, tmp = tempfile.mkstemp(dir=root, prefix=".ROADMAP.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.write(without(text, spans))
        os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print(f"{root.name}: done; `git diff ROADMAP.md` shows it, and git history keeps the text")
    return 0


def done_log(root: Path) -> int:
    root = root.resolve()
    try:
        text = read_text(root / "ROADMAP.md")
    except Unreadable as exc:
        print(f"{root.name}: ROADMAP.md {exc}")
        return 1
    spans = done_sections(text) if text is not None else []
    if not spans:
        print(f"{root.name}: ROADMAP.md keeps no done-log ✓")
    lines = text.splitlines() if text is not None else []
    for a, b, t in spans:
        print(f"===== ROADMAP.md:{a}-{b} '{t}' =====")
        print("\n".join(lines[a - 1 : b]))
    return 0


def main(argv: list[str]) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(prog="cleanup.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--ci", action="store_true")
    c.add_argument("--only", action="append", choices=PARTS)
    c.add_argument("--transient", action="append", default=[])
    c.add_argument("--keep", action="append", default=[])
    c.add_argument(
        "--no-dates",
        action="store_true",
        help="only what no calendar date decides: for a pull-request gate that must not turn red "
        "on a date; expiry, review age and quarantine ends run on a schedule",
    )
    c.add_argument("--today", help=argparse.SUPPRESS)
    c.add_argument("roots", nargs="+", type=Path)
    d = sub.add_parser("done-log")
    d.add_argument("root", type=Path)
    p = sub.add_parser("prune")
    p.add_argument("--apply", action="store_true")
    p.add_argument("root", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "done-log":
        return done_log(a.root)
    if a.cmd == "prune":
        return prune(a.root, a.apply)
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    if a.no_dates:
        today = None
    parts = tuple(a.only) if a.only else PARTS
    found = False
    for root in a.roots:
        name = root.resolve().name
        findings = check(root, parts, a.transient, a.keep, today)
        found |= bool(findings)
        for line in findings or ["cleanup ✓"]:
            print(f"{name}: {line}")
    return 1 if a.ci and found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
