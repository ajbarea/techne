---
max_turns: 6
timeout_seconds: 240
runs: 3
allowed_tools: [Read, Glob, Grep, Skill]
plugins: ["../../eval-fixtures/with-rivals"]
tags: [routing, collision]
---

Merge report1.pdf and report2.pdf into one file.
