---
name: setup
description: Check and set up phylax, the opt-in Claude Code hooks that block attribution lines in commits and PRs, block staging COMMITS.md, warn on main-checkout commits, refuse subagent calls that would silently inherit the session's model, and restart idle sessions onto an updated Claude Code. Shows which options are on and checks what each needs: the Claude Code version for the guard mod, python3, git, and for restart_on_update tmux or Windows Terminal and its state folder. Use after installing phylax, when a guard or a restart does not seem to fire, or when asked how to switch phylax's options on.
---

# Set up phylax

Read `${CLAUDE_PLUGIN_ROOT}/AGENTS.md` and follow it. It starts by running this doctor, which receives each option's current value:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/scripts/doctor.py" \
  'block_attribution_trailers=${user_config.block_attribution_trailers}' \
  'block_commits_md=${user_config.block_commits_md}' \
  'warn_main_checkout_commit=${user_config.warn_main_checkout_commit}' \
  'require_subagent_model=${user_config.require_subagent_model}' \
  'restart_on_update=${user_config.restart_on_update}'
```
