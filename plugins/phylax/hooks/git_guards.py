#!/usr/bin/env python3
"""Guards on the Bash tool for git commit, git add, git push and gh pr/issue/api writes, and
for the command shapes command_shapes.py refuses.

register.ts runs this from its tool.call hook on each main-thread Bash command
that names git or gh, passing the PreToolUse JSON on stdin and each userConfig
option as CLAUDE_PLUGIN_OPTION_<KEY>, and reads the decision from stdout. The
hooks.json PreToolUse hook runs it too, for subagents' commands and for every
command when the module did not load; mod_checks() stands it down for a command
the module already checked. A repo turns an enabled guard off for itself with
`git config phylax.<optionInCamelCase> false`.

This file only decides whether a command needs checking; git_checks.py and command_shapes.py
hold the checks. The shape checks run before the mod's stand-down (the mod runs only the git
guards), and only when hooks.json passes `--shapes`, which it does while a shape option is
on. The fallback runs on every Bash call, so a command that cannot name git or gh exits before
git_checks.py loads. Python recompiles the script it runs on every
start but caches the bytecode of a module it imports, so the checks live in an
imported module.

A crash in one subcommand's check, or a git call that cannot run or times out,
still checks the rest and emits the denies already found; with none found, the
check fails closed while a blocking guard is on (exit 2, which both callers
treat as a refusal).

Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Whether the shape check passed this call: a crash after it is a git check's, which refuses
# only while a blocking git guard is on.
shapes_checked = False
# The hook input main read, for the crash handler's warning shape.
last_input = ""


def mod_checks(data: dict) -> bool:
    """Whether register.ts already checked this call: the hooks.json fallback then stands down.

    The mod names the one call its check passed in PHYLAX_GUARD_CHECKED while that call runs,
    and clears it after. Any other call (a subagent's, which the mod leaves here because only
    this hook gets its cwd, or any call when the module did not load) is checked here.
    """
    checked = os.environ.get("PHYLAX_GUARD_CHECKED")
    return bool(checked) and checked == data.get("tool_use_id")


def cannot_name_git(payload: str) -> bool:
    """Whether the raw hook input cannot hold a command naming git or gh.

    JSON writes a letter as itself or as a \\u escape, so input with neither word and no
    \\u escape has no such command, whatever else it holds.
    """
    return "git" not in payload and "gh" not in payload and "\\u" not in payload


def may_hold_shape(payload: str) -> bool:
    """Whether the raw hook input can hold a shape command_shapes.py refuses: the same test as
    cannot_name_git, for the words each shape needs. It reads no option, so a call without
    the words costs a few substring scans and nothing else."""
    from git_options import SHAPE_WORDS

    # `\u` is a letter JSON wrote as an escape: check_shapes decodes it before it lexes.
    return "\\u" in payload or any(word in payload for word in SHAPE_WORDS)


def check_shapes(payload: str, shapes: set[str]) -> tuple[dict, int | None]:
    """Run command_shapes on the hook input: its parsed JSON, and the exit code when it decided
    (0 with a refusal printed, 2 when the check itself failed: it fails closed)."""
    import json

    import hook_output

    data: dict = {}
    try:
        data = json.loads(payload)  # not empty: it holds a shape word or a `\\u` escape
        import command_shapes

        # Antigravity backgrounds every run_command after at most 10 s.
        background = (
            hook_output.from_agy(data)
            or (data.get("tool_input") or {}).get("run_in_background") is True
        )
        denies = command_shapes.check(command_of(data), background, shapes)
    except Exception as exc:
        from git_options import off_switch

        print(
            f"phylax shape guard error: {type(exc).__name__}: {exc}; the command was not run.",
            off_switch(sorted(shapes)),
            file=sys.stderr,
        )
        return data, 2
    if denies:
        json.dump(hook_output.deny("\n".join(denies), hook_output.from_agy(data)), sys.stdout)
        return data, 0
    return data, None


def command_of(data: dict) -> str:
    """The command of Claude Code's Bash input or Antigravity's run_command."""
    tool_input = data.get("tool_input") or {}
    tool_args = (data.get("toolCall") or {}).get("args") or {}
    return (
        tool_input.get("command") or tool_args.get("CommandLine") or tool_args.get("command") or ""
    )


def main() -> int:
    global shapes_checked, last_input
    from git_options import OPTIONS, option_on

    payload = last_input = sys.stdin.read()
    data = None
    # hooks.json passes --shapes last while a shape option is on, so with them off this costs
    # one look at argv and no environment read.
    if sys.argv[-1] == "--shapes" and may_hold_shape(payload):
        from git_options import SHAPES

        shapes = {k for k in SHAPES if option_on(k)}
        if shapes:
            data, decided = check_shapes(payload, shapes)
            if decided is not None:
                return decided
    shapes_checked = True
    if not any(option_on(k) for k in OPTIONS) or cannot_name_git(payload):
        return 0
    import json
    import re

    if data is None:
        data = json.loads(payload)  # not empty: it names git or gh, or holds a `\\u` escape
    if mod_checks(data):
        return 0
    raw = command_of(data)
    if not re.search(r"\b(git|gh)\b", raw):
        return 0
    import git_checks
    import hook_output

    tool_args = (data.get("toolCall") or {}).get("args") or {}

    # agy names the folder a command runs in with run_command's Cwd, else the workspace.
    paths = data.get("workspacePaths")
    if hook_output.from_agy(data) and isinstance(tool_args.get("Cwd"), str) and tool_args["Cwd"]:
        data["cwd"] = tool_args["Cwd"]
    elif not data.get("cwd") and isinstance(paths, list) and paths:
        data["cwd"] = paths[0]
    return git_checks.check(data, raw)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"phylax git guard error: {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            from git_options import BLOCKING, MAIN_CHECKOUT, SHAPES, off_switch, option_on

            # A crash before the shape check passed leaves the shapes unchecked too.
            keys = BLOCKING if shapes_checked else (*BLOCKING, *SHAPES)
            blocking = any(option_on(k) for k in keys)
            if blocking:
                print(off_switch(keys), file=sys.stderr)
            elif option_on(MAIN_CHECKOUT):
                # Exit 0 drops stderr, so the warning verdict is what tells Claude.
                import json

                import hook_output
                from git_options import unchecked

                try:
                    agy = hook_output.from_agy(json.loads(last_input))
                except ValueError:
                    agy = False
                why = unchecked(f"{type(exc).__name__}: {exc}")
                json.dump(hook_output.warn(why, agy), sys.stdout)
        except Exception:
            blocking = True  # which guards are on cannot be read, so the check fails closed
        # hooks.json sets onFailure "block", which refuses on any exit but 0 and 2: with only
        # the warning guard on, a crash must exit 0 so it cannot stop a command.
        sys.exit(2 if blocking else 0)
