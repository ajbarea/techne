---
description: "Keep a decided quality lesson so the next deck, paper, docs site or app starts ahead: read it, add it at the moment of a correction, retire it when a later decision replaces it."
---

# `techne:lessons`

Each lesson is a decision that made the work better. Lessons live with the plugin that uses them, one file per surface, and a skill loads only its own: decks and papers in graphe, docs sites and app UI in techne, with a shared file carried by both. Only techne's maintainers change the files, through a pull request; for anyone else the skill writes the rule for their project's `CLAUDE.md` or `AGENTS.md`.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

## When to use

- Before building or restyling a web app or a project's user-facing surface; decks, papers and docs sites load their lessons themselves.
- The moment a result is corrected and the correction should hold next time: "from now on", "that was wrong", "remember this".
- When a later decision supersedes a lesson.

## Usage

```
/techne:lessons
```

An entry is one heading and four fields: **Rule**, **Why**, **Since** and **Check**. **Check** names a gate and its test, or says why the lesson stays guidance. `tests/test_lessons.py` fails a gate whose named test never mentions it, and a file over its word budget. A retired lesson keeps one line naming what replaced it; git keeps the rest.

Each surface names a reference to beat, so new work is compared with the best one so far.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/lessons/SKILL.md) holds the full instructions Claude follows for this skill.
