#!/usr/bin/env python3
"""phylax budget mode: route work to cheaper models while the usage allowance burns too fast.

Claude Code hands rate_limits only to the statusLine command; budget_snapshot.py, chained in
front of it, saves them to a file per account. Each window (5 hours, 7 days) gets a level from
its pace, used% minus the share of the window already gone: lean at budget_lean_pace points
ahead or budget_lean_used% used, frugal at budget_frugal_pace or budget_frugal_used. The
higher window decides. A missing, unreadable or day-old snapshot, and a window past its reset,
read normal.

Only a background session (PHYLAX_BUDGET_ROLE=background) or an interactive one that opts
in (PHYLAX_BUDGET=on) is routed; every other session reads normal (see role()).

Modes, run by hooks.json while budget_mode is on:
  session  SessionStart: keep the snapshot copy at ${CLAUDE_PLUGIN_DATA} current, and add the
           routing table unless the level is normal; a resumed or compacted session that
           last saw lean or frugal is told it is back to normal.
  prompt   UserPromptSubmit: when the level changed since this session last saw it, add the
           routing table, or a line saying it is back to normal.
  agent    PreToolUse on Agent: in frugal, run a call that names Opus, Fable or `best` on
           Sonnet instead, unless its description says "final review". The permission
           flow is left alone.
A cost guard must not block work, so an unreadable payload or snapshot is allowed through.
Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
import sys
import time
from typing import NamedTuple

HOOKS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOKS)
import budget_snapshot as snapshot  # noqa: E402

SNAPSHOT = os.path.join(HOOKS, "budget_snapshot.py")
WINDOWS = {"five_hour": 5 * 3600, "seven_day": 7 * 86400}
LEVELS = ("normal", "lean", "frugal")
DEFAULTS = {
    "budget_lean_pace": 10.0,
    "budget_lean_used": 80.0,
    "budget_frugal_pace": 25.0,
    "budget_frugal_used": 95.0,
}
# A snapshot older than this says nothing about now.
MAX_AGE = 86400
READ_LIMIT = 65536
# A session's remembered level is dropped after this long; a prune looks at this many at most.
SEEN_MAX_AGE = 7 * 86400
SEEN_MAX = 1000
FINAL_REVIEW = re.compile(r"final\s+review", re.IGNORECASE)
# The models above Sonnet: Opus, Fable, and `best`, which resolves to Fable where it is
# available and to Opus otherwise (code.claude.com/docs/en/model-config).
TOP_TIER = re.compile(r"\s*(opus|fable|best\b|claude-(opus|fable)-)", re.IGNORECASE)
OVERRIDE_NAME = "phylax-budget-override.json"
DEFAULT_PAUSE_HOURS = 4.0
MAX_PAUSE_HOURS = 7 * 24.0
SID = re.compile(r"[A-Za-z0-9_-]{1,128}")

ROUTING = (
    "Sonnet implements, runs research and the first review rounds; Opus reviews only the "
    "final round of a risky diff; Haiku does mechanical edits and digests. Set `model` on "
    "every Agent call to match."
)
FRUGAL_EXTRA = (
    " Also: no parallel Opus subagents, review rounds capped at 2, and Haiku for every "
    "digest. An Agent call that names Opus or Fable runs on Sonnet unless its description "
    "contains "
    '"final review".'
)


class Settings(NamedTuple):
    lean_pace: float
    lean_used: float
    frugal_pace: float
    frugal_used: float
    path: str
    bad: tuple
    conflicts: tuple


class Window(NamedTuple):
    name: str
    used: float
    elapsed: float
    level: str


class Reading(NamedTuple):
    level: str
    windows: tuple
    path: str
    note: str


def option(environ, key: str) -> str:
    value = environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", "")
    return "" if value.startswith("${") else value.strip()


def settings(environ) -> Settings:
    """Thresholds and the snapshot path from the plugin options; a bad number falls back to
    its default and is named in `bad`."""
    values, bad = {}, []
    for key, default in DEFAULTS.items():
        raw = option(environ, key)
        try:
            number = float(raw)
        except ValueError:
            number = math.nan
        if raw and math.isfinite(number) and 0 <= number <= 100:
            values[key] = number
        else:
            values[key] = default
            if raw:
                bad.append(key)
    path = option(environ, "budget_state_file") or snapshot.default_path(environ)
    conflicts = tuple(
        f"budget_lean_{kind} above budget_frugal_{kind}, so lean never fires on {kind}"
        for kind in ("pace", "used")
        if values[f"budget_lean_{kind}"] > values[f"budget_frugal_{kind}"]
    )
    return Settings(
        values["budget_lean_pace"],
        values["budget_lean_used"],
        values["budget_frugal_pace"],
        values["budget_frugal_used"],
        os.path.expanduser(path),
        tuple(bad),
        conflicts,
    )


def window_state(name: str, data, now: float) -> tuple | None:
    """(used %, elapsed % of the window) for a live window; None for an unknown, malformed
    or already reset one."""
    length = WINDOWS.get(name)
    if length is None or not isinstance(data, dict):
        return None
    used, resets = (
        snapshot.number(data.get("used_percentage")),
        snapshot.number(data.get("resets_at")),
    )
    if used is None or resets is None or resets <= now:
        return None
    elapsed = (now - (resets - length)) / length * 100
    return used, min(max(elapsed, 0.0), 100.0)


def classify(used: float, elapsed: float, s: Settings) -> str:
    pace = used - elapsed
    if pace >= s.frugal_pace or used >= s.frugal_used:
        return "frugal"
    if pace >= s.lean_pace or used >= s.lean_used:
        return "lean"
    return "normal"


def read_json(path: str):
    """A regular file's JSON; a FIFO or device would block, so it raises instead."""
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"{path} is not a regular file")
    with open(path, "rb") as f:
        return info, json.loads(f.read(READ_LIMIT))


