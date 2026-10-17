---
description: Scan comments and docstrings for AI-generated filler and propose tighter rewrites.
---

# `techne:deslop`

Scan comments and docstrings for AI-generated low-value prose and propose tightened rewrites or deletions. Keeps why-comments and non-obvious references; cuts everything else.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

## When to use

- After other AI assistants have touched a repo and left behind verbose, self-narrating commentary.
- Pre-release audit: "Clean up the codebase before we ship."
- Auditing pending changes for temporal markers, marketing padding, or narrative WHAT-comments.
- Anytime a comment or docstring makes you wince.

## Usage

Invoke by name in Claude Code:

```
/techne:deslop
```

Default scope is the whole repo minus vendored/generated paths. Narrow scope by naming a path:

```
/techne:deslop scripts/
```

For a wide scope the skill fans out parallel subagents per area (a single file or small directory is scanned inline), consolidates findings, then asks `apply all / apply selected / skip?` before editing. Pass `--apply` to edit without asking.

Files that quote slop on purpose, such as a style glossary or the tests that feed a prose checker, go under `pattern_sources` in the `## scan_scope` section; the glossary grep skips them and the report says how many it left out.

## See also

- [`techne:reslop`](reslop.md): when the answer is better prose, not less prose.
- [`techne:docsync`](docsync.md): verify factual claims in docs after a deslop pass.
- [Conventions](../conventions.md#section-reference): `## scan_scope` section in `.claude/skill-context.md` for repo-specific skip paths.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/deslop/SKILL.md) holds the full instructions Claude follows for this skill.
