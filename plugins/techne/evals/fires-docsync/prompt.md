---
max_turns: 6
timeout_seconds: 240
runs: 3
allowed_tools: [Read, Glob, Grep, Skill]
plugins: ["../../eval-fixtures/with-rivals"]
tags: [routing]
---

Check whether README.md still matches the code. I think the documented commands drifted.
