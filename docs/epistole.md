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
- It reads Gmail only when your Claude Code session calls one of its tools, or when you run `epistole-login` to sign in or check an account.
- Your tokens and the audit log stay on your machine under `~/.config/epistole`. The audit log records the time, account, recipients, subject and attachment names of each draft, update and send, never message bodies. Attachments you download are saved in your download folder (by default `~/Downloads/epistole`), and mail Claude reads is also kept in Claude Code's own local session transcripts.
- Nothing is sent to the techne author or to any third party, other than Google's Gmail API and the AI model you are already running in Claude Code. Mail the tools return to Claude is processed by that model under your own agreement with its provider.
- Claude creates or updates a draft when it calls those tools in your session. Sending a draft always needs your approval at a Claude Code prompt, in every mode that can prompt. You can also require a prompt for drafts, with the `ask` rules in the [README](https://github.com/ajbarea/techne/blob/main/plugins/epistole/README.md#safety).
- It requests two scopes. `gmail.readonly` lets it search and read mail. `gmail.compose` lets it create, update and send drafts. It does not request `gmail.modify` or full mailbox access. epistole has no tool that deletes mail or changes labels, and its scopes cannot delete received mail or change labels.
- To revoke access, open [myaccount.google.com/linkedapps](https://myaccount.google.com/linkedapps), choose Access to your Google Account, then epistole, See details, Remove access and Confirm. Then delete `~/.config/epistole` to remove the stored tokens.

The use and transfer of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements, and to the [Google Workspace API User Data and Developer Policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy).

epistole does not use Gmail data to train AI or ML models. Whether your model provider may train on conversation content depends on your agreement and settings with that provider.

Questions go to [github.com/ajbarea/techne/issues](https://github.com/ajbarea/techne/issues).
