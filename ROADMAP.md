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
larger sibling. The current set (10 skills, 4 catalog dimensions —
audit, drift, hygiene, observation) is stable. `research-grounded`
(the 2026-05-21 audit-of-audit item #3) shipped 2026-05-29 on direct
request; `narrative-coherence` / `positioning` (items #2 / #1) remain
queued for when that drift class recurs.

---

## Queued / unprioritized

- **`/techne:narrative-coherence`** — cross-sister README ecosystem
  audit. See [skill-ideas-from-audit-of-audit](./superpowers/plans/2026-05-21-skill-ideas-from-audit-of-audit.md) item #2.
- **`/techne:positioning`** — identity-drift check (claim vs work).
  Same plans file, item #1.
- **`/techne:workspace-orphans`** — content-bearing files outside the
  active sister perimeter. Same plans file, item #4. n=1 today;
  build when n≥2.
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
- **Validation stays extracted + linted.** `scripts/validate_skill_frontmatter.py` is the
  real frontmatter validator (extracted from an inline-YAML heredoc in `validate.yml`,
  2026-05-20 PR #9) — do NOT re-inline it. `scripts/*.sh` run through `shellcheck
  --severity=warning`, `scripts/*.py` through ruff; techne carries the same sister-toolchain
  lint/test discipline it audits elsewhere.

---

## Shipped

Detail lives in git history (`git log`) and the live skill code. This log is pruned once work is durably shipped.

- 2026-05-29 — **`/techne:research-grounded` skill.** Audits IMPL.md / ROADMAP.md for committed
  design decisions (library / framework / pattern / architecture choices) that lack a
  `# research(YYYY-MM):` provenance tag, then web-searches to ground them — closing the loop
  that, skipped, turned an SSML capability bet into 5 revertable PRs. Judgment over grep:
  descriptive "instead of" prose and hypotheticals are filtered out. Validated on kourai
  (8/10 grep candidates correctly ignored, 2 genuine gaps surfaced). Sibling of `/techne:docsync`.
- 2026-05-27 — **docsync cross-repo skill-context fix.** `/techne:docsync` audits a doc
  that may live in a different repo than CWD (e.g. `docsync ../velocity-fl/README.md`), but
  it loaded `.claude/skill-context.md` via a load-time `` !`cat …` `` injection that always
  reads CWD — so cross-repo runs verified claims against the *wrong* repo's context (the
  workaround was `cd` into the target first). Replaced the injection with an explicit,
  argument-aware `Read`: resolve the target repo root from the doc-path arg
  (`git -C "$(dirname <doc>)" rev-parse --show-toplevel`) then read that repo's
  skill-context. Correct for file / dir / no-arg (CWD) inputs and independent of injection
  ordering. The 6 CWD-bound siblings (audit, ci-audit, theoros, docs-site, deslop, reslop)
  keep the `` !`` `` block — they run *in* the repo, so CWD is the target; docsync is the only
  path-argument skill, so its divergence is intentional. research(2026-05):
  [code.claude.com/docs slash-commands](https://code.claude.com/docs/en/slash-commands) —
  args are 0-based (`$0` = first), `!`cmd`` injection runs *before* the model sees content;
  whether an arg interpolates *into* an injection block is undocumented, so the fix avoids
  depending on it rather than betting on an unverified mechanic.

- 2026-05-26 — **zizmor GHA static analysis (techne dogfood).** Adopted
  [zizmor](https://github.com/zizmorcore/zizmor) as a dev dep + `make zizmor`
  target, wired into `make validate` and the validate.yml gate — extending the
  GHA-security layer beyond `check_action_pins.sh` (pinning-only) to zizmor's
  security audits (template injection, excessive-permissions, artipacked,
  unpinned-uses, …). Fixed what it surfaced in techne's own workflows:
  least-privilege per-job permissions on docs.yml (`pages: write` + `id-token:
  write` moved off the workflow level onto the deploy job only — build needs
  just `contents: read`, since `configure-pages` defaults to `enablement: false`
  and Pages is already enabled), plus `persist-credentials: false` on every
  checkout (artipacked). research(2026-05): Trail of Bits "We hardened zizmor"
  (2026-05-22); zizmor audit docs; zizmor + actionlint are complementary
  (security vs correctness). Remaining: propagate to the sisters — every FL/docs
  sister carries the same docs.yml workflow-level permission over-grant +
  artipacked, each needing its findings triaged (separate PRs). actionlint and
  zizmor SARIF→code-scanning upload are later enhancements.

- 2026-05-25 — **GitHub Actions SHA-pinning (fleet hardening).** Reversed the prior
  deferral after re-checking May-2026 best practice. Every workflow `uses:` ref is
  pinned to a full commit SHA (`# vX.Y.Z` comment preserved), enforced by `make
  guards` → `scripts/check_action_pins.sh`, documented in docs/conventions.md. The
  deferral's premise ("tag pins keep Dependabot security alerts working") was the
  wrong tradeoff: GitHub emits actions alerts only for semver pins, but the dominant
  threat is tag *mutation* (tj-actions/changed-files, 2025-03) — alerts can't catch
  it, SHA-pinning prevents it. Freshness stays via the existing Dependabot *version*
  updates (GitHub's recommended companion), now with a 7-day `cooldown`. Generated
  via the authenticated `gh api` (resolves annotated tags → commit; no third-party
  binary). research(2026-05): GitHub Docs "Secure use reference"; CNCF "Securing
  GitHub Actions CI dependencies" recipe (2026-05-04); StepSecurity pinning guide.
  All 5 follow-on pin PRs merged; `cooldown` (`default-days: 7`) now covers every
  Dependabot ecosystem fleet-wide. Remaining: propagate the `check_action_pins.sh`
  guard to the other sisters (only techne enforces it today).
