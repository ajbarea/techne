# techne — Roadmap

Long-horizon plan for the techne plugin. Session-by-session execution
lives in [IMPL.md](./IMPL.md). When a milestone ships, it collapses to a
dated one-liner under [Shipped](#shipped). Git history is the
permanent record of how each skill was designed.

Last reviewed: 2026-09-17 (v1.0.0 release pass).

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
larger sibling. The current set spans six catalog dimensions (audit,
drift, hygiene, review, observation, document build); IMPL.md maps each
skill to one. `research-grounded`
(from the 2026-05-21 audit-of-audit) shipped 2026-05-29 on direct
request; `narrative-coherence` and `positioning` remain queued for when
that drift class recurs.

---

## Queued / unprioritized

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

- 2026-09-22 — **`techne:slides`.** A stdlib OOXML checker gates a talk deck on real title
  placeholders, contrast resolved through the surface actually behind the text, alt text,
  portable fonts, and figures or walls of text on talk slides; a renderer exports through
  PowerPoint (native or from WSL) or LibreOffice into a folder of its own. The skill carries
  the toolchain split (Touying for PDF decks, pptxgenjs for `.pptx`) and writing for a
  newcomer audience: claim headlines, an agenda, discussion stops, numbers kept to backup.
- 2026-09-17 — **v1.0.0, and a release pass over every file.** The README, landing page,
  Getting Started, Architecture and IMPL each listed a different subset of the skills; every
  skill now appears in each. Skill texts that contradicted the fleet were corrected:
  `docs-site` blessed tag-pinned actions that `make guards` rejects, `conventions.md` showed
  calling `dev-runner.sh` from a Makefile recipe (it recurses), and `dev-runner.sh` wrote
  untagged archives while `techne:audit` greps for the `[OUT  ]` / `[ERROR]` lines a
  `scripts/dev.py` runner writes; the shell runner now writes the same shape. The starter
  `.github-template/workflows/docs.yml` had fallen a major or two behind with none of the
  zizmor hardening, because Dependabot never reads that directory; it now copies the live
  pins, and `check_action_pins.sh` fails when the two differ (verified by drifting a SHA and
  reverting a pin to a tag). `catchup`, `latex` and `pdf` address their scripts through
  `${CLAUDE_SKILL_DIR}`. `CITATION.cff` added; the plugin stays unversioned so installs keep
  following the commit SHA, and releases are git tags.

- 2026-09-16 — **`/techne:latex` skill.** Builds a LaTeX document and gates the result on its
  log, its `.blg`, its PDF and the assignment prompt it answers, in one command. Build and
  verify are fused because `latexmk` exits 0 on a document whose every citation resolved to
  `[?]`, so a separate verify step is one that gets skipped on the run where it mattered;
  the exit code carries the verdict (0 clean / 1 no build / 2 built-but-wrong). Log wrapping
  is fixed upstream with `max_print_line` rather than by parsing texlogsieve's prose, which
  is what makes plain regex gates reliable. Engine decided as latexmk + local TeX Live: not
  tectonic, whose bundled biblatex against a system biber is a known skew class and
  `biblatex-chicago` sits in its path. Validated on both class families (QML homework:
  quantikz/braket, 28 surviving FILL badges caught, 7/7 prompt headers matched across the
  read-only clone; CISC-810 cooking paper: biblatex-chicago + biber, clean). Two defects
  found by running it rather than reading it — an anchored `.blg` regex that let a missing
  citation read as a clean build, and a fatal-error cascade that reported three phantom
  undefined refs. Absorbs the hand-rolled per-assignment `make check` in
  `classes/csci739-*/03-assignments/hw1/`, which is deleted.
- 2026-09-16 — **First pytest suite (45 tests).** techne had no unit tests: `make test` was
  JSON validity, SKILL.md frontmatter and grep guards. `latex.py` earned the harness, since
  both defects it shipped with were misclassifications in pure functions. Tier 1 covers the
  log/`.blg`/coverage gates against fixture text and runs everywhere; tier 2 builds four real
  documents and asserts the exit code. `collapse_cascade` and `verdict` were lifted out of
  `main()` so the cascade regression is a unit test rather than only an end-to-end one.
  CI does not install TeX Live (it would take a 14s pipeline to minutes), so the opt-out is
  declared instead of implied: a guard test fails when the toolchain is absent and
  `TECHNE_NO_TEX=1` is unset, and `validate.yml` sets it with the reason. Verified in both
  directions, absent-and-undeclared fails and absent-and-declared skips visibly, so green by
  absence cannot happen here. `tests/` is repo-level so `pdf/scripts/render.py` inherits it.
- 2026-09-16 — **`techne:pdf` render.py covered (74 tests total).** Unit tests over the
  markdown front end: `_typst_str`'s escape order (escaping quotes before backslashes closes
  the Typst string and spills the rest of a title into code), what `split_front_matter` lifts
  versus leaves in the body across nine document shapes, and an assertion that no template
  placeholder goes unfilled, which is the drift a new `{{TOKEN}}` would otherwise cause
  silently. Four end-to-end cases compile through Typst and check the words survive
  `pdftotext`, the verification the skill documents. The typst wheel is pulled per-run rather
  than pinned as a dev dependency, matching how the skill itself runs. CI declines the compile
  because the first one fetches cmarker from Typst Universe, and declares it with
  `TECHNE_NO_TYPST=1`. Both opt-out flags now also skip on a machine that *has* the toolchain,
  so the declaration means the same thing everywhere.
