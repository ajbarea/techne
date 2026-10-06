---
max_turns: 6
timeout_seconds: 240
runs: 3
allowed_tools: [Read, Glob, Grep, Skill]
plugins: ["../../eval-fixtures/with-rivals"]
tags: [routing, collision]
---

In deck.pptx, change the title on slide 3 to "Results".