def read_limits(path: str, now: float) -> tuple:
    """(rate_limits, note): the snapshot's rate_limits, or None and why not."""
    try:
        if now - os.stat(path).st_mtime > MAX_AGE:
            return None, f"snapshot {(now - os.stat(path).st_mtime) / 3600:.0f} h old"
        _, data = read_json(path)
    except FileNotFoundError:
        return None, "no snapshot yet"
    except (OSError, ValueError, RecursionError, OverflowError) as err:
        return None, f"unreadable snapshot ({type(err).__name__})"
    limits = data.get("rate_limits") if isinstance(data, dict) else None
    if not isinstance(limits, dict) or not limits:
        return None, "no rate_limits in the snapshot"
    return limits, ""


def level(environ, now: float) -> Reading:
    s = settings(environ)
    limits, note = read_limits(s.path, now)
    windows = []
    for name in WINDOWS:
        found = window_state(name, (limits or {}).get(name), now)
        if found:
            windows.append(Window(name, found[0], found[1], classify(found[0], found[1], s)))
    worst = max((LEVELS.index(w.level) for w in windows), default=0)
    if limits is not None and not windows:
        note = "no live window in the snapshot"
    return Reading(LEVELS[worst], tuple(windows), s.path, note)


def override_path(environ) -> str:
    return os.path.join(os.path.dirname(snapshot.default_path(environ)), OVERRIDE_NAME)


def paused_until(environ, now: float) -> float | None:
    """When a /phylax:budget off pause ends, or None when none is running."""
    try:
        _, data = read_json(override_path(environ))
    except (OSError, ValueError, RecursionError, OverflowError):
        return None
    until = snapshot.number(data.get("until")) if isinstance(data, dict) else None
    # Further off than /phylax:budget off can set is no pause of ours.
    if until is None or not now < until <= now + MAX_PAUSE_HOURS * 3600:
        return None
    return until


def clock(when: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(when))


class Role(NamedTuple):
    applies: bool
    name: str
    reason: str


