---
max_turns: 6
timeout_seconds: 240
runs: 3
allowed_tools: [Read, Glob, Grep, Skill]
plugins: ["../../eval-fixtures/with-rivals"]
tags: [routing, collision]
---

That was wrong: parse_rows should return an empty list when the file is empty, not None. Fix it.
