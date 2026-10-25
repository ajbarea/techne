---
description: "phylax:budget pauses budget mode for opted-in interactive sessions (off, for 4 hours by default), ends the pause (on), or shows any pause and whether this session is routed by budget mode (status)."
---

# `phylax:budget`

Pause or resume budget mode for interactive sessions, or show where it stands.

Part of [phylax](../plugins/phylax.md): `/plugin install phylax@techne`, then switch `budget_mode` on in `/config`.

## When to use

Before a session that should spend on purpose, or to see what budget mode is doing to this one. See [Budget mode](../configuration.md#budget-mode) for the levels and who they apply to.

| Command | What it does |
|---|---|
| `/phylax:budget off [hours]` | Puts every interactive session that opted in (`PHYLAX_BUDGET=on`) on normal routing until the pause ends: 4 hours by default, at most 168. Background agents keep reading the level. |
| `/phylax:budget on` | Ends the pause now. |
| `/phylax:budget status` | Shows any pause and whether this session is routed by budget mode. |

The pause is a file, `phylax-budget-override.json`, in the account's Claude config folder, so it covers one account. `/phylax:setup` shows the current level and the file it read.

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/phylax/skills/budget/SKILL.md) holds the full instructions Claude follows for this skill.
