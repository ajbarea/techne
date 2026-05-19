# Techne Refresh — Slop Cleanup, Generalization, and Marketplace Submission

- **Date:** 2026-05-19
- **Status:** Draft for review. Marketplace submission form submitted 2026-05-19; cleanup proceeds in parallel with Anthropic's review.
- **Primary outcome:** Land techne on `anthropics/claude-plugins-official` as an opinionated repo-hygiene plugin, with the slop artifacts left behind by a lesser-AI deployment finish removed and the framing generalized from "AJ's personal kit" to "opinionated kit any developer can adopt with the documented conventions."

## Summary

Three motivations land in one refresh:

1. **Slop cleanup.** A lesser AI wrapped the deployment of the docs site, leaving committed status artifacts (`IMPROVEMENTS.md`, `DEPLOYMENT_READY.md`), an inflated docs site (`docs/architecture.md`, `docs/examples.md`, the `docs/skills/*.md` files all padded ~150% with duplicated content and fabricated CLI flags), and a stray `COMMITS.md` in the working tree.

2. **Generalization for marketplace.** Techne currently reads as "AJ's personal kit." The refresh generalizes the portable skills (prose-level and concept-level renames) while keeping `audit` honestly opinionated about its `logs/dev-<ts>-<cmd>.log` archive convention. Ships a Conventions guide teaching the Make-wraps-uv pattern the skills assume.

3. **Submission to `anthropics/claude-plugins-official`** via the public submission form at `clau.de/plugin-directory-submission`. Form submitted 2026-05-19; review pending.

