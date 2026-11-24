---
description: Install a techne plugin, run its setup skill, and run a first skill. One first-run line for each plugin.
---

# Getting Started

Install the plugins you need, check each one's requirements, and run a first skill.

## Prerequisites

[Claude Code](https://code.claude.com/docs) (the CLI, the desktop app, or an IDE extension) runs every plugin. Antigravity CLI, Codex and Copilot CLI run techne, graphe and dokimasia; see [Antigravity CLI](#antigravity-cli) and [Codex and Copilot CLI](#codex-and-copilot-cli). Each plugin's setup skill checks the rest and prints the install command for each tool that is missing.

## 1. Add the marketplace

From inside Claude Code:

```text
/plugin marketplace add ajbarea/techne
```

## 2. Pick your plugin

Install only the plugins you use. Every enabled plugin's skill list sits in the agent's context on every turn.

Install each with `/plugin install <plugin>@techne`, then run its setup.

| You want to | Plugin | Then run | First run |
|---|---|---|---|
| Audit a build, review CI or a change, plan commits, catch up on GitHub | [`techne`](plugins/techne.md) | `/techne:setup` | `/techne:audit` in a repo with a Makefile, or `/techne:catchup` in any GitHub repo |
| Build LaTeX, PDFs or talk decks, scaffold or review a paper | [`graphe`](plugins/graphe.md) | `/graphe:setup` | `/graphe:latex paper/main.tex` |
| Check a bibliography | [`dokimasia`](plugins/dokimasia.md) | needs only uv | `/dokimasia:check` |
| Triage an idea against prior work | [`heuresis`](plugins/heuresis.md) | `/heuresis:setup` | `/heuresis:idea --now <your idea>` |
| Read and draft Gmail across accounts | [`epistole`](plugins/epistole.md) | `/epistole:setup` | `/epistole:catch-me-up` |
| Check a Brightspace course site | [`schole`](plugins/schole.md) | `/schole:setup` | `/schole:courses` |
| Block attribution lines, guard commits, restart on update | [`phylax`](plugins/phylax.md) | switch options on in `/config`, then `/phylax:setup` | `/phylax:setup` shows what is on |
| Hear a gist of each reply (WSL2 only) | [`keryx`](plugins/keryx.md) | `keryx status` | speaks the next reply |

Each plugin's page under [Plugins](plugins/techne.md) lists what it needs, its commands, and its fixes.

<a id="other-agent-clis"></a>
## Antigravity CLI

Antigravity natively converts and installs Claude Code plugins via `agy plugin`:

```bash
# Recommended: install the core techne plugin for code-repo skills
agy plugin install https://github.com/ajbarea/techne/tree/main/plugins/techne

# Or install the entire marketplace at once
agy plugin install https://github.com/ajbarea/techne
```

If you already use Claude Code on this machine, import every plugin installed in `~/.claude` without re-downloading:

```bash
agy plugin import claude
```

Run `agy plugin list` to verify. Skills are discovered automatically and loaded on demand by Antigravity: call a skill by name (e.g. `audit`, `auto-commit`, `dokimasia:check`) or describe the task. Run `python3 ~/.gemini/config/plugins/techne/skills/setup/scripts/doctor.py` to confirm your local tools (`gh`, `uv`, `tmux`) are ready.

## Codex and Copilot CLI

techne, graphe and dokimasia also run in Codex and Copilot CLI. Codex and Copilot CLI read this repo's marketplace:

```bash
codex plugin marketplace add ajbarea/techne
codex plugin add techne@techne

copilot plugin marketplace add ajbarea/techne
copilot plugin install techne@techne
```

Swap `techne` for `graphe` or `dokimasia` to add those, then ask for a skill by name ("use the techne audit skill") or describe the task. graphe's optional OpenAlex and Semantic Scholar keys come from Claude Code's plugin settings; in other CLIs, export `OPENALEX_API_KEY` and `S2_API_KEY` in your shell. techne's opt-in cleanup at session start is a Claude Code hook, and several techne skills (elenchus, seele, docs-site, deslop, reslop, docsync, research-grounded) hand part of their work to Claude Code subagents or `/code-review`; in other CLIs that step depends on what the agent offers. The other plugins rely on Claude Code's hooks, plugin settings or subagents and run there alone for now.

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
