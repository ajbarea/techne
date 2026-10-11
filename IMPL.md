# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

### `epistole` — Gmail for Claude Code across accounts (spec approved 2026-10-10, after review)

**Why.** The claude.ai Gmail connector holds one Google account and belongs to the signed-in Claude
account, so switching between a personal and a university Claude seat loses an inbox. A local MCP
server reaches every configured Gmail account whichever Claude account is active.

**Decisions** `# research(2026-10)`
- MCP Python SDK v2 (`mcp>=2,<3`, `MCPServer`), stdio, `uv` env in `${CLAUDE_PLUGIN_DATA}`. Scopes
  `gmail.readonly` + `gmail.compose` (no drafts-only scope exists; compose can send).
- Tools take an `account` alias; ids come back account-qualified (`rit:<id>`) and a mismatch is
  refused. Tools: `search` (or `all`), `read_thread`, `create_draft`, `update_draft`,
  `download_attachment`, `send_draft`. Replies set `threadId`, `In-Reply-To`/`References`, a matching
  Subject and an explicit `From`. Output budgeted under 50k characters: HTML to text, quoted replies
  trimmed, pagination. Tool list and examples live in the plugin README.
- Send gate: `send_draft` carries `_meta["anthropic/requiresUserInteraction"]: true`, so it prompts
  on every call in every mode, bypass included. It takes the account, recipients, subject and
  attachment names, so the prompt shows them; the server re-reads the draft and refuses a mismatch.
- Exfiltration limits: attachments only from allowlisted directories, never dotfiles or
  `~/.config/epistole`; downloads to a fixed directory, sanitized names, no overwrite. Bodies are
  wrapped as untrusted content, a label rather than a defence. The audit log holds metadata only
  (time, alias, ids, recipients, subject), 0600. README recommends `Read(~/.config/epistole/**)` deny.
- Auth: the user's own Desktop OAuth client; loopback + PKCE on `127.0.0.1`, random port, URL always
  printed (WSL). Login is `bin/epistole-login <alias>`, run with `!`. Tokens per alias in
  `~/.config/epistole/`, 0600; `invalid_grant` returns a re-login hint and the server starts with no
  tokens. Personal client published "In production" unverified (re-login after publishing; tokens
  also die on password change, 6 months unused, or past 100 per client). 429s back off.
- Workspace spike (2026-10-11): the university account grants both scopes. Google does not know the
  plain-domain address; its Google login is a `g.` subdomain address while mail goes out from the plain
  domain, so `accounts.toml` holds the login address and `From` is Gmail's default send-as, read from
  the API.

**Scope.** `plugins/epistole/`, marketplace entry, docs-site page + nav, first-run onboarding (an
`AGENTS.md` setup runbook any agent can follow, a `/epistole:setup` skill pointing at it,
`epistole-login --client` import, accounts added on first login, `--status` and an `accounts` tool), an `epistole` dependency group
so `ty` resolves, tests in `tests/` against a fake Gmail (MIME, threading, attachment allowlist,
id routing, the send flag in `tools/list`). First step: a login spike against the Workspace account
requesting the exact scopes, which also confirms `MCPServer` can set tool `_meta`.

**Out of scope.** Labels, archive/delete, Calendar/Drive, push notifications, a hosted server.

**Definition of done.** Under either Claude account, both inboxes search, read and draft; a send
prompts under bypass (tmux smoke); a live check shows a draft reply threaded in Gmail and a send to
self arriving; refresh token alive after 8 days; tests and docs green. Workspace outcomes: works,
works read-only (admin blocks compose), or blocked (stays on the claude.ai connector); README says which.

**Next pickup after epistole:** a marketplace-wide onboarding pass, so each plugin can be cited as a
finished tool. Every plugin gets the epistole pattern where it has setup: a plugin-level `AGENTS.md` an
agent can follow, a setup or status entry point, and errors that name the next command. Every README
gets install, first use and troubleshooting, and the docs site gets a getting-started path per plugin,
with a citation file (`CITATION.cff`) at the repo root.

**After that:** #96, backing the commit guards with Git 2.54 config-based `commit-msg` and
`pre-commit` hooks set through `CLAUDE_ENV_FILE`, so commits the Bash parser cannot see are
still checked. Blocked on Git 2.54 being available to test against.

## Skill collection state

Shipped plugins and skills by catalog dimension (the directory listing of `plugins/*/skills/` is the source of truth):

| Plugin | Dimension | Skills |
| --- | --- | --- |
| `techne` | **Audit** | `audit`, `ci-audit` |
| `techne` | **Drift** | `docsync`, `docs-site`, `research-grounded`, `sisters` |
| `techne` | **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| `techne` | **Review** | `catchup`, `elenchus` |
| `techne` | **Observation** | `theoros` |
| `graphe` | **Document build** | `latex`, `pdf`, `paper`, `paper-review`, `slides` |
| `dokimasia` | **Bibliography** | `check` |
| `epistole` | **Mail** | MCP server, setup |
| `phylax` | **Hooks** | git guards (a mod, `hooks/register.ts`), `restart_on_update` (command hooks) |

When picking up the next session, replace the "In flight" block above
with a full session plan (Why / Decisions / Scope / Out of scope /
Definition of done) following the same template every other sister
uses.
