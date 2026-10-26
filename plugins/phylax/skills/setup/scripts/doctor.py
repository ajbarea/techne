#!/usr/bin/env python3
"""Show which phylax options are on and check what each one needs, with the fix for each gap.

Runs on the system python3 (3.9 or newer, standard library only) and installs nothing.
Usage: python3 doctor.py KEY=VALUE ...  (the setup skill passes each option's value)
"""

from __future__ import annotations

import os
import shlex
import stat
import sys
import time
from collections.abc import Sequence
from pathlib import Path

sys.dont_write_bytecode = True  # a doctor leaves no file behind, not even in the plugin cache
PLUGIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN / "_shared"))
import doctor_lib as d  # noqa: E402  # ty: ignore[unresolved-import]

HOOKS = PLUGIN / "hooks"
OPTIONS = (
    "block_attribution_trailers",
    "block_commits_md",
    "warn_main_checkout_commit",
    "require_subagent_model",
    "restart_on_update",
    "budget_mode",
)
# Budget mode's numbers and paths, passed through as text; plugin_data is ${CLAUDE_PLUGIN_DATA}.
VALUES = (
    "budget_lean_pace",
    "budget_lean_used",
    "budget_frugal_pace",
    "budget_frugal_used",
    "budget_state_file",
    "plugin_data",
)
# The git guards: they need git and may run from the mod.
GUARDS = ("block_attribution_trailers", "block_commits_md", "warn_main_checkout_commit")
MOD_ADDED = (2, 1, 287)
# 2.1.288 fixed a mod's tool.call hook breaking Bash in subagents that run in a worktree.
MOD_MINIMUM = (2, 1, 288)
HOOK_FALLBACK = "the command hook runs the guards on any version"
RESTART_OFF = "restart_on_update is off"


def parse_options(argv: Sequence[str]) -> dict[str, bool | str | None]:
    """KEY=VALUE pairs, read as the hooks read them: on only for exactly `true`. An unset
    option arrives empty or as its literal placeholder (None); any other value is kept as
    text, so the report can name it, and is off."""
    values: dict[str, bool | str | None] = {key: None for key in OPTIONS}
    for arg in argv:
        key, sep, value = arg.partition("=")
        if sep and key in values:
            unset = value == "" or value.startswith("${user_config.")
            values[key] = {"true": True, "false": False}.get(value, None if unset else value)
    return values


def parse_values(argv: Sequence[str]) -> dict[str, str]:
    """The VALUES keys' raw text; an unset one arrives empty or as its literal placeholder."""
    found = dict.fromkeys(VALUES, "")
    for arg in argv:
        key, sep, value = arg.partition("=")
        if sep and key in found and not value.startswith("${"):
            found[key] = value
    return found


def option_line(key: str, value: bool | str | None) -> d.Check:
    if value is True:
        return d.Check(d.OK, key, "on")
    if value is False:
        state = "off"
    elif value is None:
        state = "not set, so off"
    else:
        state = f"set to {value!r}, which the hooks do not read as true, so off"
    return d.Check(d.NA, key, f"{state}; switch it on in /config under the phylax plugin's options")


def mod(platform: d.Platform, guards_on: bool) -> d.Check:
    if not guards_on:
        return d.Check(d.NA, "mod", "no guard is on")
    claude = d.which("claude")
    if not claude:
        return d.Check(
            d.OPTIONAL, "mod", f"claude is not on PATH, so its version is unknown; {HOOK_FALLBACK}"
        )
    code, out = d.run([claude, "--version"])
    version = d.parse_version(out) if code == 0 else None
    if version is None:
        said = d.first_line(out) or "no output"
        return d.Check(
            d.OPTIONAL,
            "mod",
            f"could not read the Claude Code version ({said}); {HOOK_FALLBACK}",
        )
    if version < MOD_ADDED:
        detail = (
            f"Claude Code {d.fmt_version(version)} predates mods ({d.fmt_version(MOD_ADDED)});"
            " the command hook runs the guards instead"
        )
        return d.Check(d.OPTIONAL, "mod", detail, d.fix_lines(platform, d.FIXES["claude-update"]))
    if version < MOD_MINIMUM:
        detail = (
            f"Claude Code {d.fmt_version(version)} loads the guard mod, but its Bash hook breaks"
            f" Bash in worktree subagents until {d.fmt_version(MOD_MINIMUM)}; update"
        )
        return d.Check(d.OPTIONAL, "mod", detail, d.fix_lines(platform, d.FIXES["claude-update"]))
    return d.Check(d.OK, "mod", f"Claude Code {d.fmt_version(version)} loads the guard mod")


