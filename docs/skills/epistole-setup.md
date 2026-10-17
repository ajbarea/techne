---
description: epistole:setup guides creating the Google OAuth client and signing each Gmail account in, and fixes an epistole server that did not start or an account that needs login.
---

# `epistole:setup`

Set up or fix epistole Gmail access: create the Google OAuth client once, then sign each account in.

Part of [epistole](../plugins/epistole.md): `/plugin install epistole@techne`.

## When to use

To connect Gmail accounts, add another account, or create the Google OAuth client; when an epistole tool says an account is not signed in, needs login or has no OAuth client; or when the epistole server fails to start because uv is missing.

## Usage

```text
/epistole:setup
```

Claude follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/epistole/AGENTS.md), starting with the `accounts` tool, and skips steps that are done. You create the OAuth client in the Google Cloud console and run `epistole-login` after `!`, because it opens a browser. Claude never asks you to paste a token or the client secret into chat, and never reads `client_secret.json` or `tokens/`.

## Steps

1. Check where things stand (`accounts`, or `!epistole-login --status`).
2. Create a Google OAuth client of type Desktop app, with the `gmail.readonly` and `gmail.compose` scopes, and publish the app to production so tokens do not expire after 7 days.
3. Import it: `!epistole-login --client <downloaded.json> <alias>`.
4. Sign each account in: `!epistole-login <alias>`.
5. Choose attachment folders in `attach_dirs`, if you want attachments.

## See also

- [epistole plugin](../plugins/epistole.md): tools, commands, configuration and troubleshooting.
- [epistole privacy policy](../epistole.md).

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/epistole/skills/setup/SKILL.md) holds the full instructions Claude follows for this skill.
