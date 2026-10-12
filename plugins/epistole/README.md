# epistole

epistole (ἐπιστολή, a letter) is a local Gmail MCP server for Claude Code. It searches, reads and drafts mail in every Gmail account you configure, whichever Claude account is signed in. Its `send_draft` tool always asks you first. It runs on your computer and uses a Google OAuth client you create yourself, so no shared secret ships with it.

Install it from the techne marketplace:

```
/plugin marketplace add ajbarea/techne
/plugin install epistole@techne
```

Requires [uv](https://docs.astral.sh/uv/). The first start downloads about 30 MB of Python packages (more if uv also needs Python 3.12 or newer). If `/mcp` shows epistole failed on that first start, reconnect it from `/mcp` once the download finishes. Tools appear as `mcp__plugin_epistole_epistole__<tool>`.

## Tools

| Tool | What it does |
| --- | --- |
| `accounts` | Shows whether the Google client is set up, and each account's address, sign-in state and send-as address. Never opens a browser. |
| `search` | Searches one account, or `all`, with Gmail query syntax. Returns thread and message ids with sender, subject, date and snippet. |
| `read_thread` | Reads a thread by id. Bodies come back wrapped as untrusted content, followed by each message's attachments with their names, sizes and attachment ids. |
| `create_draft` | Creates a draft in an account, optionally as a reply, with attachments from your allowed folders. |
| `update_draft` | Replaces a draft's content and keeps its thread. |
| `download_attachment` | Saves an attachment, named by the message id and attachment id that `read_thread` lists, into your download folder. Never overwrites a file. |
| `send_draft` | Sends a draft after you approve it. |

Every id is account-qualified (`alias:id`), and a tool refuses an id whose account differs from the `account` you named.

## Set up

1. Create a Google Cloud project, enable the Gmail API, add the `gmail.readonly` and `gmail.compose` scopes under Data access, and create a Desktop app OAuth client. Publish the app to production, because tokens issued in Testing mode expire after 7 days.
2. Import the downloaded client file: `!epistole-login --client <downloaded.json> <alias>`.
3. Sign each account in: `!epistole-login <alias>`.

The full runbook is [AGENTS.md](AGENTS.md). Or ask Claude: `/epistole:setup`.

`epistole-login` records each account in `~/.config/epistole/accounts.toml`, which also holds the attachment folders and the download folder. The first login writes `attach_dirs = []`, so attachments are off until you list the folders Claude may attach from. Use a folder that holds only files you mean to send, not `~/Downloads`. Every path, and `EPISTOLE_HOME` if you set it, must be absolute or start with `~`.

```toml
attach_dirs = ["~/Documents/outgoing"]
download_dir = "~/Downloads/epistole"

[accounts]
personal = "user@example.com"
school = "user@g.example.edu"
```

### University and Workspace accounts

The Google login can differ from the address mail goes out from. A university may sign in on a subdomain such as `g.example.edu` while people write to `user@example.edu`. `accounts.toml` records the Google login address, and mail is sent from Gmail's default send-as address; `accounts` shows both. For an alias already in `accounts.toml`, `epistole-login` opens Google's account chooser with that address pre-filled.

An administrator can block apps Google has not verified, or limit third-party access to Gmail. Sign-in then ends on a Google page saying access is blocked (`Error 400: admin_policy_enforced`), and the login command times out after 5 minutes. An administrator can also allow read access but block the compose scope; sign-in then fails the same way. Only the administrator can fix that. Ask them to allow your client, or use a personal account. The claude.ai Gmail connector is the fallback for such an account.

## Safety

- **The `send_draft` tool always asks.** It carries the `anthropic/requiresUserInteraction` flag, so Claude Code prompts you before each call in every mode that can prompt, including bypass. In `dontAsk` mode the send is refused instead. The server reads the draft once and checks the recipients (To, Cc, Bcc), the subject and the attachment names that Claude restates. It refuses the send if any differs, and otherwise sends exactly the message it checked, so an edit made elsewhere after the check does not change what goes out.
- **The prompt gates the tool, not the token.** The token in `~/.config/epistole/tokens/` can also send mail, so a script that reads it could send without a prompt. The controls for that are the `Read(~/.config/epistole/**)` deny rule below and Claude Code's [sandbox](https://code.claude.com/docs/en/sandboxing), which applies that rule to shell commands too. Claude can also put any text it has read into a draft body, and that text leaves with the message once you approve the send.
- **Large drafts** (over 5 MB) are sent through Gmail's media-upload endpoint, which accepts messages up to 35 MB; a larger draft fails with an error and can be sent from Gmail itself.
- **Attachments** are off until you list folders in `attach_dirs`; the first login writes an empty list. epistole attaches files only from those folders. A path with any component starting with `.` is refused, and so is anything under `~/.config/epistole`.
- **Downloads** go only into `download_dir`, under a sanitized file name. An existing file is never replaced; the new one gets ` (1)`, ` (2)` and so on.
- **Mail text is labelled untrusted.** Message bodies and headers are wrapped in a marker saying they are data from outside, not instructions. This is a label for Claude, not a defence: a message can still try to steer it. The send prompt and the recipient re-check are the controls that hold.
- **Drafts are not gated by default.** `create_draft` and `update_draft` run without a prompt when your permission mode or an allow rule lets them, and a message that steers Claude could trigger them. They only write to Gmail drafts. To be asked before each one, add `ask` rules to `permissions` in `~/.claude/settings.json`:

  ```json
  {
    "permissions": {
      "ask": [
        "mcp__plugin_epistole_epistole__create_draft",
        "mcp__plugin_epistole_epistole__update_draft"
      ]
    }
  }
  ```

- **Keep Claude's file tools out of your tokens.** Merge this `deny` entry into the `permissions` block of `~/.claude/settings.json`:

  ```json
  {
    "permissions": {
      "deny": ["Read(~/.config/epistole/**)"]
    }
  }
  ```

  It blocks Claude's file tools and the shell reads Claude Code recognizes (`cat`, `head`, `tail`, `sed`, redirects). It does not block `grep -r` run inside the folder or a script that opens the files itself. For an OS-level boundary, [enable the sandbox](https://code.claude.com/docs/en/sandboxing).
- **Audit log.** `~/.config/epistole/audit.jsonl` (mode 0600) records each draft, update and send, including ones whose outcome is unknown, with time, account, recipients, subject and attachment names. It never holds message bodies.

## Tokens and removal

Tokens live in `~/.config/epistole/tokens/<alias>.json` (mode 0600, folder 0700). Google stops honoring a token when you change your password, when it goes unused for 6 months, when more than 100 are live for one client, or when an administrator revokes the app. Sign in again with `!epistole-login <alias>`.

To remove epistole, revoke it at [myaccount.google.com/linkedapps](https://myaccount.google.com/linkedapps) (Access to your Google Account, the app, See details, Remove access), delete `~/.config/epistole`, delete the login environment in `~/.cache/epistole` (about 160 MB), delete the files in your download folder if you no longer want them, and run `/plugin uninstall epistole@techne`.

## Troubleshooting

Run `!epistole-login --status`. It prints whether the client file is present and, per account, `signed in` or `needs login: <reason>`, and exits 0 only when every account is signed in. A tool that reports a missing sign-in names the command to run.

## Privacy

See the [privacy policy](https://ajbarea.github.io/techne/epistole/#privacy).
