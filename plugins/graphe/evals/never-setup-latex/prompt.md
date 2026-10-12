---
max_turns: 6
timeout_seconds: 240
runs: 3
allowed_tools: [Read, Glob, Grep, Skill]
plugins: ["../../eval-fixtures/with-rivals"]
tags: [routing, collision]
---

Build paper/main.tex and tell me whether the PDF is ready to submit.
