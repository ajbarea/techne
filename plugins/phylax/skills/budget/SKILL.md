---
name: budget
description: Pause or resume phylax budget mode for interactive sessions that opted in, or show where it stands. "off [hours]" keeps them on normal routing until the pause ends (4 hours by default, at most 168), "on" ends the pause early, and "status" shows any pause and whether this session is routed by budget mode. Background agents keep paying while a pause runs. Use when the user starts a deliberately heavy session, asks to stop or resume budget routing, or asks what budget mode is doing to this session.
---

# Pause or resume budget mode

`<plugin-root>` is the plugin's root directory, two levels above the directory holding this SKILL.md.

Run the command with the user's argument: `off`, `off <hours>`, `on` or `status` (no argument means `status`).

```bash
python3 "<plugin-root>/hooks/budget.py" status
```

Report the printed line as it stands. A pause applies to every interactive session that opted in with `PHYLAX_BUDGET=on` on this account; background agents (`PHYLAX_BUDGET_ROLE=background`) keep reading the level, so they absorb a heavy session's burn. An interactive session that did not opt in already keeps normal routing. For the current level and the usage file it reads, run `/phylax:setup`.
