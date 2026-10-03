# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

### #98: restart idle sessions onto an updated Claude Code

**Why.** An auto-update lands on disk, but every open session keeps the old binary until it is
restarted by hand. The opt-in `restart_on_update` hook moves an idle session onto the installed
binary with `claude --resume`, so the conversation carries over.

**Decisions.**
- Trigger on `Notification`/`idle_prompt` (about 60 s after each turn). Gate on the session's own
  `~/.claude/sessions/<pid>.json`: `version` differs from the `claude` on `PATH`, `status` is
  `idle`, `kind` is `interactive`, `procStart` matches `/proc/<pid>/stat`. `idle_prompt` alone
  fires during background jobs; the file reads `shell` then.
- A `Stop` hook records the turn's `background_tasks`, `session_crons`, effort and permission
  mode; the check refuses on a running task or any session cron, which would die with the process.
- The resumed model is the transcript's latest reply model, so `/model` switches carry over.
- One Python file, `hooks/stale_restart.py`, run as the hook and as the handoff, so both apply
  the same check. Python 3.9, stdlib only, like `git_guards.py`.
- Launchers: tmux when the session file names a pane, else Windows Terminal (`wt.exe -w 0 nt`)
  under WSL, else one notice per session and nothing else.
- The handoff shows a 15 s countdown any key cancels, re-checks, sends SIGTERM, waits, and never
  sends SIGKILL. A cancel is remembered per session and installed version.
- The old WT tab closes only on exit 0, so the shell exits through a documented `PROMPT_COMMAND`
  snippet keyed on a marker file; without it the shell gets SIGHUP. tmux respawns the old pane.
- Launch flags are carried over from an allowlist, never the positional prompt or session flags.

**Out of scope.** macOS and native Windows launchers; sessions started by `--bg`/jobs.

**Done when.** Unit tests cover the gate matrix, flag carry-over, both launchers' argv and the
handoff's refusals; a live tmux run and a live WT run move a 2.1.287 session onto 2.1.288 with
the conversation intact; `make validate` passes; elenchus review is clean.

**Next pickup:** #96, backing the commit guards with Git 2.54 config-based `commit-msg` and
`pre-commit` hooks set through `CLAUDE_ENV_FILE`, so commits the Bash parser cannot see are
still checked. Blocked on Git 2.54 being available to test against.

## Skill collection state

Shipped skills by catalog dimension (the directory listing of `plugins/techne/skills/` is the source of truth):

| Dimension | Skills |
| --- | --- |
| **Audit** | `audit`, `ci-audit` |
| **Drift** | `docsync`, `docs-site`, `research-grounded`, `sisters` |
| **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| **Review** | `catchup`, `elenchus` |
| **Observation** | `theoros` |
| **Document build** | `latex`, `pdf`, `paper`, `paper-review`, `slides` |

When picking up the next session, replace the "In flight" block above
with a full session plan (Why / Decisions / Scope / Out of scope /
Definition of done) following the same template every other sister
uses.
