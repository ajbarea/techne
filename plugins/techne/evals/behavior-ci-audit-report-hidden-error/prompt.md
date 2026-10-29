---
max_turns: 15
timeout_seconds: 300
runs: 2
allowed_tools: [Read, Glob, Grep, Skill]
---

Run ci-audit in report mode on the recorded GitHub Actions run in ./run (its facts.json is already computed). Fix nothing. Reply with the report JSON.