def budget_module():
    sys.path.insert(0, str(HOOKS))
    import budget as module

    return module


def budget(values: dict[str, str]) -> d.Check:
    """The level budget mode reads now and the file it read, or what to do about the file."""
    module = budget_module()
    env = {f"CLAUDE_PLUGIN_OPTION_{k.upper()}": v for k, v in values.items() if k != "plugin_data"}
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        env["CLAUDE_CONFIG_DIR"] = os.environ["CLAUDE_CONFIG_DIR"]
    reading = module.level(env, time.time())
    found = module.settings(env)
    notes = [f"{key} not a number from 0 to 100, so its default" for key in found.bad]
    notes += list(found.conflicts)
    now = time.time()
    who = module.role(os.environ, now)
    routed = "routed by budget mode" if who.applies else f"normal routing ({who.reason})"
    notes.append(f"this session is {who.name}, {routed}")
    until = module.paused_until(os.environ, now)
    if until is not None and not who.reason.startswith("paused"):
        notes.append(f"opted-in sessions paused until {module.clock(until)}")
    extra = "".join(f"; {note}" for note in notes)
    if reading.note == "no snapshot yet":
        config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
        data = values.get("plugin_data") or os.path.join(config, "plugins", "data", "phylax-techne")
        copy = shlex.quote(os.path.join(data, "budget_snapshot.py"))
        target = f" {shlex.quote(reading.path)}" if values.get("budget_state_file") else ""
        fix = (
            "fix: put the snapshot in front of your status line in settings.json (cat keeps it"
            f' rendering if the copy is missing): "command": "{{ python3 {copy}{target} || cat; }}'
            ' | <your status line command>", or with no status line of your own'
            f' "python3 {copy}{target} > /dev/null" (the copy appears at the next session start)'
        )
        detail = f"no snapshot yet at {reading.path}, so normal{extra}"
        return d.Check(d.OPTIONAL, "budget", detail, (fix,))
    if reading.note.startswith(("unreadable", "no rate_limits")):
        fix = f"fix: check {reading.path} is the file the status line step writes"
        detail = f"{reading.note} at {reading.path}, so normal{extra}"
        return d.Check(d.OPTIONAL, "budget", detail, (fix,))
    if reading.note.startswith("snapshot "):
        fix = (
            "fix: check the status line step still runs; any response on this account refreshes it"
        )
        detail = f"{reading.note} at {reading.path}, so normal{extra}"
        return d.Check(d.OPTIONAL, "budget", detail, (fix,))
    # A live reading, or every window past its reset (normal until the next response).
    shown = module.why(reading) or reading.note
    return d.Check(d.OK, "budget", f"{reading.level}: {shown}; read {reading.path}{extra}")


def stale_restart():
    sys.path.insert(0, str(HOOKS))
    import stale_restart as module  # ty: ignore[unresolved-import]

    return module


def proc() -> d.Check:
    root = stale_restart().PROC
    if root.is_dir():
        return d.Check(d.OK, "proc", str(root))
    return d.Check(
        d.MISSING,
        "proc",
        f"no {root}; restart_on_update works on Linux and WSL only, so switch it off in /config",
    )


