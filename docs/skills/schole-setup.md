---
description: schole:setup installs the browser for schole and signs you in to your Brightspace (D2L) course site once, in a real browser window.
---

# `schole:setup`

Set up or fix schole: install the browser and sign in to the course site once.

Part of [schole](../plugins/schole.md): `/plugin install schole@techne`.

## When to use

To connect your Brightspace or myCourses course site; when a schole command says `needs login` or names a missing `schole.toml`; after a password change; or when the browser for schole is missing.

## Usage

```text
/schole:setup
```

Claude follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/schole/AGENTS.md), starting with `schole-login --status`. You sign in: Claude never types into a sign-in, SSO or Duo page and never asks for a password. You run `schole-login` after `!` because it opens a window.

## Steps

1. Check where things stand: `schole-login --status` prints the site, the term filter and `signed in` or `needs login`, and exits 0 only when signed in.
2. Install Chromium: `uv run --no-project --with playwright==1.63.0 playwright install chromium`.
3. Sign in once: `!schole-login --site https://mycourses.example.edu --term 2261 --timezone America/New_York`. The window closes when the site answers, and the command gives up after 10 minutes.
4. Confirm with `schole-login --status`, then `schole-sweep`.

## See also

- [schole plugin](../plugins/schole.md): commands, configuration, privacy and troubleshooting.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/schole/skills/setup/SKILL.md) holds the full instructions Claude follows for this skill.