- 2026-09-16 — **`techne:catchup` sweep.py covered (114 tests total).** Closes the last
  untested skill-shipped Python. Covers repo resolution across all four argument shapes, the
  nested-clone walk, the GraphQL flattening, and what is allowed to anchor a window. Most of
  these pin a safety property the code documents in prose: a close is never attributed to the
  author, a state change on your own item is not participation, a commit moves the anchor but
  not the participation timestamp, and no sibling clone is dropped from a scan. `gh` and `git`
  are faked with pytest-subprocess (`# research(2026-09)`: preferred over hand-rolled
  monkeypatch for subprocess, and it asserts the exact argv, which matters because the slug
  must come from `gh repo view` and not a parsed remote). Snapshot testing (syrupy) was
  considered for the payload flattening and declined: snapshots record what the output is, not
  why, and their failure mode is blessing a diff to get green, which is the opposite of what
  this suite is for. monkeypatch stays where the assertion is about a command's environment,
  since `fp.calls` records argv only and cannot see `max_print_line`.
- 2026-09-16 — **`make validate` builds the site, and CI does too.** A dependency bump left
  lint, tests and zizmor green while aborting the docs build: zensical 0.0.60 moved search
  into Rust and removed the `engine` option this repo set. Nothing would have caught it,
  because `docs.yml` runs on push to main rather than on pull requests, and `validate` did not
  include `build` — drift from techne's own published target vocabulary, which defines
  validate as `lint test-unit build`. Added to both the target and `validate.yml`, and
  verified by restoring the bad option and watching the gate fail (exit 2). Cost: 0.4s.
- 2026-09-16 — **sweep.py: functional core, and a constant that now says what it does.**
  The event budget lived in `main()` as a closure over local state, so the rule that matters
  most there — anything addressed to the user survives the cap, everything else competes on
  recency — could only be exercised end-to-end. Lifted to `select_reported` and
  `retain_pre_anchor`, both pure (`# research(2026-09)`: functional core / imperative shell,
  the standard frame for making a CLI's decisions testable without mocks), and covered by 15
  tests. `NESTED_CLONE_CAP` renamed to `NESTED_STOP_DESCENT_AFTER`: it never capped the
  result, it stops the walk going deeper, and truncating the result would produce the false
  all-clear the scan exists to catch. Verified behaviour-identical by diffing a live sweep of
  this repo before and after.
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
  Dependabot ecosystem fleet-wide. Remaining (DRY, not coverage): every sister
  already enforces pin-pinning via an inline regex in its own `pin-check.yml`;
  consolidating them onto techne's shared `check_action_pins.sh` is the open step.
  Pin-pinning is fleet-wide today — only the *shared script* is techne-only.