Path chosen: **hybrid** (generalize where cheap, document the opinion where it's load-bearing). Two alternatives were considered and rejected:

- **Path A (deslop only):** keep "AJ's kit" framing, no marketplace submission. Rejected because AJ wants marketplace presence.
- **Path B (full generalize):** rewrite `audit` runner-agnostic, rename `sisters`/`theoros` concepts deeply. Rejected because it risks making `audit` worse for AJ without making it obviously better for anyone else (every dev runs different toolchains anyway).

## Background

### The lesser-AI deployment finish

AJ ran out of Claude tokens temporarily and used a different AI to wrap the docs site deployment. That AI left several signature slop patterns:

- **Status report files committed to repo root:** `IMPROVEMENTS.md` (line-count brag tables, "Quality Bar Achieved" framing) and `DEPLOYMENT_READY.md` ("READY TO DEPLOY" headers, emoji-decorated checklists).
- **Padded skill docs:** every `docs/skills/*.md` inflated from ~32 to ~80 lines with duplicated SKILL.md content, fabricated CLI flags (`/audit --verbose`, `/sisters --report-only`, `/reslop --file src/api.py`), and invented troubleshooting sections.
- **Slop-shaped architecture and examples docs:** ASCII art tree diagrams, emoji section headers ("🔧 Build & Toolchain"), hallucinated output blocks ("⚠️ Fixable in-repo (6 issues): ❌ actions/setup-python@v3 deprecated"), made-up session IDs.
- **A stray `COMMITS.md`** in the working tree (the AJ convention has this gitignored; the lesser AI created one and stranded it locally).

A separate lesser-AI audit at `~/ajsoftworks/copilot-audit-ideas/TECHNE_AUDIT.md` was also reviewed during brainstorming. It hallucinated techne as a Python CLI ("Core: Python 3.12+, Typer, GitHub API") and proposed ten feature-creep enhancements (JSON violation output, `--auto-fix` flags, Bandit/Semgrep integration, multi-language coverage, health-score dashboards) following from that category error. The single useful kernel — "Strongest asset: it's opinionated about code quality in a way that scales across repos" — is borrowed for the marketplace pitch. The audit file was deleted as part of this refresh. Three secondary positioning kernels carry forward: "opinionated" (centerpiece), "meta-development tools" (one-word framing), and "multi-project dashboard" framing for `sisters`.

### The marketplace ambition

The official directory is `anthropics/claude-plugins-official`. Submission is via the public form at `clau.de/plugin-directory-submission`, not via PR (direct PRs auto-close; submissions flow through Anthropic's internal review pipeline). The bar is quality + security review, not "useful to every dev," but the discovery UX of the marketplace rewards plugins that read as broadly applicable.

### Skill-by-skill generalize cost

| Cost | Skills | What couples them to AJ |
|---|---|---|
| Cheap (prose rename) | `ci-audit`, `deslop`, `reslop`, `docsync`, `docs-site`, `auto-commit` | Already read generic inputs (`gh`, markdown, code). Strip "AJ"/"phalanx-fl" examples, ship. |
| Medium (concept rename) | `sisters`, `theoros` | "Sister repos"/"kourai-khryseai" are AJ-flavored framings; the underlying concepts (linked-repo drift, observed tmux session) are universal. |
| High (convention-coupled) | `audit` | Tightly coupled to the `logs/dev-<ts>-<cmd>.log` archive convention + Makefile-wraps-uv pattern. Stays opinionated with an explicit "requires this convention" pointer to the Conventions guide. |

## Section 1: Scope

### Dies

- `COMMITS.md` — working-tree only (already gitignored per AJ convention). Simple `rm`.
- `IMPROVEMENTS.md` — tracked, committed in `41c7475`. `git rm` + add to `.gitignore`.
- `DEPLOYMENT_READY.md` — tracked, committed in `b746523`. `git rm` + add to `.gitignore`.

History stays as-is. The introducing commits also touched legitimate work (the docs site bootstrap, the landing CTA fix); no clean revert. Delete forward in a new commit. No destructive history rewrite.

**`.gitignore` addition** (specific names, mirrors the existing `COMMITS.md` line):

```
# Transient AI-status artifacts, never committable
IMPROVEMENTS.md
DEPLOYMENT_READY.md
```

### Stays

- The plugin's `plugins/techne/skills/*/SKILL.md` files — AJ's own work, untouched by the lesser AI. Editing only for description-text generalization per Section 3.
- Modular CSS split (`variables.css`, `base.css`, `components/hero.css`, `components/landing.css`) — genuinely good maintenance pattern. Keep.
- `docs/javascripts/hero.js` — small, single justified comment. Keep.
- `marketplace.json` — generic enough; minor description polish only.
- Architecture and Examples nav slots in `zensical.toml` — good information architecture; the content gets deslopped but the slots stay.

### Gets added

- **`docs/conventions.md`** — new top-level nav slot teaching the Make-wraps-uv pattern, the `.claude/skill-context.md` skeleton, the dev-runner archive contract, and the `~/.claude/techne.toml` user config. See Section 2.
- **`scripts/dev-runner.sh`** — reference script users `cp` into their repo's `scripts/`. Makes the `audit` skill instantly usable without users reverse-engineering the archive convention.
- **`.github-template/workflows/docs.yml`** — reference workflow under a non-conflicting path (`.github-template/` instead of `.github/`) users copy into their own `.github/workflows/`. Makes the `docs-site` skill drop-in adoptable.

### Gets rewritten (substantial deslop, content survives)

- **`docs/architecture.md`** (~190 lines → ~80-100). Replace ASCII art + emoji headers with terse prose. Keep concept structure (Build / Documentation / Versioning / Multi-Repo categories) but compress each to 2-3 sentence descriptions. See Section 4.
- **`docs/examples.md`** (~390 lines → ~150-200). Partial rewrite, not just deslop. Strip fabricated CLI flags and emoji-decorated output blocks; replace AJ-coded paths with placeholders; tighten each workflow. See Section 4.
- **Every `docs/skills/*.md`** (~80 lines each → ~40-50). Strip duplication of SKILL.md content and invented features. See Section 4.
- **`README.md`** — generalize lede (drop "sister project to kourai-khryseai" link), replace AJ-coded config example with placeholders, cross-link the Conventions guide. See Section 3.
- **`pyproject.toml`** — `description` from "AJ's personal Claude Code skill collection, distributed as a plugin." → "An opinionated Claude Code skill collection for repo hygiene, audits, and doc/code drift."
- **`zensical.toml`** — `site_description` from `"Nine Claude Code skills. One /plugin install. Sister-repo hygiene, audit pipelines, doc/code drift checks, and CI noise control."` → `"Opinionated Claude Code skills for repo hygiene: audit pipelines, hunt doc/code drift, tame CI noise, sync linked repos. One /plugin install."` (142 chars; sits in the ideal range for desktop meta descriptions).

### Theoros: not a registration bug

An earlier brainstorming hypothesis ("theoros isn't loading; the session reminder showed eight of nine skills") was wrong. The frontmatter at `plugins/techne/skills/theoros/SKILL.md` is correct, the skill is shipped, and AJ has used it recently. The eight-of-nine count in the system reminder was a per-session load quirk, not real drift. No fix needed.

### Theoros spec/plan archival

`docs/specs/2026-05-17-theoros-design.md` and `docs/plans/2026-05-17-theoros.md` are AJ's brainstorming + writing-plans output from when theoros was implemented. They're decision records with a deferred-work tail, not active improvement docs. Move them to the canonical superpowers paths:

- `docs/specs/2026-05-17-theoros-design.md` → `docs/superpowers/specs/2026-05-17-theoros-design.md`
- `docs/plans/2026-05-17-theoros.md` → `docs/superpowers/plans/2026-05-17-theoros.md`

This refresh's spec lands in the same canonical location (`docs/superpowers/specs/2026-05-19-techne-refresh-design.md`), so future readers find related history together. Verify zensical doesn't render `docs/superpowers/**` as orphan pages; exclude via configuration if it does.

After relocation, the empty `docs/specs/` and `docs/plans/` directories are removed (`rmdir`); future specs/plans go to the canonical path and recreate the structure automatically.

## Section 2: Conventions guide

### Location

`docs/conventions.md` as a new top-level nav slot, sibling of the existing "Configuration" page. Not merged with Configuration: Configuration is for settings; Conventions is for the patterns techne assumes the user adopts.

### Structure

Terse prose throughout, no emoji headers. Sections:

1. **Overview** (~5 lines). Techne is opinionated; here are the opinions and how to adopt them. Each subsection cross-references the dependent skill(s).

2. **The Makefile pattern.** Wrap toolchain commands behind one-word `make` targets. Why: stable interface across heterogeneous tools (uv, npm, cargo, just); CI-friendly; self-documenting. Ships a ~20-line example Makefile covering `setup`, `lint`, `test`, `ci`. Cross-refs: required for `audit`, recommended for `ci-audit` and `theoros`.

3. **The dev-runner archive.** Each `make <target>` invocation writes `logs/dev-<UTC-timestamp>-<target>.log` ending with a `SUMMARY` block. The `audit` skill diffs the terminal exit code against these archives. Documents the contract (filename pattern, `SUMMARY` schema) and ships `scripts/dev-runner.sh` as the reference implementation. Cross-refs: required for `audit`.

4. **`.claude/skill-context.md`.** Per-repo config the skills read. Ships a copy-pasteable skeleton inline (single fenced code block) with all required section headers (`## repo`, `## audit`, `## ci_audit`, `## slop_ground_truth`, `## scan_scope`, `## docs_site`, `## theoros`). Cross-refs: required for `audit`, `sisters`, `theoros`; recommended for the deslop/reslop/docsync family.

5. **`~/.claude/techne.toml`.** User-level config; one paragraph pointing at the README example. Cross-refs: required for `sisters`.

6. **`COMMITS.md`.** Auto-commit writes here. Gitignore it. Three lines. Cross-refs: required for `auto-commit`.

7. **The docs-site workflow.** `.github/workflows/docs.yml` deploys via Zensical to GitHub Pages. References `.github-template/workflows/docs.yml` as the worked example users copy. Cross-refs: required for `docs-site`.

### Decisions resolved during brainstorming

- **Ship `scripts/dev-runner.sh`** as a reference implementation rather than document the contract only. Resolves the audit-skill adoption barrier; matches the "opinionated kit" positioning.
- **Ship `.github-template/workflows/docs.yml`** as a reference workflow rather than document only. Same rationale.
- **Skill-context skeleton lives inline in `conventions.md`** (single fenced code block) rather than a separate template file. Keeps the guide self-contained.

## Section 3: Positioning rewrite

Per-artifact text changes that strip AJ-coded framing without losing voice.

### `README.md`

- **Lede:** mostly stays. "Claude Code skills..." is already general. "Sister repos" as a concept stays; what was personal was naming *which* sisters. Polish for count-agnostic phrasing (no "Nine").
- **Config example block:** replace `github_user = "ajbarea"`, `workspace_root = "/home/ajbar/ajsoftworks"`, and the specific sister names (phalanx-fl, vFL, kourai-khryseai) with placeholders (`your-github-username`, `/path/to/your/workspace`, `repo-one`/`repo-two`).
- **"Why techne" section:** drop the sentence "Sister project to kourai-khryseai, where Techne is the coder agent." Keep the Greek etymology paragraph.
- **Cross-link the Conventions guide** in the install section so new users find prerequisites before the audit skill fails mysteriously.

### `pyproject.toml`

- `description`: "AJ's personal Claude Code skill collection, distributed as a plugin." → "An opinionated Claude Code skill collection for repo hygiene, audits, and doc/code drift."

### `marketplace.json`

- Plugin `description` already neutral; keep.
- `owner.name = "AJ"` stays. Authorship attribution, not personal framing.

### SKILL.md descriptions (frontmatter)

- **`sisters`:** "AJ's sister repos (currently phalanx-fl, vFL, kourai-khryseai...)" → "linked repos listed in `~/.claude/techne.toml` (configurable per-user)."
- Sweep the other portable skills (all except `audit`) for any "AJ"/"phalanx"/"kourai"/"vFL" references; generalize.
- **Trigger phrases stay.** They're functional for skill activation; generalize framing but preserve the phrases users actually say.
- **`audit` is the exception.** Keep its description honest about the `logs/dev-<ts>-<cmd>.log` archive dependency. Add a one-clause pointer: "...requires the dev-runner archive convention; see Conventions guide."

### Audit SKILL.md body

The current pointer ("this skill needs one [skill-context.md]; ask the user to add one...") stays in spirit; update its reference to point at `docs/conventions.md` as the canonical authority.

## Section 4: Docs deslop bulk pass

Largest section by line-count. Mechanical once the principles are settled.

### Deslop principles applied

Drawn from `/techne:deslop` itself and AJ's memory of writing patterns:

- No emoji in headers or prose (✓, ❌, ⚠️, 🔧, 📚, 🚀, etc.).
- No hardcoded counts of skills, workflows, features, datasets, agents. Replace with count-agnostic phrasing (category names, not numbers). Category-specificity is durable where count-specificity is not.
- No line-count brag tables or "Quality Bar Achieved" framing.
- No temporal markers ("Completed 2026-05-18", "May 2026 best practice", "Updated: ...").
- No marketing padding ("comprehensive", "robust", "powerful", "production-grade").
- No em-dashes (per AJ memory rule for external prose under AJ's name: replace by intent, comma/semi/parens/period; POSIX `--flags` stay).
- One-line comments max in code blocks.
- Real skill invocation syntax (`/techne:sisters`), not invented CLI flags (`/sisters --report-only`).

### Artifact 1: `docs/architecture.md`

~190 → ~80-100 lines.

- Replace ASCII-art tree + emoji section headers ("🔧 Build & Toolchain") with terse prose.
- Keep the concept structure (Build / Documentation / Versioning / Multi-Repo categories) but compress each to 2-3 sentence descriptions.
- Compress the four typical-workflow sections to 4-5 bullet lines each (currently 6-7 numbered steps with emoji).
- Replace the four-numbered "Design philosophy" section with one 5-7 line prose paragraph.

### Artifact 2: `docs/examples.md`

~390 → ~150-200 lines. Partial rewrite, not just deslop.

Beyond cosmetics, fixes hallucinated content:

- **CLI flags that don't exist:** `/audit --verbose`, `/sisters --report-only`, `/reslop --file src/api.py`, `/deslop docs/ src/`. Skills are invoked by name with natural-language modifiers; they don't take CLI flags. Rewrite every invocation example to match real skill behavior.
- **Fabricated outputs:** invented drift reports ("`Function signature 'fetch_user(user_id)' is now 'fetch_user(user_id: int) -> Optional[User]'`"), emoji-decorated output blocks ("`⚠️ Fixable in-repo (6 issues): ❌ actions/setup-python@v3 deprecated`"), made-up session IDs (`theoros-2026-05-18-15-30-42` vs. the actual `<repo-slug>-theoros` convention). Replace with prose descriptions of expected output, not fabricated literal output.
- **AJ-specific repo names:** phalanx-fl, vFL, kourai-khryseai everywhere → placeholders per Section 3.
- **AJ-coded paths:** `/home/ajbar/ajsoftworks/my-project` → `<your-repo>` placeholder.

Tighten each of six workflows to ~20-30 lines.

### Artifact 3: every `docs/skills/*.md`

~80 lines each → ~40-50.

Each was inflated ~+150% with duplicated SKILL.md content + invented features.

- **Keep:** Overview (1-2 lines), purpose/when-to-use (only if it adds to the frontmatter), real usage examples, `.claude/skill-context.md` configuration pointer, terse See Also.
- **Drop:** invented `--flag` arguments, invented error scenarios in "Troubleshooting" sections, "Reads:" sections that just enumerate file paths users won't care about, padded See Also lists.

### Acceptance criteria (Section 4)

- Emoji grep across user-facing docs (`docs/` excluding `docs/superpowers/**`) returns empty (modulo intentional code-fence content).
- Em-dash and en-dash grep across user-facing docs returns empty.
- No `\b(nine|9|six|6|eight|8|ten|10)\b` adjacent to "skills|workflows|features" in user-facing docs (`docs/` excluding `docs/superpowers/**`, `README.md`, `zensical.toml`) — or only matches load-bearing context. Internal planning artifacts under `docs/superpowers/**` are intentionally excluded; precision counts are useful for internal communication where they would be fragile for users.
- No `/techne:* --flag` patterns; every skill invocation in examples matches actual behavior.
- All AJ-specific repo names replaced with placeholders.
- Page sizes within target ranges (rough, not exact).

## Section 5: Marketplace submission path

### Status

Form submitted 2026-05-19 via `https://clau.de/plugin-directory-submission`. Awaiting Anthropic's review.

### Submission mechanism (verified 2026-05)

- Form: `https://clau.de/plugin-directory-submission` (public URL), or `https://platform.claude.com/plugins/submit` via console.
- **Not via PR** to `anthropics/claude-plugins-official` — direct PRs auto-close; submissions flow through the form into Anthropic's internal review pipeline.

### Cleanup ordering (because the form is already in)

Because the form is submitted, Anthropic's automated and manual review will look at the repo in its current slop-shaped state unless Sections 1-4 land first. Cleanup ordering becomes urgent rather than blocking:

1. Land Sections 1, 3, 4 (the surface-level cleanup: slop files removed, README/SKILL.md descriptions generalized, docs deslopped) as soon as possible.
2. Land Section 2 (Conventions guide + `scripts/dev-runner.sh` + `.github-template/workflows/docs.yml`) immediately after; this is the substantive adoption-enablement work.
3. Smoke test: install from a clean Claude Code session, verify all skills load, run at least one against a real repo end-to-end.
4. Verify the Pages site builds clean with the new content (Conventions guide rendered, deslopped architecture/examples live).

### Security profile

All skills execute local CLI commands via the user's existing auth (`gh`, `git`, `tmux`, `docker compose`, `make`). No raw network access. No secrets handled. No code execution from external sources. Aligns with Claude Code skill conventions; nothing exotic that would flag review.

### Post-submission expectations

"Published" in the portal does not immediately mean visible in the directory (known lag, issues [#984](https://github.com/anthropics/claude-plugins-official/issues/984) and [#1272](https://github.com/anthropics/claude-plugins-official/issues/1272)). Expect a several-day window. Any quality/security flags come back via the form. If Anthropic requests changes, address them inline; resubmission flows through the same form.

### Decisions baked in

- **Anthropic Verified badge:** out of scope for v1 submission. Targets the additional manual review tier; pursue after the directory listing settles in and adoption telemetry justifies it.
- **Submission timing:** moot, already done.

### Post-acceptance maintenance

- README + SKILL.md descriptions are the user-visible source of truth. Eat your own dogfood: run `/techne:deslop` on the techne repo periodically to prevent drift.
- Bump `marketplace.json` version for material changes.
- Drift watch: if Anthropic publishes additional standards (security checklist, structural requirements), revisit then.

## Acceptance criteria (rollup)

- The three slop files are deleted (`COMMITS.md` from working tree; `IMPROVEMENTS.md` and `DEPLOYMENT_READY.md` `git rm`-ed) and `.gitignore` updated.
- `docs/conventions.md` exists and teaches the four conventions (Makefile pattern, dev-runner archive, skill-context.md skeleton, techne.toml pointer).
- `scripts/dev-runner.sh` and `.github-template/workflows/docs.yml` exist as reference artifacts users can copy.
- `README.md`, `pyproject.toml`, `marketplace.json`, `zensical.toml`, and the eight portable SKILL.md frontmatter descriptions are generalized per Section 3.
- `docs/architecture.md`, `docs/examples.md`, and every `docs/skills/*.md` file pass the Section 4 acceptance criteria (no emoji, no em-dashes, no fabricated CLI flags, no AJ-specific repo names, no fragile counts).
- The theoros spec/plan are relocated to `docs/superpowers/specs/` and `docs/superpowers/plans/`.
- The Pages site builds clean and renders the new content.
- The marketplace listing, once approved, points at a clean repo.

## Out of scope

- **Rewriting `audit` runner-agnostic.** Deliberately retained as opinionated. The Conventions guide documents the opinion.
- **Adding new skills** (no `techne:security-scan`, `techne:perf-regression`, `techne:health-dashboard`, etc.; these were lesser-AI feature creep based on a category error about what techne is).
- **Auto-fix mode or JSON output for `/techne:deslop` and `/techne:docsync`.** Skills are LLM-driven prose instructions; they don't have CLI flags. Same category error.
- **Extending `/techne:deslop` to flag hardcoded counts.** Worth doing but separate; flagged for a future pass.
- **Anthropic Verified badge.** Out of scope for v1 submission.
- **Other lesser-AI audits in `~/ajsoftworks/copilot-audit-ideas/`** (KOURAI_AUDIT.md, PHALANX_FL_AUDIT.md, etc.). Per-repo cleanup if AJ wants it; not techne's responsibility.

## Open questions for review

1. **Site_description punchline.** The decision baked in strips "Nine ... One ..." rhetorical contrast in favor of category-specific prose. The "One /plugin install." stays as a stable binary truth. Confirm this reads right; the contrast loss is real but earns durability.

2. **Conventions guide depth.** The guide ships a reference Makefile snippet, `dev-runner.sh`, `.claude/skill-context.md` skeleton, and `docs.yml` workflow. Current target is "minimum viable adoption" — enough that a stranger can get the audit skill working on the first try. A longer treatment (rationale, alternatives, troubleshooting) can come post-submission if adoption telemetry justifies it.

## Success criteria

A developer who:

- has never seen techne,
- finds it in the marketplace listing,
- reads the README and Conventions guide,
- copies `scripts/dev-runner.sh` and `.github-template/workflows/docs.yml` into their repo,
- creates a `.claude/skill-context.md` from the inline skeleton,
- runs `/techne:audit` against their repo,

...gets a working audit on the first try without conversation-level back-and-forth.

Additionally:

- The marketplace listing shows techne with a working install command and a clean description.
- The Pages site reads as a professional opinionated tool, not as someone's personal kit.
- `/techne:deslop` run against the techne repo itself returns zero new findings (the project eats its own dogfood).
