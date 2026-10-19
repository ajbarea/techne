---
description: Find decisions in IMPL.md, ROADMAP.md and decision records that lack research provenance, then search the web to ground them.
---

# `techne:research-grounded`

Flag decisions (technology choices, data release and privacy, study design, access-rule readings, public-claim wording) that lack a `# research(YYYY-MM):` provenance comment, then web-search to ground them before they harden into code.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

## When to use

- Before a plan's decisions turn into commits: "are these library / architecture choices grounded in current best practice, or training-cutoff recall?"
- After drafting IMPL.md / ROADMAP.md entries that pick a tool, pattern, or protocol.
- When a decision is stated as fact ("X supports Y") that was never verified against the target's current docs, the class of miss that becomes revertable work.
- Auditing `planning/` design notes for un-cited architectural choices.

## Usage

Invoke by name in Claude Code:

```
/techne:research-grounded
```

Default scope is `IMPL.md` + `ROADMAP.md` in the current repo; a `decision_docs:` key in the `## research_grounded` block of `.claude/skill-context.md` adds research logs, ADRs and specs. Narrow or redirect by naming a file or directory:

```
/techne:research-grounded planning/
```

The skill greps for decision language only as a candidate seed, then reads around each hit to keep the genuine technology / pattern / architecture choices. Descriptive prose ("reads X instead of Y") and hypotheticals ("what if we used…") are filtered out. For each committed decision lacking an adjacent `research(YYYY-MM):` tag, it reports a `decision → gap → action` entry and, on confirmation, web-searches current best practice and adds the provenance tag. It never invents a citation.

## See also

- [`techne:docsync`](docsync.md): verifies documentation claims against the code; this skill is the sibling that verifies design *decisions* against *evidence*.
- [`techne:deslop`](deslop.md): tightens AI-slop prose, a different kind of doc-quality pass.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/research-grounded/SKILL.md) holds the full instructions Claude follows for this skill.
