---
description: epistole plugin, Gmail across accounts for Claude Code. Search, read and draft mail in every configured account, and send a draft only after you approve it. Local MCP server with your own Google OAuth client.
---

# epistole

epistole gives Claude access to your Gmail accounts. It can search and read mail, and create or update drafts. Its `send_draft` tool sends a draft only after you approve it. It runs as a local MCP server on your own computer, using a Google OAuth client that you create, so it works with several accounts at once, whichever Claude account is signed in.

## Use it when

- You want Claude to find, read or draft mail across more than one Gmail account.
- You want one catch-up that covers every inbox, and the course site too when schole is installed.

## Install

```text
/plugin marketplace add ajbarea/techne
/plugin install epistole@techne
```

## Needs

[uv](https://docs.astral.sh/uv/), and a Google OAuth client you create once. The first start downloads about 30 MB of Python packages. If `/mcp` shows epistole failed on that first start, reconnect it from `/mcp` once the download finishes.

Claude Code in the terminal or the desktop app. The plugin ships commands in `bin/`, and claude.ai and Cowork do not install a plugin that has one ([plugin reference](https://code.claude.com/docs/en/plugins-reference#standard-layout)).

## Set up

Ask Claude to run `/epistole:setup`. It guides you through creating the OAuth client, importing it, and signing each account in:

```text
!epistole-login --client <downloaded.json> <alias>
!epistole-login <alias>
```

The [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/epistole/AGENTS.md) has every step, and the [README](https://github.com/ajbarea/techne/blob/main/plugins/epistole/README.md) covers university and Workspace accounts, signatures and the safety model.

## Skills

| Skill | Use it to |
|---|---|
| [`epistole:catch-me-up`](../skills/catch-me-up.md) | Sweep every account for mail since the last sweep and report what needs you. |
| [`epistole:setup`](../skills/epistole-setup.md) | Create the Google OAuth client and sign each account in. |

## Commands and tools

The MCP server's tools appear as `mcp__plugin_epistole_epistole__<tool>`.

| Tool | What it does |
|---|---|
| `accounts` | Shows whether the Google client is set up, and each account's address, sign-in state and send-as address. Never opens a browser. |
| `search` | Searches one account, or `all`, with Gmail query syntax. Takes `max_results` (1 to 50) and `page_token`, which works with one account. |
| `read_thread` | Reads a thread by id. `full=true` keeps quoted replies and lists more attachments per message. Bodies come back marked as untrusted content. |
| `create_draft` | Creates a draft in an account, optionally as a reply, with attachments from your allowed folders. A new draft gets the account's Gmail signature; a reply does not. |
| `update_draft` | Replaces a draft's content and keeps its thread. |
| `download_attachment` | Saves an attachment into your download folder. Never overwrites a file. |
| `send_draft` | Sends a draft after you approve it. |

Every id is account-qualified (`alias:id`), and a tool refuses an id whose account differs from the `account` you named.

Two commands run in a terminal, or in Claude Code after `!`:

| Command | What it does |
|---|---|
| `epistole-login --status` | Prints whether the client file is present and, per account, `signed in`, `needs login: <reason>` or `could not check (network error)`. Exits 0 only when every account is signed in. |
| `epistole-login [--client FILE] <alias>` | Imports the Google client, or signs one account in. A new alias adds the account. With no arguments, or with `--status` and an alias together, it prints its usage and exits 2. |
| `epistole-since` | Prints the catch-up window: the last sweep time (or, with none, the start of yesterday, Friday on a Monday), the current time and a Gmail `after:` query. |
| `epistole-since --set EPOCH` | Records when a sweep read the inboxes. |

`epistole-login` exits 127 when uv is not on PATH.

## Configuration

`~/.config/epistole/accounts.toml` records the accounts, the attachment folders and the download folder. Set `EPISTOLE_HOME` to move the folder; the value must be absolute or start with `~`.

```toml
attach_dirs = ["~/Documents/outgoing"]
download_dir = "~/Downloads/epistole"
timezone = "America/New_York"   # optional, an IANA name; else the machine's zone

[accounts]
personal = "user@example.com"
school = "user@g.example.edu"
```

- Attachments are off until you list folders in `attach_dirs`. Attach paths must be absolute, and a file or the total may not exceed 25 MB.
- `epistole-since` keeps its time in `catch-me-up.json` in the same folder.
- `XDG_CACHE_HOME` moves the login environment from `~/.cache/epistole`. The MCP server's own environment lives in Claude Code's plugin data folder.

## Privacy

epistole runs on your computer and sends nothing to its author. Read the [epistole privacy policy](../epistole.md), which is the policy for the Google OAuth app.

## Troubleshooting

- **`/mcp` shows epistole failed, or the `accounts` tool is missing.** The server starts through `uv`. Run `command -v uv`; if it prints nothing, install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh`, then restart Claude Code, because the server takes its PATH from the session that starts it. If uv is installed, the first start was probably still downloading packages: reconnect epistole from `/mcp`.
- **An account `needs login`.** Run `!epistole-login <alias>`. Google stops honoring a token when you change your password, when it goes unused for 6 months, or when an administrator revokes the app.
- **Sign-in ends on a page saying access is blocked (`Error 400: admin_policy_enforced`).** An administrator limits third-party access to Gmail. Only the administrator can fix that, or use a personal account.
- **`epistole-login` says uv is not on PATH.** Install uv the same way, open a new terminal, and run the command again.
