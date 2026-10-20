---
max_turns: 6
timeout_seconds: 240
runs: 3
allowed_tools: [Read, Glob, Grep, Skill]
plugins: ["../../eval-fixtures/with-rivals"]
tags: [routing]
---

Across all my repos, what's merged but not live yet? Show me the board.
