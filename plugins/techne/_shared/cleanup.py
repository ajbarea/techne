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
  transient  a file matched by a transient glob has no `owner` plus `expires` or
             `reviewed` frontmatter (its own, for a markdown file, else the nearest
             README.md above it), or is past it
--ci exits 1 when any finding is printed; without it check always exits 0, as the other
sisters checks do. --only limits the parts run. --transient and --keep add to the repo's
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
# (https://rufuspollock.com/2026-02-25-changelogs-lightweight-best-practice).

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
}
AGENT_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "CLAUDE.local.md",
    ".github/copilot-instructions.md",
    ".claude/skill-context.md",
)
PARTS = ("roadmap", "impl", "agents", "transient")
MAX_READ = 4 << 20  # Claude Code skips an instruction file over 4 MiB; nothing here is larger
FRONT_MAX = 8192  # frontmatter sits in a file's first lines
SKIP_DIRS = {".git"}
GROUP_AT = 3  # past this many unowned files in one folder, one line names the folder

# A heading that opens a log of finished work. "Done when" and its kin are criteria, not logs.
DONE_HEADING = re.compile(
    r"^(?:(?:recently|already|previously|what(?:'s| has| was)?)\s+)?"
    r"(?:completed|complete|shipped|done|finished|landed|released|archived?|history|"
    r"change\s*log|release\s+notes)\b(?!\s+(?:when|means|criteria|if|by)\b)"
)
HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")


class Unreadable(Exception):
    pass


