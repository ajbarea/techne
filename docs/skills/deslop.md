# `techne:deslop`

Scan comments and docstrings for AI-generated low-value prose and propose tightened rewrites or deletions. Keeps why-comments and non-obvious references; cuts everything else.

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

The skill fans out parallel subagents per area, consolidates findings, then asks `apply all / apply selected / skip?` before editing.

## See also

- [`techne:reslop`](reslop.md): when the answer is better prose, not less prose.
- [`techne:docsync`](docsync.md): verify factual claims in docs after a deslop pass.
- [Conventions](../conventions.md): `## scan_scope` section in `.claude/skill-context.md` for repo-specific skip paths.
