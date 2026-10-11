# epistole

epistole is a Claude Code plugin that gives Claude access to your Gmail accounts. It can search and read mail, and create or update drafts. It sends a draft only after you approve it. It runs as a local server on your own computer, using a Google OAuth client that you create, so it works with several accounts at once, whichever Claude account is signed in.

## Install

```bash
/plugin marketplace add ajbarea/techne
/plugin install epistole@techne
```

epistole needs [uv](https://docs.astral.sh/uv/). Then ask Claude to run `/epistole:setup`, or follow the [setup guide](https://github.com/ajbarea/techne/blob/main/plugins/epistole/AGENTS.md) yourself. The [README](https://github.com/ajbarea/techne/blob/main/plugins/epistole/README.md) lists the tools and the safety model.

## Privacy

This is the privacy policy for epistole, the Google OAuth app it signs in with.

- epistole runs entirely on your computer.
- It reads Gmail only when your Claude Code session calls one of its tools.
- Your tokens and the audit log stay on your machine under `~/.config/epistole`. The audit log records the time, account, recipients, subject and attachment names of each draft and send, never message bodies.
- Nothing is sent to the techne author or to any third party, other than Google's Gmail API and the AI model you are already running in Claude Code. Mail the tools return to Claude is processed by that model under your own agreement with its provider.
- epistole creates a draft or sends mail only when you ask. Every send asks you to approve it first, in every permission mode.
- It requests two scopes. `gmail.readonly` lets it search and read mail. `gmail.compose` lets it create, update and send drafts. It does not request `gmail.modify` or full mailbox access, so it cannot delete mail or change labels.
- To revoke access, open Google Account, Security, Third-party access, choose epistole, and remove access. Then delete `~/.config/epistole` to remove the stored tokens.

Use of information received from Google APIs follows the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including its Limited Use requirements.

Questions go to [github.com/ajbarea/techne/issues](https://github.com/ajbarea/techne/issues).
