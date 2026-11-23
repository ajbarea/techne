# techne — Roadmap

Long-horizon plan for the techne marketplace and its plugins, forward only. Session-by-session
execution lives in [IMPL.md](./IMPL.md). When a milestone ships, its block is deleted: merged PRs,
closed issues and `git log` are the record, and what it taught becomes a lesson, a rule below or
an issue. `make guards` runs the cleanup check that holds this.

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
  state. Tracked alongside `narrative-coherence` below.
- **Workspace orphan detection.** A directory in `~/ajsoftworks/`
  that isn't in `~/.claude/techne.toml` may be a stale artifact or a
  pre-promotion sister; surfacing the difference would let the
  workspace stay tidy without manual sweeps. n=1 today, so not a
  build.

### Skill-collection evolution

Skills are added when a pattern proves itself across multiple sisters
(n≥2). Skills are deleted or merged when their domain collapses into a
larger sibling. The current set spans eleven catalog dimensions (audit,
drift, hygiene, review, observation, setup, document build, bibliography, ideas, mail, hooks); IMPL.md maps
each skill or hook to one. `research-grounded`
(from the 2026-05-21 audit-of-audit) shipped 2026-05-29 on direct
request; `narrative-coherence` and `positioning` remain queued for when
that drift class recurs.

---

## Queued / unprioritized

- **Portability, next phases** (phase 1 shipped 2026-10-18).
  2. **Plugin settings and data outside Claude Code.** `${user_config.*}` and
     `${CLAUDE_PLUGIN_DATA}` hold heuresis's and phylax's setup and heuresis's runtime; give them a
     neutral config file and data folder that Claude Code's settings still fill, then drop the
     guard's exemption.
  3. **Hooks and subagents per CLI.** phylax's guards, keryx, the key hooks, techne's session-start
     cleanup and heuresis's four scouts. Codex sets `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` for hooks;
     Antigravity CLI converts Claude hooks on install. Measure each before claiming it.
  4. **OpenCode and other skill-folder agents.** They read `~/.agents/skills/` and have no plugin
     marketplace. A flat bundle needs unique names (six plugins each have `setup`) and each skill's
     `_shared` files beside it.
