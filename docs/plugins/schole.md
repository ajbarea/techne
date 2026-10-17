---
description: schole plugin, a read-only Brightspace (D2L) course-site reader for Claude Code. Reports new announcements and content, what is due, and what came due unsubmitted after one browser sign-in.
---

# schole

schole (σχολή, school) reads a Brightspace (D2L) course site, such as RIT's myCourses, for Claude Code. It reports new announcements and new or updated content since a time, what is due in the next two weeks, and what came due without a submission. You sign in once in a real browser window; after that it reads the site's own REST API headless with that session.

It only reads. Every request is a GET on a fixed allowlist (enrollments, announcements, the content outline, assignment folders, and the student Assignments page for submission state), and anything else is refused before it is sent. It never opens a content page, because Brightspace marks a page read, and its module complete, when you view it. It never types into a sign-in, SSO or Duo page.

## Use it when

- You ask what is due, what is new in your courses, or whether you missed a deadline.
- You want course announcements without opening the site.

## Install

```text
/plugin marketplace add ajbarea/techne
/plugin install schole@techne
```

## Needs

[uv](https://docs.astral.sh/uv/) and Playwright's Chromium. On WSL the sign-in window needs WSLg (Windows 11).

Claude Code in the terminal or the desktop app. The plugin ships commands in `bin/`, and claude.ai and Cowork do not install a plugin that has one ([plugin reference](https://code.claude.com/docs/en/plugins-reference#standard-layout)).

## Set up

Ask Claude to run `/schole:setup`. It follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/schole/AGENTS.md): it installs the browser and has you sign in once:

```text
!schole-login --site https://mycourses.example.edu --term 2261 --timezone America/New_York
```

`--site` is your course site's https origin, `--term` is text every current course code contains, and `--timezone` is optional.

## Skills

| Skill | Use it to |
|---|---|
| [`schole:courses`](../skills/courses.md) | Report new announcements and content, what is due, and what came due unsubmitted. |
| [`schole:setup`](../skills/schole-setup.md) | Install the browser and sign in to the course site once. |

epistole's [`catch-me-up`](../skills/catch-me-up.md) also runs the course sweep when schole is installed, so one catch-up covers mail and courses.

## Commands and tools

| Command | What it does |
|---|---|
| `schole-login --site URL --term TEXT [--timezone ZONE]` | Opens a browser window on the site and waits up to 10 minutes for you to sign in. The options are saved in `schole.toml`; later runs may omit them. |
| `schole-login --status` | Checks the sign-in headless and prints the site, the term filter and `signed in` or `needs login`. Exits 0 only when signed in. |
| `schole-sweep [--since EPOCH]` | Prints what changed since `EPOCH` (epoch seconds; default 24 hours ago) and what is due. |

Exit codes: `0` success, `1` a missing or bad setting (`schole.toml`, `--site`, `--timezone`) or a sign-in that did not finish (a closed window, or a login that ran out of time), `2` an unknown option or a `--since` that is not a number, `3` `needs login`, `4` the course site failed or the browser could not run (Chromium missing, profile in use), `127` uv is not on PATH. `--help` on either command lists them with examples.

`schole-sweep` prints a header line (`<site> since <time>: N courses`), then for each course an `OK` or `APIFAIL` line followed by that course's lines:

| Line | Meaning |
|---|---|
| `OK <course> :: news N topics N dropbox N` | The course was read. |
| `APIFAIL <course> :: news:404` | That part of that course could not be read; the rest still was. |
| `ANNOUNCE <course> :: <title> :: <time> :: <body start>` | An announcement posted after the window start. |
| `CONTENT <course> :: <title> :: <time> :: UNREAD\|seen` | Content changed after the window start. |
| `DUE <course> :: <assignment> :: <due time>` | Due within two weeks. |
| `PASTDUE <course> :: <assignment> :: <due time> :: <state>` | Came due inside the window. The state is `NOT SUBMITTED`, `<n> submitted`, or `NOROW` or `LISTFAIL <status>` when it could not be checked. |

## Configuration

`~/.config/schole/schole.toml` holds three keys, written by `schole-login`. An unknown key is an error.

```toml
site = "https://mycourses.example.edu"
term = "2261"
timezone = "America/New_York"   # optional, an IANA name
```

`SCHOLE_HOME` moves the whole folder, the profile included; it must be absolute or start with `~`.

## Why the browser

Brightspace's API needs an OAuth app your institution registers; students cannot register one. Claude Code's own Chrome integration is not supported under WSL. A browser profile you sign into once, read with GET requests only, works for any student account at any school that runs Brightspace.

## Privacy

- schole runs on your computer. The browser profile in `~/.config/schole/profile` holds your course site's session, including a copy of its session cookies in `session-cookies.json` (readable by you only) that schole refreshes after each run once the site accepts the session, so the sign-in survives the browser closing. It never leaves the machine; treat the folder like a password.
- `session-cookies.json` holds only the course site's own session cookies. Cookies set by the sign-in provider are not kept.
- Nothing is sent anywhere but your course site, and the course text it prints goes to the model you already run in Claude Code.
- To sign out here, delete `~/.config/schole/profile`, which removes the saved cookies too. This does not end the session on the site's server.

## Troubleshooting

- **`needs login`, exit 3.** The site's session ended. Brightspace ends it after an idle timeout the school sets, and on a password change. A refused cookie restore can also cause it. The line ends with when the site last accepted the session, if it ever did. Run `!schole-login`.
- **Zero courses.** The term filter matches no course code. Run `!schole-login --site <site> --term <code>` with the text your current courses' codes contain.
- **`APIFAIL <course> :: news:404`.** That part of that course could not be read; the rest still was. Check it on the site yourself.
- **`schole: the course site failed (...); try again later.`** The site did not answer. Exit 4.
- **`the browser profile is in use; close the schole-login window and try again`.** Another schole browser is open on the same profile.
- **`Chromium is not installed for schole; run: ...`.** Run the command it prints. On Linux, if the browser then fails for missing libraries, run `uv run --no-project --with playwright==1.63.0 playwright install-deps chromium`.
- **`the browser window closed before the site answered`.** Run the command again and leave the window open.
- **`schole: could not restore the saved sign-in` or `could not save the sign-in`.** The cookie file could not be read into the browser or written. The next run signs in again if the site's session is gone.
- **No window opens on WSL.** The login window needs WSLg (Windows 11).
