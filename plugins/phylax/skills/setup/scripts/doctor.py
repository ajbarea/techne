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
    "restart_on_update",
)
GUARDS = OPTIONS[:3]
MOD_MINIMUM = (2, 1, 287)
HOOK_FALLBACK = "the command hook runs the guards on any version"
RESTART_OFF = "restart_on_update is off"


def parse_options(argv: Sequence[str]) -> dict[str, bool | None]:
    """KEY=VALUE pairs. Anything but true or false (an unset option arrives empty or as its
    literal placeholder) reads as unset, which is off."""
    values: dict[str, bool | None] = {key: None for key in OPTIONS}
    for arg in argv:
        key, sep, value = arg.partition("=")
        if sep and key in values:
            word = value.strip().lower()
            values[key] = True if word == "true" else False if word == "false" else None
    return values


def option_line(key: str, value: bool | None) -> d.Check:
    if value is True:
        return d.Check(d.OK, key, "on")
    state = "off" if value is False else "not set, so off"
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
    if version < MOD_MINIMUM:
        detail = (
            f"Claude Code {d.fmt_version(version)} predates mods ({d.fmt_version(MOD_MINIMUM)});"
            " the command hook runs the guards instead"
        )
        return d.Check(d.OPTIONAL, "mod", detail, d.fix_lines(platform, d.FIXES["claude-update"]))
    return d.Check(d.OK, "mod", f"Claude Code {d.fmt_version(version)} loads the guard mod")


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
    tmux = d.which("tmux")
    if tmux and not (platform.wsl and d.windows_side(tmux)):
        return d.Check(d.OK, "launcher", f"tmux at {tmux}")
    if platform.wsl:
        wt = d.which("wt.exe")
        if wt:
            return d.Check(d.OK, "launcher", f"Windows Terminal at {wt}")
    return d.Check(
        d.MISSING,
        "launcher",
        "neither tmux nor Windows Terminal (wt.exe) is on PATH",
        d.fix_lines(platform, d.FIXES["tmux"]),
    )


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


def checks(platform: d.Platform, options: dict[str, bool | None]) -> list[d.Check]:
    guards_on = any(options[key] for key in GUARDS)
    restart_on = bool(options["restart_on_update"])
    found = [option_line(key, options[key]) for key in OPTIONS]
    found.append(d.guarded("mod", False, lambda: mod(platform, guards_on)))
    if guards_on or restart_on:
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
    return found


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_options(sys.argv[1:] if argv is None else argv)
    return d.report(checks(d.detect_platform(), options))


if __name__ == "__main__":
    sys.exit(main())
