# schole setup runbook

This is the setup guide for schole, written for an agent guiding a user. schole reads a Brightspace (D2L) course site through the site's own API, using a browser profile the user signs into once. It only reads: every request is a GET on a fixed allowlist, and it never opens a content page, which would mark the item read.

## Rules

- The user signs in. Never type into a sign-in, SSO or Duo page, and never ask for a password. The login command opens a real browser window for them.
- The user runs `schole-login`, because it opens a window. In Claude Code they type it after `!`.
- The profile in `~/.config/schole/profile` holds the site's session. Never read, copy or print anything in it.
- Report only what the commands print.

## 1. Check where things stand

Run `schole-login --status`. It prints the site, the term filter, and `signed in` or `needs login`, and exits 0 only when signed in. If Chromium is missing it says so and names the install command from step 2 (exit 4). With no setup yet it says `no ~/.config/schole/schole.toml` and names the command for step 3.

If the shell says `uv` is not found, the user installs it with `curl -LsSf https://astral.sh/uv/install.sh | sh` and opens a new terminal.

## 2. Install the browser

schole drives Playwright's Chromium. Run `uv run --no-project --with playwright==1.63.0 playwright install chromium` after the user approves. On Linux, if the browser later fails to start for missing libraries, the user runs `uv run --no-project --with playwright==1.63.0 playwright install-deps chromium`, which uses `sudo`.

## 3. Sign in once

Ask the user for the course site's address (the origin, such as `https://mycourses.example.edu`) and the text their current term's course codes contain (at RIT the Fall 2026 term code is `2261`). Then they run:

```
!schole-login --site https://mycourses.example.edu --term 2261 --timezone America/New_York
```

A Chromium window opens on the site. The user signs in as usual, SSO and Duo included. The command watches for the site's API to answer, prints `signed in`, and closes the window; it gives up after 10 minutes. `--timezone` is optional and sets the zone for printed times. The settings land in `~/.config/schole/schole.toml`, which the user may edit.

On WSL the window needs WSLg (Windows 11). Without a display the window cannot open.

## 4. Confirm

Run `schole-login --status` again, then `schole-sweep`. The sweep prints one `OK` or `APIFAIL` line per course, then any `ANNOUNCE`, `CONTENT`, `DUE` and `PASTDUE` lines. Zero courses usually means the term filter matches nothing; run `!schole-login --site <site> --term <code>` with the right code.

When the site's session expires (often after a few days or a password change), commands print `needs login` and exit 3. The user runs `!schole-login` again with no options.