def read_text(path: Path, limit: int = MAX_READ) -> str | None:
    """PATH's text, or None when there is none. Only a regular file is read, opened without
    blocking and checked through its descriptor, so a FIFO cannot hang the check."""
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
        raw = f.read(limit + 1)
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
    section = re.search(r"^## cleanup[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not section:
        return cfg
    for raw in section.group(1).splitlines():
        m = re.match(r"^\s*[-*]\s+([a-z_]+)\s*:\s*(.*?)\s*$", raw)
        if not m:
            continue
        key, value = m.groups()
        if key in DEFAULTS:
            if not re.fullmatch(r"[1-9][0-9]{0,5}", value):
                cfg.errors.append(
                    f"## cleanup: {key} {value!r} is not a whole number → write one, such as "
                    f"{DEFAULTS[key]}"
                )
                continue
            cfg.budgets[key] = int(value)
        elif key in ("transient", "keep", "agent_file"):
            if value.startswith("<"):  # the template's placeholder, not yet filled in
                continue
            if not value:
                cfg.errors.append(f"## cleanup: {key} has no glob → write one or delete the line")
                continue
            {"transient": cfg.transient, "keep": cfg.keep, "agent_file": cfg.agent_files}[
                key
            ].append(value)
        elif key == "prune":
            if value.split()[0:1] == ["off"]:
                cfg.prune_off = value
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
    """Every file under ROOT as a repo-relative POSIX path, skipping .git; one pass."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel = os.path.relpath(dirpath, root)
        prefix = "" if rel == "." else rel.replace(os.sep, "/") + "/"
        for name in sorted(filenames):
            yield prefix + name


# --- frontmatter --------------------------------------------------------------------------


def frontmatter(path: Path) -> dict[str, str] | None:
    """The `key: value` lines between a leading `---` and the next `---`, or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(FRONT_MAX).decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = head.lstrip("﻿").splitlines()
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


def parse_date(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value[:10]) if re.match(r"\d{4}-\d\d-\d\d$", value) else None
    except ValueError:
        return None


def freshness(fields: dict[str, str], today: dt.date, review_days: int) -> str | None:
    """Why FIELDS do not keep a file current, or None when they do."""
    if not fields.get("owner"):
        return "no owner"
    expires, reviewed = fields.get("expires"), fields.get("reviewed")
    if not expires and not reviewed:
        return "no expires or reviewed date"
    if expires:
        day = parse_date(expires)
        if day is None:
            return f"expires {expires!r} is not a YYYY-MM-DD date"
        if day < today:
            return f"expired {day.isoformat()} (owner {fields['owner']})"
    if reviewed:
        day = parse_date(reviewed)
        if day is None:
            return f"reviewed {reviewed!r} is not a YYYY-MM-DD date"
        if (today - day).days > review_days:
            owner = fields["owner"]
            return f"last reviewed {day.isoformat()}, over {review_days} days ago (owner {owner})"
    return None


# --- checks -------------------------------------------------------------------------------


def done_sections(text: str) -> list[tuple[int, int, str]]:
    """(first line, last line, heading) of each done-log section, 1-based and inclusive. A
    section runs to the next heading of its level or higher; headings inside code fences are
    not headings. A done-log nested in another is part of it."""
    lines = text.splitlines()
    heads: list[tuple[int, int, str]] = []  # (index, level, title)
    fence = None
    for i, line in enumerate(lines):
        m = FENCE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark[0] * len(mark)
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence is None:
            h = HEADING.match(line)
            if h:
                heads.append((i, len(h.group(1)), h.group(2)))
    found: list[tuple[int, int, str]] = []
    for n, (i, level, title) in enumerate(heads):
        if found and i <= found[-1][1] - 1:
            continue  # inside a done-log already found
        if not DONE_HEADING.match(normal_title(title)):
            continue
        end = len(lines)
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
    return t


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
    seen = list(AGENT_FILES)
    for glob in cfg.agent_files:
        pattern = glob_regex(glob)
        base = re.split(r"[*?]", glob, maxsplit=1)[0].rsplit("/", 1)[0] if "/" in glob else ""
        start = root / base if base and (root / base).is_dir() else root
        prefix = (base + "/") if start != root else ""
        for rel in walk_files(start):
            rel = prefix + rel
            if pattern.match(rel) and rel not in seen:
                seen.append(rel)
    return seen


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


def transient_status(root: Path, cfg: Config, today: dt.date) -> Transient:
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
            if own is not None:
                return rel, own
        parts = rel.split("/")[:-1]
        while parts:
            readme = "/".join(parts) + "/README.md"
            if readme != rel and os.path.isfile(root / readme):
                got = fm(readme)
                if got is not None:
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
    return found


def check_transient(root: Path, cfg: Config, today: dt.date) -> list[str]:
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
    root: Path, parts: tuple[str, ...], extra_t: list[str], extra_k: list[str], today: dt.date
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
    return out


# --- prune --------------------------------------------------------------------------------


def git_out(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, env=env, check=False
    )


def registered(root: Path) -> bool:
    """Whether ~/.claude/techne.toml marks the sister at ROOT `registered_report = true`. A
    roster that cannot be read counts as marked: a prune never guesses."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import techne_config
    finally:
        sys.path.pop(0)
    try:
        cfg = techne_config.load()
    except techne_config.ConfigError:
        return True
    if cfg is None:
        return False
    try:
        roster = techne_config.sisters(cfg)
    except techne_config.ConfigError:
        return True
    ws = techne_config.workspace_root(cfg)
    here = root.resolve()
    for s in roster:
        hit = s.get("name") == here.name if ws is None else (ws / s["name"]).resolve() == here
        if hit and s.get("registered_report") is True:
            return True
    return False


def prune_refusal(root: Path, cfg: Config) -> str | None:
    if cfg.prune_off:
        return f"## cleanup says prune: {cfg.prune_off} → harvest by hand, or change nothing"
    if registered(root):
        return "techne.toml marks it registered_report (or cannot be read) → change nothing"
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
    lines = text.splitlines(keepends=True)
    drop = set()
    for a, b, _ in spans:
        drop.update(range(a - 1, b))
    kept = [line for i, line in enumerate(lines) if i not in drop]
    # A thematic break that separated the deleted section from the one before it is left
    # dangling: at the end of the file, or doubled with the next section's own break.
    rule = re.compile(r"^ {0,3}([-*_])(?: *\1){2,} *$")
    out: list[str] = []
    for line in kept:
        if rule.match(line.rstrip("\r\n")):
            prev = next((x for x in reversed(out) if x.strip()), "")
            if rule.match(prev.rstrip("\r\n")):
                continue
        out.append(line)
    while out and (not out[-1].strip() or rule.match(out[-1].rstrip("\r\n"))):
        out.pop()
    text = re.sub(r"\n{3,}", "\n\n", "".join(out))
    return text.rstrip("\n") + "\n" if text.strip() else ""


def prune(root: Path, apply: bool) -> int:
    root = root.resolve()
    cfg = load_config(root)
    why = prune_refusal(root, cfg)
    if why:
        print(f"{root.name}: refused: {why}")
        return 1
    path = root / "ROADMAP.md"
    text = read_text(path) or ""
    spans = done_sections(text)
    if not spans:
        print(f"{root.name}: ROADMAP.md keeps no done-log ✓")
        return 0
    for a, b, t in spans:
        print(f"{root.name}: {'deleting' if apply else 'would delete'} ROADMAP.md:{a}-{b} '{t}'")
    if not apply:
        print(f"{root.name}: dry run; harvest first (cleanup.py done-log), then --apply")
        return 0
    if (read_text(path) or "") != text:  # moved while we worked
        print(f"{root.name}: refused: ROADMAP.md changed during the prune; nothing written")
        return 1
    fd, tmp = tempfile.mkstemp(dir=root, prefix=".ROADMAP.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
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
    lines = (text or "").splitlines()
    spans = done_sections(text or "")
    if not spans:
        print(f"{root.name}: ROADMAP.md keeps no done-log ✓")
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
