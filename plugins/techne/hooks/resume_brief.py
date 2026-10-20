#!/usr/bin/env python3
"""SessionStart hook: tell a fresh session where the work in this worktree stands.

In a repo that keeps an IMPL.md at its root, it adds as context the branch's IMPL.md, its
commits past the default branch, its uncommitted files and whether it was pushed, then the
rule that keeps IMPL.md the branch's resume state. Elsewhere it prints nothing.

Reads the hook JSON on stdin for cwd. Local git only, no network. Never fails and never
prints an error: a hook that does is noise. Runs on python3 3.9.
"""

from __future__ import annotations

import json
import os
import sys

sys.dont_write_bytecode = True  # the plugin cache stays as installed
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_shared"))
import resume_state  # noqa: E402  # ty: ignore[unresolved-import]

# Claude Code caps additionalContext at 10,000 characters; past it, Claude gets a preview.
CONTEXT_CAP = 9500
IMPL_CAP = 6000
DIRTY_SHOWN = 15

RULE = (
    "Keep IMPL.md the resume state of this branch: after each finished task, rewrite what "
    "the slice is, what is done, what is next and how to verify it, then commit and push. "
    "A session that starts here after a restart, /clear or compaction resumes from IMPL.md, "
    "git log and the working tree alone."
)
RULE_ON_BASE = (
    "IMPL.md on the default branch describes the last slice merged. Start new work on a "
    "branch in its own worktree, and keep that branch's IMPL.md as its resume state: after "
    "each finished task, rewrite what the slice is, what is done, what is next and how to "
    "verify it, then commit and push."
)


def brief(s: resume_state.ResumeState) -> str:
    where = f"branch `{s.branch}`" if s.branch else f"detached HEAD at {s.head}"
    lines = [f"Resume brief (techne) for `{s.repo}`, {where}, in {s.root}:"]
    if s.base and not s.on_base:
        lines.append(f"- Commits past {s.base}: {s.ahead}" + (" (newest first)" if s.ahead else ""))
        lines += [f"  - {c}" for c in s.commits]
        if s.ahead > len(s.commits):
            lines.append(f"  - and {s.ahead - len(s.commits)} older")
    if s.dirty:
        lines.append(f"- Uncommitted: {len(s.dirty)} path(s)")
        lines += [f"  - `{d}`" for d in s.dirty[:DIRTY_SHOWN]]
        if len(s.dirty) > DIRTY_SHOWN:
            lines.append(f"  - and {len(s.dirty) - DIRTY_SHOWN} more (`git status`)")
    else:
        lines.append("- Uncommitted: nothing")
    if s.branch:
        if not s.pushed_to:
            lines.append("- Pushed: never")
        elif s.unpushed:
            lines.append(f"- Pushed: to {s.pushed_to}, {s.unpushed} commit(s) not pushed yet")
        else:
            lines.append(f"- Pushed: {s.pushed_to} is up to date")
    if s.impl is None:
        lines.append(
            f"- IMPL.md: missing here although {s.base} has one; write it for this branch."
        )
    elif s.impl_matches_base:
        lines.append(
            f"- IMPL.md: unchanged from {s.base}, so it does not describe this branch yet. "
            "Read the commits and the uncommitted diff, then rewrite it for this branch."
        )
    head = "\n".join(lines) + "\n\n" + (RULE_ON_BASE if s.on_base else RULE)
    if s.impl is None:
        return head
    room = min(IMPL_CAP, CONTEXT_CAP - len(head) - 200)
    impl = s.impl.strip()
    if len(impl) > room:
        impl = impl[: max(room, 0)].rstrip() + "\n[... cut here; read IMPL.md for the rest]"
    label = f"IMPL.md as {s.base} has it:" if s.impl_matches_base else "IMPL.md:"
    return f"{head}\n\n{label}\n\n{impl}"


def hook_cwd() -> str:
    try:
        cwd = json.load(sys.stdin).get("cwd")
    except (ValueError, OSError, AttributeError):
        cwd = None
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()


def main() -> int:
    try:
        s = resume_state.read(hook_cwd())
        if s is None or (s.impl is None and s.impl_matches_base is None):
            return 0  # not a repo, or one that keeps no IMPL.md
        out = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": brief(s)[:CONTEXT_CAP],
            }
        }
    except Exception:
        return 0
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
