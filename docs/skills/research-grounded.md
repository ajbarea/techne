# `techne:research-grounded`

Flag design decisions in a plan (library, framework, pattern, and architecture choices) that lack a `# research(YYYY-MM):` provenance comment, then web-search to ground them before they harden into code.

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

Default scope is `IMPL.md` + `ROADMAP.md` in the current repo. Narrow or redirect by naming a file or directory:

```
/techne:research-grounded planning/
```

The skill greps for decision language only as a candidate seed, then reads around each hit to keep the genuine technology / pattern / architecture choices. Descriptive prose ("reads X instead of Y") and hypotheticals ("what if we used…") are filtered out. For each committed decision lacking an adjacent `research(YYYY-MM):` tag, it reports a `decision → gap → action` entry and, on confirmation, web-searches current best practice and adds the provenance tag. It never invents a citation.

## See also

- [`techne:docsync`](docsync.md): verifies documentation claims against the code; this skill is the sibling that verifies design *decisions* against *evidence*.
- [`techne:deslop`](deslop.md): tightens AI-slop prose, a different kind of doc-quality pass.
