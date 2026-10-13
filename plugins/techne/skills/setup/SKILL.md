---
name: setup
description: Check and set up what the techne code-repo skills need on this machine: git, the GitHub CLI (gh) and its sign-in, uv, python3 3.11 or newer, tmux, Playwright's Chromium, plus the repo's .claude/skill-context.md and ~/.claude/techne.toml. Use after installing techne, when a techne skill says gh, tmux, a sign-in or a config file is missing, or when asked whether techne is ready to use on this machine. Prints each check with its exact install command and installs nothing itself. Not for running a repo's own build or lint (techne:audit).
---

# Set up techne

Read `${CLAUDE_PLUGIN_ROOT}/AGENTS.md` and follow it. It is the setup runbook, and it starts by running this doctor:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/scripts/doctor.py"
```

The plugin root is `${CLAUDE_PLUGIN_ROOT}`. The skill-context skeleton is `${CLAUDE_PLUGIN_ROOT}/skills/setup/skill-context.template.md`.
