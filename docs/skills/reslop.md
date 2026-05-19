# `techne:reslop`

Rewrite docstrings and comments grounded in the actual implementation, call sites, and tests. Produces factual one-or-two-line descriptions instead of marketing prose or signature restatements.

## When to use

- A docstring is inaccurate, overhyped, or hallucinates behavior the code doesn't have.
- After a major refactor: regenerate docstrings to match the new implementation.
- "Rewrite the docstrings in my pending changes" / "Replace AI-generated docs with what the code actually does."
- When `/techne:deslop` flags a docstring and the answer is better prose, not deletion.

## Usage

Invoke by name in Claude Code:

```
/techne:reslop
```

Default scope is the files the user named, or pending-change files. The skill reads each target's implementation, call sites, and tests, then presents old-to-new diffs and asks `apply all / apply selected / skip?`

## See also

- [`techne:deslop`](deslop.md): identify and delete low-value prose; hand off to reslop when a replacement is needed.
- [`techne:docsync`](docsync.md): verify factual claims in docs after a reslop pass.
- [Conventions](../conventions.md): `## slop_ground_truth` section in `.claude/skill-context.md` for grounding numeric claims.