- **Sandboxed tests in CI** (#172). `make test-sandboxed` runs locally on WSL2. GitHub's ubuntu-24.04
  runners restrict unprivileged user namespaces through AppArmor, so bwrap needs a profile there;
  measure one runner before adding the job, and pin srt the same way the Makefile does. Next hardening
  step: deny `~` and allow back only what the tests need.
- **epistole: reach drafts it did not create.** `search in:drafts` returns message ids, but
  `update_draft` and `send_draft` take the Gmail draft id (`r…`), and no tool lists drafts, so a
  draft made in Gmail or by another session cannot be edited or sent. Fix: a read-only
  `list_drafts` tool that returns each draft's id, message id, recipients, subject and
  attachments, or let `update_draft`/`send_draft` accept a message id and resolve it through
  `drafts.list`; a test for each path. Hit 2026-10-17; the workaround called
  `users().drafts().list(q=…)` through epistole's own client.
- **heuresis phases 3 to 6** (spec: `specs/2026-10-15-heuresis-design.md`, "Build order"). Each
  phase gets its own implementation plan.
  - **Evaluation follow-ups.** A verified-novel `candidate` case, so the set again checks that a
    new idea can reach `do`; an LLM judge for verdict reasons and behaviour evals; refuse an
    `--out` inside another repository's `.git`; count an edited idea text as a stale label; let
    `--cases` override a recorded cases file that still exists; let the guard tell a real capture
    from a leak (it stops the run on any change to the real ideas repository, so a capture made
    during a run stops it too).
  3. **Queue.** `queue.jsonl`, checkpoints, budget reading from klepsydra, a systemd timer, and
     `/heuresis:queue`.
  4. **Phone path.** An Action workflow, secrets, an iOS Shortcut, an issue form and a weekly
     sweep.
  5. **Import.** Importers, the digest agent, then the backfill itself.
  6. **Review.** `/heuresis:review`, resurfacing, merges and lint.
- **`/techne:narrative-coherence`** — cross-sister README ecosystem
  audit. Reads each sister's README and checks whether they
  cross-reference each other into a coherent ecosystem story, surfacing
  missing reciprocal links. Distinct from `/techne:sisters`, which
  checks dev-infra coherence rather than narrative coherence.
- **`/techne:positioning`** — identity-drift check (claim vs work).
  Reads each sister's README hero, ROADMAP top, and recent commits,
  drafts a one-line "what does this project claim to be?", and flags
  where the claim has drifted from the work. Distinct from
  `/techne:docsync`, which checks technical claims against code; this
  goes after marketing-shape drift.
- **`/techne:workspace-orphans`** — content-bearing files outside the
  active sister perimeter. Scans the workspace root for directories
  absent from `~/.claude/techne.toml`, which are either stale artifacts
  or pre-promotion sisters. n=1 today; build when n≥2.
- **Execution-grounded triage pattern (watcher, not a build).** Anthropic's
  [defending-code-reference-harness](https://github.com/anthropics/defending-code-reference-harness)
  (autonomous C/C++ memory-safety vuln discovery) is **not** applicable to the
  fleet as a tool — nothing here is C/C++, velocity-fl's Rust core has zero
  `unsafe` blocks (no buffer-overflow / UAF class to fuzz), and the FL sisters'
  "security" is adversarial-ML (Byzantine/Fang/DP), a different domain. The one
  transferable idea is its **triage methodology**: stage findings
  (scan → dedupe → *N-vote verify* → patch) and only let *execution-* or
  *reproduction-verified* findings survive, to crush false positives. That maps
  onto techne's audit family (`/techne:audit`, `/techne:ci-audit`) — a future
  audit skill could adopt N-vote verification before it asserts a finding rather
  than reporting single-pass. **Why only a watcher:** code-vuln scanning is
  already covered by the built-in `/security-review` + `/code-review ultra`, so
  techne should not grow a vuln-scan skill (no n≥2 gap); the *N-vote verification*
  sub-pattern is the only piece worth borrowing, and only if a techne audit skill
  starts emitting false positives that single-pass review can't filter. Logged so
  the harness isn't re-evaluated from scratch next time it surfaces.
- **Renovate revisit trigger** — if the fleet consolidates into a
  monorepo or wants cross-repo shared presets + auto-merge, re-evaluate
  Renovate (shared `extends` preset). Also re-enable the `uv` ecosystem
  on kourai once dependabot-core#14004 (workspace mis-targeting) closes —
  **re-checked 2026-05-30: still open**, so kourai's uv deferral stands.
- **uv toolchain-floor churn — still deferred (re-verified 2026-06-01).** Dependabot's
  uv ecosystem bumps pyproject floors (not just uv.lock), so ruff/ty floors drift
  across sisters unevenly as releases land — caught and re-aligned via
  `/techne:sisters` check 7 (e.g. 2026-05-25), which remains the mitigation. The
  queued fix was `versioning-strategy: lockfile-only` on the uv entries, gated on
  dependabot-core#12162. **2026-06-01 verification says not ready, despite the issue
  closing:** #12162 closed (`completed`) but tracked the umbrella for its requester's
  `increase` value, not `lockfile-only` for uv; astral's own uv↔Dependabot guide
  (docs.astral.sh/uv/guides/integration/dependabot) documents only `package-ecosystem`
  + `cooldown` and **never mentions `versioning-strategy`**, and current sources report
  it "not fully supported for uv." Applying `lockfile-only` fleet-wide would push
  unverified config (silently ignored at best, broken updates at worst), so the
  template comment ("not supported for uv yet") stands — do **not** edit the fleet
  until astral's guide or the GitHub options reference explicitly lists
  `versioning-strategy` for the uv ecosystem. Renovate's `update-lockfile`
  rangeStrategy is the equivalent if the fleet ever moves there. `research(2026-06)`:
  astral uv-Dependabot guide (no versioning-strategy); #12162 closed for `increase`,
  uv `lockfile-only` support unconfirmed.

---

## Cross-cutting invariants

- **No `aj-*` skill names anywhere.** The plugin family was renamed
  to `techne:*` in 2026-05; the `## guards` make target hard-fails
  on any re-introduction. Same rule blocks references to the
  deprecated `.claude/skills/_shared` path.
- **Skill SKILL.md frontmatter is canon.** `name:` and `description:`
  in every `plugins/*/skills/*/SKILL.md` is the source of truth
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
