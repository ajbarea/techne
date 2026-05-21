# Skill ideas surfaced by the 2026-05-21 audit-of-audit

Context: AJ ran a Copilot ecosystem audit against the five active sisters
in 2026-05; on 2026-05-21 we did an audit-of-an-audit, evaluating every
Copilot recommendation against current sister state + 2026-05 web-search
best practice. The source folder was deleted after extraction; everything
actionable migrated to per-sister ROADMAPs. This file captures the
**techne-skill-shaped catches** that Copilot surfaced which the existing
`techne:audit` and `techne:ci-audit` skills would not have caught. None
are urgent. All four are sketches, not specs.

## 1. `techne:positioning` — identity-drift check

**What it would do.** Read each sister's README hero, ROADMAP top, and
recent commit messages, then draft a one-line "what does this project
claim to be?" per sister. Flag where the claim drifts from the work
actually being done.

**Different from existing skills.** `techne:docsync` checks claims
against code (CLI commands, file paths, config keys, signatures);
this would check **identity drift** — "Kourai used to be a CLI dev
tool, now it's a VN-first dev game; does the README hero still say
the old thing?" Goes after marketing-shape drift, not technical-claim
drift.

**Why it's worth building.** Self-positioning drift is the slowest
form of drift — it doesn't break tests, doesn't trip CI, doesn't
fail an audit. Only catches it: an outsider reading the README cold.
Techne is positioned to be that outsider on demand.

## 2. `techne:narrative-coherence` — cross-sister story audit

**What it would do.** Given the active sister list in `~/.claude/techne.toml`,
read each sister's README and check whether the sisters cross-reference each
other and present a coherent ecosystem story. Surface gaps where reciprocal
links are missing or where one sister names the ecosystem but others don't.

**Different from `techne:sisters`.** `techne:sisters` checks
dev-infra coherence (action pins, toolchain pins, skill-context
parity, branch protection, open PRs, branch hygiene). This would
check **narrative coherence** at the README + ecosystem-block layer.

**Why it's worth building.** The 2026-05-21 audit found this gap
concretely: every sister has dev-infra coherence but none of them
link to each other narratively. The LDQIS lab page (dataqualitylabs.com)
already tells the ecosystem story; the sisters do not. A skill could
make this catchable continuously, not just in ad-hoc audits.

## 3. `techne:research-grounded` — research-comment provenance check

**What it would do.** Scan IMPL.md and ROADMAP.md for design decisions
about libraries, patterns, or architectural choices, then flag where
those decisions lack a `# research(YYYY-MM):` provenance comment
(per the convention captured in `feedback_research_comment_convention`).

**Pattern lives.** Phalanx-FL already uses `# research:` for paper
citations in code; AJ has converged on the same pattern for design
choices in `# research(YYYY-MM): <tradeoff> <source>` form. This
skill would mechanize the convention.

**Why it's worth building.** When SSML investment in Kourai turned
out to be 5 PRs of revertable work because the planning step didn't
verify against the actual M6 target (ElevenLabs v3 doesn't support
SSML break tags), the failure was a missing research check at the
planning step. A skill that flags un-grounded decisions before they
become commitments closes that loop.

## 4. `techne:workspace-orphans` — content-bearing files outside the sister perimeter

**What it would do.** Scan `~/ajsoftworks/*` for content-bearing
files or subdirectories that aren't listed as active sisters in
`techne.toml`, flag any that look stale or content-light enough to
need attention.

**Why it's worth building.** During the 2026-05-21 audit-of-audit I
escalated `DQL/dql.html` as "the single highest-value catch" before
reading the file — Copilot had described it as a 1.2KB minimal HTML
file that needed expanding. The actual file was a 1247-line paper-grade
lab landing page with all the content Copilot wanted to add already
present. Copilot worked from a stale snapshot; my error was trusting
the snapshot before verifying. A skill that scans workspace orphans
periodically would have surfaced "DQL is in the workspace, not in
techne.toml, when was it last touched" automatically — and would have
prevented the embarrassing first-pass verdict.

Today DQL is the only such orphan; the skill is overkill for n=1. If
more accumulate, the skill is worth filing.

## When to pick these up

None are urgent. The pattern is: when a sister-audit reveals a class
of drift the existing skills don't catch, the new-skill candidate
gets surfaced. Build only when the second instance of the same class
appears, not the first — n=1 is a one-off, n=2 is a pattern.

## Provenance

These four sketches were surfaced during the 2026-05-21 audit-of-audits
review and extracted here as the durable home before the audit folder
was deleted.
