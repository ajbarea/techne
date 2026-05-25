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
the canonical `.claude/skill-context.md` layout, the canonical
`scripts/dev-runner.sh` wrapper for archived runs, and the canonical
`.github/dependabot.yml` (template: `templates/dependabot.yml.example`).
techne itself
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
- **GitHub Actions SHA-pinning hardening** — pin actions to full commit
  SHAs (immutable) over version tags fleet-wide; the
  tj-actions/changed-files compromise (2025-03, ~23k repos, CI-secret
  exfiltration via rewritten tags) is the cautionary case. Deferred, not
  skipped: tag pins keep Dependabot security alerts working, and
  SHA-pinning is a deliberate per-workflow sweep rather than a config
  toggle; Dependabot keeps SHA pins fresh once adopted.
  research(2026-05): github.blog/changelog/2025-08-15 (policy enforcement
  + immutable releases).
- **Renovate revisit trigger** — if the fleet consolidates into a
  monorepo or wants cross-repo shared presets + auto-merge, re-evaluate
  Renovate (shared `extends` preset). Also re-enable the `uv` ecosystem
  on kourai once dependabot-core#14004 (workspace mis-targeting) closes.
- **uv toolchain-floor churn** — Dependabot's uv ecosystem bumps pyproject
  floors (not just uv.lock), and `versioning-strategy: lockfile-only` isn't
  supported for uv yet (dependabot-core#12162, open as of 2026-05). So
  ruff/ty floors drift across sisters unevenly as releases land — caught and
  re-aligned via `/techne:sisters` check 7 (e.g. 2026-05-25). When #12162
  lands, add `versioning-strategy: lockfile-only` to the uv entries (template
  + repos) to stop the churn; Renovate's `update-lockfile` rangeStrategy
  already does this if the fleet ever moves there.

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

Detail lives in git history (`git log`) and the live skill code. This log is pruned once work is durably shipped.