def launcher(platform: d.Platform) -> d.Check:
    """Judged by the hook's own launcher_for(), from this session's environment."""
    module = stale_restart()
    pane = os.environ.get("TMUX_PANE", "")
    found = module.launcher_for(pane.startswith("%"))
    if found == "tmux":
        return d.Check(d.OK, "launcher", f"this session runs in tmux at {d.which('tmux')}")
    if found == "wt":
        return d.Check(d.OK, "launcher", "this session runs in Windows Terminal")
    detail = (
        "restart_on_update only restarts a session running inside tmux or Windows Terminal"
        f" under WSL; start Claude Code inside tmux (see {d.CONFIG_DOCS}#restart-on-update)"
    )
    fixes = () if d.which("tmux") else d.fix_lines(platform, d.FIXES["tmux"])
    return d.Check(d.MISSING, "launcher", detail, (*fixes, "fix: tmux new-session claude"))


def state_dir() -> d.Check:
    """Judged by the hook's own state_ok(), without creating the directory."""
    module = stale_restart()
    path = module.STATE
    quoted = shlex.quote(str(path))
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return d.Check(d.OK, "state-dir", f"{path} is created on first use")
    except OSError as exc:
        return d.Check(d.MISSING, "state-dir", f"{path}: {exc.strerror}")
    if stat.S_ISLNK(st.st_mode):
        detail = f"{path} is a symlink, so the hook ignores it"
        return d.Check(d.MISSING, "state-dir", detail, (f"fix: rm {quoted}",))
    if not stat.S_ISDIR(st.st_mode):
        return d.Check(d.MISSING, "state-dir", f"{path} is not a directory", (f"fix: rm {quoted}",))
    if st.st_uid != os.getuid():
        return d.Check(
            d.MISSING,
            "state-dir",
            f"{path} belongs to another user, so the hook ignores it;"
            " set XDG_RUNTIME_DIR to a directory of your own",
        )
    if not module.state_ok(path):
        detail = f"{path} is open to other users"
        return d.Check(d.MISSING, "state-dir", detail, (f"fix: chmod 700 {quoted}",))
    return d.Check(d.OK, "state-dir", str(path))


def checks(
    platform: d.Platform,
    options: dict[str, bool | str | None],
    values: dict[str, str] | None = None,
) -> list[d.Check]:
    guards_on = any(options[key] is True for key in GUARDS)
    model_on = options["require_subagent_model"] is True
    restart_on = options["restart_on_update"] is True
    budget_on = options["budget_mode"] is True
    found = [option_line(key, options[key]) for key in OPTIONS]
    found.append(d.guarded("mod", False, lambda: mod(platform, guards_on)))
    if guards_on or model_on or restart_on or budget_on:
        found.append(
            d.program(
                platform,
                "python3",
                "python3",
                version_argv=d.PYTHON_VERSION_ARGV,
                minimum=(3, 9),
                why="the hooks run on the system python3",
            )
        )
    else:
        found.append(d.Check(d.NA, "python3", "every option is off, so no hook starts python3"))
    if guards_on:
        found.append(d.program(platform, "git", "git"))
    else:
        found.append(d.Check(d.NA, "git", "no guard is on"))
    if restart_on:
        found += [
            d.guarded("proc", True, proc),
            d.guarded("launcher", True, lambda: launcher(platform)),
            d.program(
                platform, "claude", "claude", why="restart_on_update starts the claude on PATH"
            ),
            d.guarded("state-dir", True, state_dir),
        ]
    else:
        found += [
            d.Check(d.NA, name, RESTART_OFF) for name in ("proc", "launcher", "claude", "state-dir")
        ]
    if budget_on:
        found.append(d.guarded("budget", False, lambda: budget(values or parse_values(()))))
    else:
        found.append(d.Check(d.NA, "budget", "budget_mode is off"))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    return d.report(checks(d.detect_platform(), parse_options(args), parse_values(args)))


if __name__ == "__main__":
    sys.exit(main())
