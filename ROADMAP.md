# techne — Roadmap

Long-horizon plan for the techne plugin. Session-by-session execution
lives in [IMPL.md](./IMPL.md). When a milestone ships, it collapses to a
dated one-liner under [Shipped](#shipped). Historical design specs and
plans archived under [`superpowers/plans/`](./superpowers/plans/) and
[`superpowers/specs/`](./superpowers/specs/).

Last reviewed: 2026-05-23.

---

## Why this file exists

techne is a meta-sister — it ships the canonical skills that audit every
other repo in `~/.claude/techne.toml`. ROADMAP/IMPL exist here for
convention parity with the rest of the sister fleet; the meta nature
means most planning is **cross-skill** (vocabularies, conventions,
dogfood gates) rather than per-skill feature work.

---

## Active themes

### Sister-toolchain parity

Every consumer sister carries the canonical Makefile vocabulary
(`make setup` / `make lint` / `make test` / `make validate` / `make ci`),
the canonical `.claude/skill-context.md` layout, and the canonical
`scripts/dev-runner.sh` wrapper for archived runs. techne itself
dogfoods the same shape (see [#14](https://github.com/ajbarea/techne/pull/14)).
Drift between the template (`templates/Makefile.example`) and the live
sisters surfaces through `/techne:sisters` — when a sister forks ahead
of the template, the template catches up the same session.

### Audit coverage

The audit family (`/techne:audit`, `/techne:ci-audit`) has dependency-
ordered `make` targets, log-archive reconciliation, and stop-early
gating. Open coverage gaps:

- **Sister-graduation final gates.** `/techne:sisters` should detect
  unchecked M6-equivalent boxes in a sister's ROADMAP — today the
  audit only inspects infra parity, not the planning-doc handoff
  state. Tracked alongside the [`narrative-coherence` sketch](./superpowers/plans/2026-05-21-skill-ideas-from-audit-of-audit.md).
- **Workspace orphan detection.** A directory in `~/ajsoftworks/`
  that isn't in `~/.claude/techne.toml` may be a stale artifact or a
  pre-promotion sister; surfacing the difference would let the
  workspace stay tidy without manual sweeps. Sketched under #4 in
  the same plans file; n=1 today so not a build.

### Skill-collection evolution

Skills are added when a pattern proves itself across multiple sisters
(n≥2). Skills are deleted or merged when their domain collapses into a
larger sibling. The current set (9 skills, 4 catalog dimensions —
audit, drift, hygiene, observation) is stable; the next addition will
likely be `narrative-coherence` or `positioning` once the
2026-05-21 audit-of-audit drift class shows up a second time in the
wild.

---

## Queued / unprioritized

- **`/techne:narrative-coherence`** — cross-sister README ecosystem
  audit. See [skill-ideas-from-audit-of-audit](./superpowers/plans/2026-05-21-skill-ideas-from-audit-of-audit.md) item #2.
- **`/techne:positioning`** — identity-drift check (claim vs work).
  Same plans file, item #1.
- **`/techne:research-grounded`** — flag IMPL/ROADMAP design choices
  missing `# research(YYYY-MM):` provenance. Same plans file, item #3.
- **`/techne:workspace-orphans`** — content-bearing files outside the
  active sister perimeter. Same plans file, item #4. n=1 today;
  build when n≥2.

---

## Cross-cutting invariants

- **No `aj-*` skill names anywhere.** The plugin family was renamed
  to `techne:*` in 2026-05; the `## guards` make target hard-fails
  on any re-introduction. Same rule blocks references to the
  deprecated `.claude/skills/_shared` path.
- **Skill SKILL.md frontmatter is canon.** `name:` and `description:`
  in every `plugins/techne/skills/*/SKILL.md` is the source of truth
  surfaced in the marketplace registry. `validate_skill_frontmatter.py`
  enforces well-formedness; README + `docs/skills/*.md` cross-references
  must match.
- **Self-host the audits.** techne runs `/techne:audit`,
  `/techne:sisters`, `/techne:docsync`, `/techne:docs-site` against its
  own working tree — same way every other sister runs them. The
  meta-repo caveat is documented in `.claude/skill-context.md` under
  `## meta_repo_caveat`.
- **Web-search before convention changes.** May 2026 Claude Code skill
  conventions shift week-to-week. Before renaming a skill, restructuring
  the marketplace manifest, or changing the SKILL.md frontmatter shape,
  verify against [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)
  and Anthropic's current marketplace docs.

---

## Shipped

One-liner per item, newest first. Detail moves to git history when work lands.

- 2026-05-23 — **Sisters audit: `allow_auto_merge` drift detection** —
  canonical merge-settings pin extended; 5/6 sisters auto-fixed
  out-of-band [#17]
- 2026-05-23 — **Makefile + CI drop system jq/shellcheck deps**: `make`
  targets and `validate.yml` no longer require apt installs; CI dogfoods
  `make setup` / `make lint` / `make shellcheck` / `make test` [#16]
- 2026-05-22 — **Makefile dogfood** + `check_theoros_skill.sh` wired
  into `make frontmatter` + `check-env` install hints [#14]
- 2026-05-22 — **Makefile template** (`templates/Makefile.example`) +
  canonical 13-target vocabulary + self-documenting help pattern in
  `docs/conventions.md` [#12, hotfixed #13]
- 2026-05-21 — **README "Sister ecosystem" block** + reciprocal blocks
  added to every consumer sister
- 2026-05-21 — **Stale-assumption audit** documented as a maintenance
  invariant under `docs/architecture.md`
- 2026-05-21 — **Skill ideas from audit-of-audit** filed under
  `superpowers/plans/` [#11]
- 2026-05-21 — **Required-section labels** dropped the deprecated
  parenthetical skill-name prefix in `.claude/skill-context.md` [#10]
- 2026-05-20 — **Sister-toolchain parity**: shellcheck + ruff added,
  validator extracted into `scripts/` for sister-shaped reuse [#9]
- 2026-05-20 — **`.claude/skill-context.md`** added — closed the last
  meta-repo gap from the sister audit [#8]
- 2026-05-19 — **Marketplace prep**: slop cleanup + generalization +
  Conventions guide for plugin publication [#7]
- 2026-05-18 — **Zensical docs site** bootstrap with GitHub Pages
  deploy + theoros skill landing [#1, #2]
- 2026-05-02 — **Initial release** of the techne plugin to the
  marketplace