def role(environ, now: float) -> Role:
    """Whether budget mode routes this session. Background agents (PHYLAX_BUDGET_ROLE=
    background) pay first; an interactive session keeps normal routing unless it opts in with
    PHYLAX_BUDGET=on, and a /phylax:budget off pause sends opted-in sessions back to normal.
    PHYLAX_BUDGET=normal exempts any session."""
    asked = environ.get("PHYLAX_BUDGET", "").strip().lower()
    background = environ.get("PHYLAX_BUDGET_ROLE", "").strip().lower() == "background"
    name = "background" if background else "interactive" + (", opted in" if asked == "on" else "")
    if asked == "normal":
        return Role(False, name, "PHYLAX_BUDGET=normal")
    if background:
        return Role(True, name, "")
    if asked != "on":
        return Role(False, name, "interactive sessions keep normal routing")
    until = paused_until(environ, now)
    if until is not None:
        return Role(False, name, f"paused until {clock(until)}")
    return Role(True, name, "")


def session_level(environ, now: float) -> Reading:
    """The level this session routes by: the account's level, or normal when its role is exempt
    (then the snapshot is not read at all)."""
    who = role(environ, now)
    if not who.applies:
        return Reading("normal", (), "", who.reason)
    return level(environ, now)


def why(reading: Reading) -> str:
    label = {"five_hour": "5-hour", "seven_day": "7-day"}
    return "; ".join(
        f"{label[w.name]} window {w.used:.0f}% used with {w.elapsed:.0f}% of it gone"
        for w in reading.windows
    )


def context(reading: Reading, previous: str = "normal") -> str | None:
    if reading.level == "normal":
        if previous == "normal":
            return None
        reason = why(reading) or reading.note or "no live reading"
        return f"phylax budget mode: back to normal ({reason}). Opus writes and reviews again."
    text = f"phylax budget mode: {reading.level} ({why(reading)}). Until it eases: {ROUTING}"
    return text + FRUGAL_EXTRA if reading.level == "frugal" else text


def data_dir(environ) -> str | None:
    folder = environ.get("CLAUDE_PLUGIN_DATA", "")
    return folder if folder and not folder.startswith("${") else None


def seen_path(environ, payload: dict) -> str | None:
    folder, sid = data_dir(environ), payload.get("session_id")
    if not folder or not isinstance(sid, str) or not SID.fullmatch(sid):
        return None
    return os.path.join(folder, "budget-seen", sid)


def read_seen(path: str | None) -> str:
    if path is None:
        return "normal"
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read(16).strip()
    except OSError:
        return "normal"
    return value if value in LEVELS else "normal"


def prune_seen(environ, now: float) -> None:
    """Drop remembered levels older than SEEN_MAX_AGE, looking at SEEN_MAX entries at most."""
    folder = data_dir(environ)
    if not folder:
        return
    seen = os.path.join(folder, "budget-seen")
    try:
        if not stat.S_ISDIR(os.lstat(seen).st_mode):
            return  # a symlink or a file: never delete through it
        with os.scandir(seen) as entries:
            for count, entry in enumerate(entries):
                if count >= SEEN_MAX:
                    break
                if not (SID.fullmatch(entry.name) and entry.is_file(follow_symlinks=False)):
                    continue
                if now - entry.stat(follow_symlinks=False).st_mtime > SEEN_MAX_AGE:
                    os.unlink(entry.path)
    except OSError:
        pass


def install_snapshot(environ) -> None:
    """Keep ${CLAUDE_PLUGIN_DATA}/budget_snapshot.py equal to the shipped one."""
    folder = data_dir(environ)
    if not folder:
        return
    target = os.path.join(folder, "budget_snapshot.py")
    with open(SNAPSHOT, "rb") as f:
        shipped = f.read()
    try:
        with open(target, "rb") as f:
            if f.read() == shipped:
                return
    except OSError:
        pass
    snapshot.write_atomic(target, shipped)
    shutil.copymode(SNAPSHOT, target)


def emit(event: str, **fields) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}}))


