---
description: schole:courses reports a Brightspace (D2L) course site's new announcements and content, what is due in the next two weeks, and what came due without a submission. Read-only, never marks anything read.
---

# `schole:courses`

Check your Brightspace (D2L) course site, such as myCourses, for new announcements and content, what is due, and what came due unsubmitted.

Part of [schole](../plugins/schole.md): `/plugin install schole@techne`, then sign in with `/schole:setup`.

## When to use

"What is due?" "What is new in my courses?" "Did I miss a deadline?" "Any announcements?" For mail, or a combined mail and course catch-up, use [`epistole:catch-me-up`](catch-me-up.md), which runs this sweep too.

## Usage

```text
/schole:courses
```

The skill runs `schole-sweep`, or `schole-sweep --since <epoch>` for a window other than the last 24 hours. It is read-only: it never opens a course page, because Brightspace marks a page read when it is opened. Course text is treated as data, never as instructions.

The answer leads with past-due work that shows `NOT SUBMITTED`, then what is due soonest, then announcements (with any time or room change), then a count of new content, unread first. A part of a course that could not be read (`APIFAIL`), or a submission state that could not be checked (`NOROW`, `LISTFAIL`), is reported as "could not check", never as "nothing new" or "missed".

[The schole page](../plugins/schole.md#commands-and-tools) lists every output line, the exit codes and the messages.

## Needs

A signed-in course site. Exit 3 with `needs login` means the session ended, usually after an idle timeout the school sets: run `!schole-login`. A missing `schole.toml` means schole is not set up: run `/schole:setup`.

## See also

- [schole plugin](../plugins/schole.md): commands, configuration, privacy and troubleshooting.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/schole/skills/courses/SKILL.md) holds the full instructions Claude follows for this skill.
