# schole

schole (σχολή, school) reads a Brightspace (D2L) course site, such as RIT's myCourses, for Claude Code. It reports new announcements and new or updated content since a time, what is due in the next two weeks, and what came due without a submission. You sign in once in a real browser window; after that it reads the site's own REST API headless with that session.

It only reads. Every request is a GET on a fixed allowlist (enrollments, announcements, the content outline, assignment folders, and the student Assignments page for submission state), and anything else is refused before it is sent. It never opens a content page, because Brightspace marks a page read, and its module complete, when you view it. It never types into a sign-in, SSO or Duo page.

## Install

```bash
/plugin marketplace add ajbarea/techne
/plugin install schole@techne
```

schole needs [uv](https://docs.astral.sh/uv/) and Playwright's Chromium. Then ask Claude to run `/schole:setup`, which follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/schole/AGENTS.md): it installs the browser and has you run `!schole-login --site <your site> --term <term code>` to sign in once.

## Use

Ask what is due or what is new in your courses, or run `/schole:courses`. epistole's `catch-me-up` also runs the course sweep when schole is installed, so one catch-up covers mail and courses. The commands are `schole-sweep [--since EPOCH]` and `schole-login [--status]`.

## Why the browser

Brightspace's API needs an OAuth app your institution registers; students cannot register one. Claude Code's own Chrome integration is not supported under WSL. A browser profile you sign into once, read with GET requests only, works for any student account at any school that runs Brightspace.

## Privacy

- schole runs on your computer. The browser profile in `~/.config/schole/profile` holds your course site's session and never leaves the machine; treat the folder like a password.
- Nothing is sent anywhere but your course site, and the course text it prints goes to the model you already run in Claude Code.
- To sign out, delete `~/.config/schole/profile`.

## Troubleshooting

- **`needs login`, exit 3.** The site's session expired, often after a few days or a password change. Run `!schole-login`.
- **Zero courses.** The term filter matches no course code. Run `!schole-login --site <site> --term <code>` with the text your current courses' codes contain.
- **`APIFAIL <course> :: news:404`.** That part of that course could not be read; the rest still was. Check it on the site yourself.
- **No window opens on WSL.** The login window needs WSLg (Windows 11).
