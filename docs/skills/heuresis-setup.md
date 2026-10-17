---
description: heuresis:setup checks uv, git and gh, the ideas repository and repos folder, and which search API keys are set, and creates the private ideas repository when it does not exist.
---

# `heuresis:setup`

Check heuresis, create the ideas repository, and list which search keys are set.

Part of [heuresis](../plugins/heuresis.md): `/plugin install heuresis@techne`.

## When to use

After installing heuresis, when `/heuresis:idea` says the ideas repository is not set, or when a source shows `skipped` in a verdict.

## Usage

```text
/heuresis:setup
```

The skill runs a doctor script that only reads, then follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/heuresis/AGENTS.md). You set `ideas_repo` and `repos_root` in `/config` under the heuresis plugin's options. When the ideas repository does not exist, Claude creates it with `heuresis init`, makes the first commit, and creates the private GitHub repository only after you say yes and `gh` is signed in. Search keys are saved one of two ways: you run `/plugin configure heuresis@techne` and paste each into its masked field, or Claude prints a template, you fill it in at a private path, and a store script saves it to Claude Code's secure storage, printing names only. Restart Claude Code afterwards. Claude never asks for an API key in chat and never reads the file.

## What it checks

| Check | Meaning |
|---|---|
| `uv`, `git` | Required. |
| `gh` | Optional. GitHub search and the ideas remote. |
| `ideas_repo`, `repos_root` | The two folders set in `/config`. |
| API keys | Optional. One line per key: `S2_API_KEY`, `LENS_API_TOKEN`, `EPO_OPS_KEY` with `EPO_OPS_SECRET`, `OPENALEX_API_KEY`, `OPENALEX_MAILTO` and the GitHub token. Saved in Claude Code's secure storage, or exported in your shell, which wins. A source without its key shows `skipped` in a verdict. |

## Output

Each line starts with `ok`, `missing`, `optional` or `n/a`, then the check's name and a detail. A `missing` or `optional` line is followed by one or more `fix:` lines. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. The doctor exits 0 when nothing required is missing, and only reads.

## See also

- [heuresis plugin](../plugins/heuresis.md): install, needs and troubleshooting.
- [`heuresis:idea`](idea.md): the skill this prepares.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/heuresis/skills/setup/SKILL.md) holds the full instructions Claude follows for this skill.
