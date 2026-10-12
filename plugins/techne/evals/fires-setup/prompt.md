---
max_turns: 6
timeout_seconds: 240
runs: 3
allowed_tools: [Read, Glob, Grep, Skill]
plugins: ["../../eval-fixtures/with-rivals"]
tags: [routing]
---

I just installed the techne plugin on a new laptop. Check whether this machine has everything its skills need, like gh, uv and tmux, and tell me what to install.
