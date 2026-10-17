---
description: Install a techne plugin, run its setup skill, and run a first skill. One first-run line for each plugin.
---

# Getting Started

Install the plugins you need, check each one's requirements, and run a first skill.

## Prerequisites

[Claude Code](https://code.claude.com/docs): the CLI, the desktop app, or an IDE extension. Each plugin's setup skill checks the rest and prints the install command for each tool that is missing.

## 1. Add the marketplace

From inside Claude Code:

```text
/plugin marketplace add ajbarea/techne
```

## 2. Pick your plugin

Install only the plugins you use. Every enabled plugin's skill list sits in Claude's context on every turn.

| You want to | Install | Then run | First run |
|---|---|---|---|
| Audit a build, review CI or a change, plan commits, catch up on GitHub | `/plugin install techne@techne` | `/techne:setup` | `/techne:audit` in a repo with a Makefile, or `/techne:catchup` in any GitHub repo |
| Build LaTeX, PDFs or talk decks, scaffold or review a paper | `/plugin install graphe@techne` | `/graphe:setup` | `/graphe:latex paper/main.tex` |
| Check a bibliography | `/plugin install dokimasia@techne` | needs only uv | `/dokimasia:check` |
| Triage an idea against prior work | `/plugin install heuresis@techne` | `/heuresis:setup` | `/heuresis:idea --now <your idea>` |
| Read and draft Gmail across accounts | `/plugin install epistole@techne` | `/epistole:setup` | `/epistole:catch-me-up` |
| Check a Brightspace course site | `/plugin install schole@techne` | `/schole:setup` | `/schole:courses` |
| Block attribution lines, guard commits, restart on update | `/plugin install phylax@techne` | switch options on in `/config`, then `/phylax:setup` | `/phylax:setup` shows what is on |
| Hear a gist of each reply (WSL2 only) | `/plugin install keryx@techne` | `keryx status` | speaks the next reply |

Each plugin's page under [Plugins](plugins/techne.md) lists what it needs, its commands, and its fixes.

## 3. Set up

Run the setup skill for each plugin you installed. It checks what the plugin needs on this machine and prints the exact install command for anything missing. The doctors only read. Run a `fix:` line yourself when it contains `sudo`, and after `!` in Claude Code.

Confirm the skills loaded:

```text
/skills
```

The skills of the plugins you installed should be listed. If they are not, run `/reload-plugins` and check again. To pick up a newer techne, run `/plugin install techne@techne` again, or enable auto-update for the marketplace in `/plugin`.

## 4. First run: validate a build

Pick `techne:audit` and run it in a repo that has the [Makefile pattern](conventions.md#the-makefile-pattern):

```text
/techne:audit
```

It runs the phases your `.claude/skill-context.md` lists, then prints one table row per command (terminal exit code, archive `SUMMARY` rc, steps, elapsed) and a one-line verdict such as `Full audit clean.` A failing row names the archive to open.

Skills that change files show you the plan, report or diff before making changes. Review it, then say "go" or "apply" to execute it, or ask for changes.

Once one skill is familiar, combine them:

```text
/techne:audit
/techne:auto-commit
/techne:ci-audit
/techne:deslop src/
```

[Examples](examples.md) walks through real workflows.

## Next steps

- [Skills](skills/index.md): what each skill does, grouped by job.
- [Configuration](configuration.md): `~/.claude/techne.toml` and phylax options.
- [Conventions](conventions.md): the files each techne skill assumes.
- [Troubleshooting](troubleshooting.md): common questions and fixes.
- [Architecture](architecture.md): how the skills fit together.
