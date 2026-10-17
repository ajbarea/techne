---
name: setup
description: Check and set up heuresis, the idea triage plugin. Checks uv, git and gh, the ideas repository and repos folder set in /config, and which search API keys are present (OpenAlex, Semantic Scholar, Lens, EPO), and creates the private ideas repository when it does not exist. Use after installing heuresis, when /heuresis:idea says the ideas repository is not set, or when a source shows skipped in a verdict.
---

# Set up heuresis

Read `${CLAUDE_PLUGIN_ROOT}/AGENTS.md` and follow it. The ideas repository is `${user_config.ideas_repo}` and the repos folder is `${user_config.repos_root}`; either may be empty.

The runbook starts by running this doctor:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/scripts/doctor.py" 'IDEAS_REPO=${user_config.ideas_repo}' 'REPOS_ROOT=${user_config.repos_root}'
```

The runbook's "heuresis command" is:

```bash
env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis
```

The runbook's "store command" is:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/scripts/store_keys.py"
```

It takes `--template` or the path of a filled-in file.