def on_session(payload: dict, environ, now: float) -> None:
    try:
        install_snapshot(environ)
    except OSError as err:
        print(f"phylax budget: could not copy budget_snapshot.py ({err})", file=sys.stderr)
    prune_seen(environ, now)
    path = seen_path(environ, payload)
    # A resumed or compacted session still carries what it was last told.
    resumed = payload.get("source") in ("resume", "compact")
    previous = read_seen(path) if resumed else "normal"
    reading = session_level(environ, now)
    remember(path, reading.level)
    text = context(reading, previous)
    if text:
        emit("SessionStart", additionalContext=text)


def on_prompt(payload: dict, environ, now: float) -> None:
    path = seen_path(environ, payload)
    if path is None:
        return  # nowhere to remember what this session saw: SessionStart told it once
    previous = read_seen(path)
    reading = session_level(environ, now)
    if reading.level == previous:
        return
    remember(path, reading.level)
    text = context(reading, previous)
    if text:
        emit("UserPromptSubmit", additionalContext=text)


def remember(path: str | None, value: str) -> None:
    if path:
        try:
            snapshot.write_atomic(path, value.encode())
        except OSError as err:
            print(f"phylax budget: could not record the level ({err})", file=sys.stderr)


def rewrite(payload: dict, environ, now: float | None = None) -> dict | None:
    """The PreToolUse output that runs this Agent call on Sonnet, or None to leave it."""
    now = time.time() if now is None else now
    if payload.get("tool_name") not in ("Agent", "Task"):
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    model, description = tool_input.get("model"), tool_input.get("description")
    if not isinstance(model, str) or not TOP_TIER.match(model):
        return None
    if isinstance(description, str) and FINAL_REVIEW.search(description):
        return None
    reading = session_level(environ, now)
    if reading.level != "frugal":
        return None
    return {
        "hookEventName": "PreToolUse",
        "updatedInput": {**tool_input, "model": "sonnet"},
        "additionalContext": (
            f"phylax budget mode is frugal ({why(reading)}), so this {model.strip()} call ran on"
            ' Sonnet. Put "final review" in the description to keep it for a final review round.'
        ),
    }


def pause(argv: list, environ, now: float) -> int:
    """/phylax:budget off [hours], on, status: a pause for opted-in interactive sessions."""
    path = override_path(environ)
    if argv[0] == "off":
        try:
            hours = float(argv[1]) if len(argv) > 1 else DEFAULT_PAUSE_HOURS
        except ValueError:
            hours = math.nan
        if not (math.isfinite(hours) and 0 < hours <= MAX_PAUSE_HOURS):
            print(
                f"phylax budget: hours must be more than 0 and at most 168, not {argv[1]!r}",
                file=sys.stderr,
            )
            return 2
    try:
        if argv[0] == "off":
            snapshot.write_atomic(path, json.dumps({"until": now + hours * 3600}).encode())
        elif argv[0] == "on":
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
    except OSError as err:
        print(f"phylax budget: could not change the pause at {path} ({err})", file=sys.stderr)
        return 1
    until = paused_until(environ, now)
    who = role(environ, now)
    state = f"paused until {clock(until)}" if until else "not paused"
    routed = "routed by budget mode" if who.applies else f"normal routing ({who.reason})"
    print(f"phylax budget: {state}; this session is {who.name}, {routed}")
    return 0


def main(argv: list) -> int:
    mode = argv[0] if argv else ""
    if mode in ("off", "on", "status"):
        return pause(argv, os.environ, time.time())
    if mode not in ("session", "prompt", "agent"):
        print(f"phylax budget: unknown mode {mode!r} (session, prompt or agent)", file=sys.stderr)
        return 2
    try:
        payload = json.load(sys.stdin)
    except ValueError as err:
        print(f"phylax budget: stdin is not JSON ({err}); going ahead", file=sys.stderr)
        return 0
    if not isinstance(payload, dict):
        print("phylax budget: payload is not an object; going ahead", file=sys.stderr)
        return 0
    now = time.time()
    if mode == "session":
        on_session(payload, os.environ, now)
    elif mode == "prompt":
        on_prompt(payload, os.environ, now)
    else:
        found = rewrite(payload, os.environ, now)
        if found:
            print(json.dumps({"hookSpecificOutput": found}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
