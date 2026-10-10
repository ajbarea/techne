# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

### `epistole` — Gmail for Claude Code across accounts (design approved 2026-10-10)

**Why.** The claude.ai Gmail connector holds one Google account and belongs to the signed-in
Claude account, so switching between a personal and a university Claude seat loses one inbox.
A local MCP server reaches every configured Gmail account whichever Claude account is active.

**Decisions** `# research(2026-10)`
- Official MCP Python SDK v2 (`mcp>=2,<3`, its `MCPServer`), stdio, launched by `uv` with pinned deps.
- Scopes `gmail.readonly` + `gmail.compose` only. No drafts-only scope exists; compose can send.
- Few consolidated tools, each taking `account` (`all` for search): `search`, `read_thread`,
  `create_draft`, `update_draft` (thread replies via `threadId` + `In-Reply-To`/`References`;
  attachments from disk paths), `download_attachment`, `send_draft` (draft id only). Concise output
  by default, under Claude Code's 25k-token tool-output cap.
- Send safety: users add a `permissions.ask` rule for `send_draft`, the one control no mode
  auto-approves (plugins cannot ship permission rules); message bodies returned inside an untrusted-
  content wrapper; an append-only local log of drafts and sends.
- Accounts in a config file (alias → address); tokens per alias under `~/.config/epistole/`, 0600,
  with the user's own Desktop OAuth client. Loopback + PKCE via `InstalledAppFlow`, random port,
  printed-URL fallback for WSL. Personal client published "In production" unverified to escape
  Testing's 7-day refresh-token expiry (verified empirically, not documented for restricted scopes).

**Scope.** `plugins/epistole/` (plugin.json, `.mcp.json`, server, `login` CLI, README), marketplace
entry, docs-site page, unit tests against a fake Gmail service (MIME, reply headers, attachments,
wrapper, account routing). First step: a login spike against a Workspace account, since a school
admin can block unverified apps from restricted scopes (`admin_policy_enforced`).

**Out of scope.** Labels, archive/delete, Calendar/Drive, push notifications, a hosted server.

**Definition of done.** Both accounts searchable, readable and draftable from a session under either
Claude account; `send_draft` prompts under bypass; refresh token alive after 8 days; tests and docs
green. If the Workspace spike is blocked, that account stays on the claude.ai connector and the
README says so.

**Next pickup after epistole:** #96, backing the commit guards with Git 2.54 config-based `commit-msg` and
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
| `phylax` | **Hooks** | git guards (a mod, `hooks/register.ts`), `restart_on_update` (command hooks) |

When picking up the next session, replace the "In flight" block above
with a full session plan (Why / Decisions / Scope / Out of scope /
Definition of done) following the same template every other sister
uses.
