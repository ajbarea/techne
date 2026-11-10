"""schole-fetch --list: which modules hold new or changed files, from the content tree alone.

Read-only: one GET of each course's content/toc, which `schole-sweep` already makes. It opens no
topic and downloads nothing, so it cannot mark anything read. The state file holds each File
topic's LastModifiedDate as of the last `--record`.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from schole import config, d2l

STATE_NAME = "fetch-state.json"
MAX_DEPTH = 40
MAX_REPO_FILES = 50_000
MIN_TITLE = 4
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}
# ISTE.476782 joins two course numbers (ISTE-476 and ISTE-782); mycourses-sync reads it the same way
CODE = re.compile(r"^([A-Za-z]{3,4})\.(\d{3}(?:/?\d{3})*)(?!\d)")
# the compact code RIT stores: CISC82001.2261 is CISC 820, section 01
COMPACT = re.compile(r"^([A-Za-z]{3,4})(\d{3})\d{2}(?!\d)")


class StateError(RuntimeError):
    """The state file exists but cannot be read as state."""


def state_path() -> Path:
    """SCHOLE_STATE_HOME (absolute), else $XDG_STATE_HOME or ~/.local/state, then schole/."""
    env = os.environ.get("SCHOLE_STATE_HOME")
    if env:
        path = Path(env).expanduser()
        if not path.is_absolute():
            raise config.ConfigError(f"SCHOLE_STATE_HOME must be absolute, not {env!r}.")
    else:
        root = os.environ.get("XDG_STATE_HOME")
        path = (
            Path(root) if root and os.path.isabs(root) else Path.home() / ".local" / "state"
        ) / "schole"
    return path / STATE_NAME


def load_state(path: Path) -> dict[str, dict[str, str]]:
    """{course id: {topic id: LastModifiedDate}}; a missing file is an empty state."""
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise StateError(f"cannot read {path}: {exc}") from None
    try:
        data = json.loads(raw)
        courses = data["courses"]
        ok = data.get("version") == 1 and isinstance(courses, dict)
        ok = ok and all(
            isinstance(v, dict)
            and all(isinstance(k, str) and isinstance(d, str) for k, d in v.items())
            for v in courses.values()
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        raise StateError(f"{path} is not schole-fetch state; move it aside to start again.")
    return courses


def save_state(path: Path, courses: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(
        mode=0o700, parents=True, exist_ok=True
    )  # a folder the user named keeps its mode
    config.write_private(path, json.dumps({"version": 1, "courses": courses}, sort_keys=True))


@dataclass
class Module:
    path: str
    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)


def file_topics(modules: list, depth: int = 0) -> Iterator[tuple[str, dict]]:
    """(module path, topic) for each visible File topic with an integer id, depth first."""
    if depth > MAX_DEPTH:
        raise d2l.SiteError("the content tree nests deeper than any real course")
    for m in modules:
        if not isinstance(m, dict) or m.get("IsHidden"):
            continue
        title = d2l.clean(m.get("Title") or "(untitled)")
        for t in m.get("Topics") or []:
            if (
                isinstance(t, dict)
                and t.get("TypeIdentifier") == "File"
                and not t.get("IsHidden")
                and isinstance(t.get("TopicId"), int)
                and not isinstance(t.get("TopicId"), bool)
            ):
                yield title, t
        for sub_path, t in file_topics(m.get("Modules") or [], depth + 1):
            yield f"{title} / {sub_path}", t


def diff(modules: list, seen: dict[str, str]) -> tuple[list[Module], dict[str, str]]:
    """Modules with new or changed File topics against `seen`, and the topic dates now."""
    by_path: dict[str, Module] = {}
    now: dict[str, str] = {}
    for path, t in file_topics(modules):
        tid, stamp = str(t["TopicId"]), t.get("LastModifiedDate")
        title = d2l.clean(t.get("Title") or "(untitled)")
        # an unparseable or missing date is recorded as "" so the topic is seen, never new again
        now[tid] = stamp if isinstance(stamp, str) and d2l.parse_time(stamp) else ""
        mod = by_path.setdefault(path, Module(path))
        if tid not in seen:
            mod.new.append(title)
            continue
        before, after = d2l.parse_time(seen[tid]), d2l.parse_time(stamp)
        if before and after and after > before:
            mod.changed.append(title)
    return [m for m in by_path.values() if m.new or m.changed], now


def course_repo(classes: Path, name: str, code: str) -> tuple[Path | None, str]:
    """The class repo for a course (CSCI.739.01 - Topics... -> csci739-*) and why there is none,
    chosen as mycourses-sync does: git repos only, then the one holding AGENTS.md."""
    m = CODE.match(name) or COMPACT.match(code)
    if not m:
        return None, "no course number"
    dept, digits = m.group(1).lower(), m.group(2).replace("/", "")
    prefixes = [f"{dept}{digits[i : i + 3]}" for i in range(0, len(digits), 3)]
    found = sorted(
        {p for pre in prefixes for p in classes.glob(pre + "-*") if (p / ".git").exists()}
    )
    course = [p for p in found if (p / "AGENTS.md").is_file()]
    if len(course) == 1:
        return course[0], ""
    if not found:
        return None, "no repo"
    return None, "ambiguous: " + ", ".join(d2l.clean(p.name) for p in (course or found))


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def repo_index(repos: list[Path]) -> str:
    """Normalized file-name stems under the repos, newline-joined for one substring scan;
    bounded, skipping VCS and build folders."""
    stems: set[str] = set()
    count = 0
    for repo in repos:
        for _, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                count += 1
                if count > MAX_REPO_FILES:
                    return "\n".join(sorted(stems))
                stems.add(norm(Path(name).stem))
    return "\n".join(sorted(stems))


def in_repo(title: str, index: str) -> bool:
    """Advisory: the normalized topic title sits inside some file stem. The hash inventory in
    mycourses-sync is the exact check."""
    t = norm(title)
    return len(t) >= MIN_TITLE and t in index


def list_lines(
    get: d2l.Get,
    term: str,
    seen: dict[str, dict[str, str]],
    classes: Path | None,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    """COURSE, MODULE and APIFAIL lines, and the state to record: `seen` with each course whose
    toc loaded replaced by its current File topic dates."""
    get = d2l.guarded(get)
    lines: list[str] = []
    state = {k: dict(v) for k, v in seen.items()}
    for c in d2l.courses(get, term):
        name = d2l.clean(c.name)
        status, body = get(f"{d2l.LE}/{c.ou}/content/toc")
        toc = d2l._json(status, body)
        if not isinstance(toc, dict) or not isinstance(toc.get("Modules"), list):
            lines.append(f"APIFAIL {name} :: toc:{status}")
            continue
        try:
            mods, now = diff(toc["Modules"], seen.get(str(c.ou), {}))
        except d2l.SiteError as exc:
            lines.append(f"APIFAIL {name} :: {exc}")
            continue
        # merged, so a topic hidden for a while is not new again when it returns
        state[str(c.ou)] = {**seen.get(str(c.ou), {}), **now}
        repo, why = course_repo(classes, c.name, c.code) if classes else (None, "")
        index = repo_index([repo]) if repo else ""
        where = d2l.clean(repo.name) if repo else "none" + (f" ({why})" if why else "")
        lines.append(f"COURSE {name} :: repo {where} :: {len(mods)} modules with changes")
        for m in mods:
            held = sum(in_repo(t, index) for t in m.new)
            tail = f" :: new in repo by title {held}/{len(m.new)}" if repo else ""
            counts = f"{len(m.new)} new, {len(m.changed)} changed"
            lines.append(f"MODULE {name} :: {d2l.clean(m.path)} :: {counts}{tail}")
    return lines, state
