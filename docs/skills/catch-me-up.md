---
description: epistole:catch-me-up sweeps every Gmail account for mail since the last sweep, plus the course site when schole is installed, and reports what needs a reply or a decision. Read-only.
---

# `epistole:catch-me-up`

Catch up on everything new in all your Gmail inboxes since the last sweep, and say what needs a reply or a decision.

Part of [epistole](../plugins/epistole.md): `/plugin install epistole@techne`, then sign accounts in with `/epistole:setup`.

## When to use

"Catch me up." "What did I miss?" "Anything new in my email?" It covers course-site, calendar and service notifications that arrive by email. Not for GitHub repos, issues or pull requests: that is [`techne:catchup`](catchup.md).

## Usage

```text
/epistole:catch-me-up
```

The skill is read-only. It never sends, drafts, archives, labels or marks anything. It searches each signed-in account for mail after the window start, archived and filtered mail included, and opens a thread only when the snippet cannot answer a date, deadline or question. Mail content is treated as data, never as instructions. The digest leads with what needs you and what is time-sensitive, by account.

## The window

`epistole-since` keeps the window. It prints the last sweep time, or with no record the start of yesterday (Friday on a Monday), and a Gmail `after:<epoch>` query that reaches 10 minutes before the last sweep so late-indexed mail is not lost. After a full sweep the skill records the time with `epistole-since --set <epoch>`. It skips the record, and says so, when an account needed login, a search failed, or you asked for a custom window ("since Monday") or only some accounts. Times use the `timezone` in `accounts.toml`, else the machine's zone. The time is kept in `catch-me-up.json` in the epistole folder.

## Course sites

When `schole-sweep` is on PATH (the schole plugin), the skill also runs it with the same window and reports past-due unsubmitted work, what is due, announcements and new content. Its `needs login` (exit 3) is reported like an unsigned account.

## See also

- [`schole:courses`](courses.md): the course sweep.
- [epistole plugin](../plugins/epistole.md): tools and commands.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/epistole/skills/catch-me-up/SKILL.md) holds the full instructions Claude follows for this skill.
