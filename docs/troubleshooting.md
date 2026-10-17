---
description: Common questions and fixes for techne skills and plugins, including a skill that is not recognized, a missing tool or sign-in, odd output, and sister repo configuration.
---

# Troubleshooting

Answers to common questions, then fixes for the problems people hit most. Each plugin's page under [Plugins](plugins/techne.md) has its own fixes.

## Common questions

**Can I use only one skill?**
Yes. Each skill is independent. You can use `audit` without `ci-audit`, or `docsync` without any others.

**What if a skill wants to change my code and I disagree?**
Skills that edit show a plan or diff first. Review it, edit by hand if needed, and approve before execution.

**Can I customize skill behavior?**
Yes. Use `.claude/skill-context.md` for per-repo overrides and `~/.claude/techne.toml` for multi-repo config. See [Configuration](configuration.md) and [Conventions](conventions.md).

**Does techne change my git history?**
Only if you approve. `auto-commit` branches, commits, pushes and opens a PR only after you say "go" on its plan. `audit` and `catchup` are read-only, and `sisters` is read-only in report mode; its clean mode removes finished branches and worktrees only after you approve the list. `docsync` and `ci-audit` edit files but leave committing to you.

**What is the difference between `deslop` and `reslop`?**
`deslop` finds and trims AI filler (verbose, redundant prose). `reslop` rewrites docstrings from the actual code. Use `deslop` for triage and `reslop` when you want replacement prose, not deletion. See [Examples](examples.md#pre-release-documentation-audit).

**How do I debug a skill?**
The skills are prompt-driven, not CLI tools with flags; steer them in natural language. Ask Claude to explain what a skill is doing, or tell it what looked wrong and rerun. If one gets stuck, cancel and try a different approach.

## Fixes

**`/techne:audit` is not recognized**

- Run `/plugin install techne@techne` inside Claude Code (`graphe@techne` for the document skills).
- Run `/reload-plugins`, then `/skills` to confirm the `techne:*` skills are listed.
- To pick up a newer techne, run `/plugin install techne@techne` again, or enable auto-update for the marketplace in `/plugin`.

**A tool or sign-in is missing**

- Run the plugin's setup skill. Each plugin's page under Plugins lists its fixes.

**A skill runs but the output looks wrong**

- Rerun it and tell Claude what looked off. There are no `--verbose` or `--debug` flags.
- Check `.claude/skill-context.md` for overrides that change behavior.
- Ask Claude to explain what the skill is doing.

**Sister repo config is not working**

- Verify `~/.claude/techne.toml` exists and is readable.
- Check that the repo names match your actual directories.
- Ask `techne:sisters` which repos it detected from the config.
