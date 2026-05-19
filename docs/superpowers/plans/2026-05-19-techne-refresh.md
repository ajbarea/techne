# Techne Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the techne refresh (slop cleanup + generalization + Conventions guide) against the spec at `docs/superpowers/specs/2026-05-19-techne-refresh-design.md` before Anthropic's marketplace review (form submitted 2026-05-19) examines the repo.

**Architecture:** Sequence tasks by dependency — cleanup first (clears the slop and relocates planning artifacts), then positioning surfaces (the user-visible text), then Conventions guide + reference artifacts (new content), then docs deslop (rewrites against placeholders established in earlier tasks), then verification and smoke test. Each task ends with a commit. The grep-based acceptance criteria from Section 4 of the spec serve as the "tests" for prose work.

**Tech Stack:** Markdown, TOML (zensical, pyproject), JSON (marketplace), Bash (dev-runner script), YAML (Pages workflow), Make.

---

## File Structure

**Created:**
- `docs/conventions.md` — new top-level nav slot teaching the four conventions (Makefile pattern, dev-runner archive, skill-context.md skeleton, techne.toml pointer)
- `scripts/dev-runner.sh` — reference Make-target log wrapper that produces `logs/dev-<ts>-<cmd>.log` with `SUMMARY` block
- `.github-template/workflows/docs.yml` — reference Zensical Pages workflow users copy to their own `.github/workflows/`

**Modified:**
- `.gitignore` (append two filenames)
- `README.md` (lede polish, config example placeholders, drop kourai-khryseai link, cross-link Conventions guide)
- `pyproject.toml` (description rewrite)
- `zensical.toml` (`site_description` + Conventions nav slot)
- `docs/architecture.md` (deslop rewrite ~190 → ~80-100 lines)
- `docs/examples.md` (deslop + hallucination fixes ~390 → ~150-200 lines)
- `docs/skills/{audit,auto-commit,ci-audit,deslop,docs-site,docsync,reslop,sisters,theoros}.md` (~80 → ~40-50 lines each)
- `plugins/techne/skills/sisters/SKILL.md` (description text)
- `plugins/techne/skills/audit/SKILL.md` (description caveat + body pointer to `docs/conventions.md`)
- Other `plugins/techne/skills/*/SKILL.md` files (sweep for AJ-coded references)

**Deleted:**
- `IMPROVEMENTS.md` (tracked; `git rm`)
- `DEPLOYMENT_READY.md` (tracked; `git rm`)
- `COMMITS.md` (untracked; `rm`)

**Moved:**
- `docs/specs/2026-05-17-theoros-design.md` → `docs/superpowers/specs/`
- `docs/plans/2026-05-17-theoros.md` → `docs/superpowers/plans/`
- After move: remove the now-empty `docs/specs/` and `docs/plans/`

---

## Task 0: Commit the spec and plan if not already committed

**Files:**
- `docs/superpowers/specs/2026-05-19-techne-refresh-design.md` (this refresh's spec, currently uncommitted)
- `docs/superpowers/plans/2026-05-19-techne-refresh.md` (this plan, currently uncommitted)

- [ ] **Step 1: Check whether spec and plan are tracked**

Run: `git ls-files docs/superpowers/`
If both spec and plan files are listed: skip to Task 1 (already committed in AJ's batch).
If they're absent: continue to Step 2.

- [ ] **Step 2: Stage and commit the planning artifacts**

```bash
git add docs/superpowers/specs/2026-05-19-techne-refresh-design.md docs/superpowers/plans/2026-05-19-techne-refresh.md
git commit -m "docs: brainstorm spec + plan for techne marketplace refresh"
```

---

## Task 1: Delete slop status files + update .gitignore

**Files:**
- Delete: `IMPROVEMENTS.md`, `DEPLOYMENT_READY.md` (tracked); `COMMITS.md` (untracked)
- Modify: `.gitignore` (append two lines after existing `COMMITS.md` line)

- [ ] **Step 1: Pre-flight verify git state**

Run: `git ls-files COMMITS.md IMPROVEMENTS.md DEPLOYMENT_READY.md`
Expected: `IMPROVEMENTS.md` and `DEPLOYMENT_READY.md` printed; `COMMITS.md` absent.

Run: `git status --short -- COMMITS.md IMPROVEMENTS.md DEPLOYMENT_READY.md`
Expected: empty (working-tree state of these files matches HEAD aside from local untracked `COMMITS.md`).

- [ ] **Step 2: Append to `.gitignore`**

Add these lines after the existing `# AJ working-doc convention: COMMITS.md is always local` / `COMMITS.md` lines:

```
# Transient AI-status artifacts, never committable
IMPROVEMENTS.md
DEPLOYMENT_READY.md
```

- [ ] **Step 3: Remove the three files**

```bash
rm COMMITS.md
git rm IMPROVEMENTS.md DEPLOYMENT_READY.md
```

- [ ] **Step 4: Verify**

Run: `ls COMMITS.md IMPROVEMENTS.md DEPLOYMENT_READY.md 2>&1`
Expected: 3 × "No such file or directory".

Run: `git status --short`
Expected: includes `D  IMPROVEMENTS.md`, `D  DEPLOYMENT_READY.md`, `M  .gitignore` (or with leading `D` and `M` in the staged column).

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: remove AI-status slop files; gitignore future ones"
```

---

## Task 2: Relocate theoros spec + plan to canonical superpowers paths

**Files:**
- Move: `docs/specs/2026-05-17-theoros-design.md` → `docs/superpowers/specs/`
- Move: `docs/plans/2026-05-17-theoros.md` → `docs/superpowers/plans/`
- Remove: empty `docs/specs/` and `docs/plans/` directories

- [ ] **Step 1: Confirm canonical target directories exist**

Run: `ls -ld docs/superpowers/specs docs/superpowers/plans`
Expected: both directories present (created during brainstorming).

- [ ] **Step 2: Move both files preserving git history**

```bash
git mv docs/specs/2026-05-17-theoros-design.md docs/superpowers/specs/
git mv docs/plans/2026-05-17-theoros.md docs/superpowers/plans/
```

- [ ] **Step 3: Remove the now-empty source directories**

```bash
rmdir docs/specs docs/plans
```

- [ ] **Step 4: Verify**

Run: `git status --short`
Expected: shows two rename entries (`R  docs/specs/... -> docs/superpowers/specs/...` and similar for plans).

Run: `ls docs/specs docs/plans 2>&1`
Expected: 2 × "No such file or directory".

Run: `ls docs/superpowers/specs docs/superpowers/plans`
Expected: each lists its `2026-05-17-theoros-*` file plus the new `2026-05-19-techne-refresh-*` files if Task 0 ran.

- [ ] **Step 5: Confirm zensical doesn't render `docs/superpowers/**` as orphan pages**

Run: `grep -nE 'superpowers' zensical.toml`
Expected: no hits (the nav doesn't reference these paths).

If zensical's build picks up orphan markdown by default (verify by running `uv run --group dev zensical build` and grepping `site/superpowers/`), exclude the path via zensical config. Defer the exclusion to Task 13 if no orphan pages appear.

- [ ] **Step 6: Commit**

```bash
git commit -m "chore: relocate theoros spec/plan under canonical docs/superpowers path"
```

---

## Task 3: Generalize `README.md`

**Files:**
- Modify: `README.md`

Three sub-edits: (a) lede polish for count-agnostic phrasing, (b) config example placeholders, (c) drop kourai-khryseai sister-link sentence; the Greek etymology paragraph stays. Cross-link to Conventions guide is added in Task 8 (after the guide exists at `docs/conventions.md`).

- [ ] **Step 1: Lede polish (line 3)**

Replace the lede sentence:

```diff
- Nine Claude Code skills that audit builds, tame CI noise, hunt doc/code drift, and keep sister repos in lockstep, installable as a single `/plugin`.
+ Opinionated Claude Code skills for repo hygiene: audit builds, tame CI noise, hunt doc/code drift, keep linked repos in lockstep. Installable as a single `/plugin`.
```

Rationale: drops "Nine" per the count-agnostic deslop rule; replaces "sister repos" with the neutral "linked repos"; threads the "opinionated" framing from the spec; ends with the "One /plugin install" punchline as a load-bearing binary truth.

- [ ] **Step 2: Generalize the config example (lines ~40-54)**

Replace the AJ-coded TOML block with placeholders:

```diff
- github_user   = "ajbarea"
- workspace_root = "/home/ajbar/ajsoftworks"
+ github_user   = "your-github-username"
+ workspace_root = "/path/to/your/workspace"

  [[sisters]]
- name   = "phalanx-fl"
+ name   = "repo-one"
  status = "active"

  [[sisters]]
- name   = "vFL"
+ name   = "repo-two"
  status = "active"

  [[sisters]]
- name   = "kourai-khryseai"
+ name   = "repo-three"
  status = "active"
```

- [ ] **Step 3: Drop the kourai-khryseai sister-project line**

In the `## Why "techne"` section, remove the sentence:

```diff
- Sister project to [kourai-khryseai](https://github.com/ajbarea/kourai-khryseai), where Techne is the coder agent.
```

Keep the Greek etymology paragraph that precedes/follows.

- [ ] **Step 4: Verify the README diff**

Run: `git diff README.md`
Expected: three localized changes (lede, config block, sister-project sentence); no other edits.

Run: `grep -nE 'ajbarea|ajsoftworks|phalanx-fl|kourai-khryseai|vFL' README.md`
Expected: empty.

Run: `grep -nE '\bNine\b' README.md`
Expected: empty.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): generalize lede, config example, drop personal sister-link"
```

---

## Task 4: Generalize `pyproject.toml` description

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit the description field**

```diff
- description = "AJ's personal Claude Code skill collection, distributed as a plugin."
+ description = "An opinionated Claude Code skill collection for repo hygiene, audits, and doc/code drift."
```

- [ ] **Step 2: Verify**

Run: `grep -n 'description' pyproject.toml`
Expected: single match, the new description.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build(pyproject): generalize description from 'AJ's personal' to opinionated kit"
```

---

## Task 5: Generalize `zensical.toml` site_description + add Conventions nav slot

**Files:**
- Modify: `zensical.toml`

Two changes: (a) replace `site_description` with the deslopped 142-char version, (b) add a `Conventions` entry to the nav (the file at `docs/conventions.md` is written in Task 9).

- [ ] **Step 1: Replace `site_description`**

```diff
- site_description = "Nine Claude Code skills. One /plugin install. Sister-repo hygiene, audit pipelines, doc/code drift checks, and CI noise control."
+ site_description = "Opinionated Claude Code skills for repo hygiene: audit pipelines, hunt doc/code drift, tame CI noise, sync linked repos. One /plugin install."
```

- [ ] **Step 2: Insert Conventions into the `nav` block**

The current `nav` is:

```toml
nav = [
  { "Home" = "index.md" },
  { "Getting Started" = "getting-started.md" },
  { "Skills" = [
      { "Overview" = "skills/index.md" },
      { "audit" = "skills/audit.md" },
      ...
  ]},
  { "Architecture" = "architecture.md" },
  { "Examples" = "examples.md" },
  { "Configuration" = "configuration.md" },
]
```

Insert `{ "Conventions" = "conventions.md" },` immediately after the `Examples` entry and before `Configuration`. The result:

```toml
  { "Architecture" = "architecture.md" },
  { "Examples" = "examples.md" },
  { "Conventions" = "conventions.md" },
  { "Configuration" = "configuration.md" },
```

- [ ] **Step 3: Verify**

Run: `grep -nE 'Nine|Conventions' zensical.toml`
Expected: `Conventions` listed; no `Nine` hits.

- [ ] **Step 4: Commit**

The nav references a file that doesn't exist yet — the commit is safe but the site won't render Conventions until Task 9 lands. Acceptable interleaving since Tasks 3-13 will be merged together before any deploy.

```bash
git add zensical.toml
git commit -m "docs(zensical): generalize site_description; nav slot for Conventions guide"
```

---

## Task 6: Generalize portable SKILL.md descriptions

**Files:**
- Modify: `plugins/techne/skills/sisters/SKILL.md` (description rewrite)
- Sweep: `plugins/techne/skills/{auto-commit,ci-audit,deslop,docs-site,docsync,reslop,theoros}/SKILL.md` for AJ-coded references in their `description:` frontmatter lines and inline body prose.
- Hold: `plugins/techne/skills/audit/SKILL.md` (handled in Task 7 — needs the convention-pointer caveat).

- [ ] **Step 1: Rewrite `sisters` description**

Current description (frontmatter `description:` line at `plugins/techne/skills/sisters/SKILL.md:3`):

> Cross-repo drift audit across AJ's sister repos (currently phalanx-fl, vFL, kourai-khryseai; configured in `~/.claude/techne.toml`). Read-only inspection of CI action pins, toolchain pins in pyproject.toml, skill-context structural parity, GitHub merge settings, open PRs, and branch hygiene. Triggers on phrases like "audit the sisters", "are the sisters in sync", "check cross-repo drift", or when multiple sister repos are mentioned together for a consistency check.

New description (preserve trigger phrases verbatim — they're functional for skill activation):

> Cross-repo drift audit across linked repos listed in `~/.claude/techne.toml` (configurable per-user). Read-only inspection of CI action pins, toolchain pins in pyproject.toml, skill-context structural parity, GitHub merge settings, open PRs, and branch hygiene. Triggers on phrases like "audit the sisters", "are the sisters in sync", "check cross-repo drift", or when multiple sister repos are mentioned together for a consistency check.

- [ ] **Step 2: Sweep the other portable SKILL.md frontmatter for AJ-coded references**

Run: `grep -nE "AJ's|ajbarea|phalanx-fl|kourai-khryseai|vFL" plugins/techne/skills/{auto-commit,ci-audit,deslop,docs-site,docsync,reslop,theoros}/SKILL.md`
For each hit, rewrite the surrounding sentence to use neutral framing.

Specific known cases (verify against current files):
- `theoros/SKILL.md`: body mentions `kourai-khryseai` as the "worked reference" for tier-2 scaffolding. Keep one such reference — it's a citation to a real worked example, not personal framing — but make sure it reads as "see kourai-khryseai for a worked example" rather than "AJ's kourai-khryseai."
- Body prose inside the SKILL.md files (not just frontmatter) — sweep for "AJ's" and similar.

Preserve all trigger phrases verbatim; they're functional.

- [ ] **Step 3: Verify**

Run: `grep -rnE "AJ's|ajbarea|phalanx-fl|kourai-khryseai|vFL" plugins/techne/skills/{auto-commit,ci-audit,deslop,docs-site,docsync,reslop,sisters,theoros}/SKILL.md`
Expected: at most one hit (the kourai-khryseai worked-example reference in `theoros/SKILL.md`).

- [ ] **Step 4: Commit**

```bash
git add plugins/techne/skills/
git commit -m "feat(skills): generalize portable SKILL.md descriptions; preserve trigger phrases"
```

---

## Task 7: Update `audit` SKILL.md with convention caveat + body pointer

**Files:**
- Modify: `plugins/techne/skills/audit/SKILL.md`

Two changes: (a) append a one-clause caveat to the description pointing at the new Conventions guide, (b) update the body's "this skill needs a skill-context.md" pointer to reference `docs/conventions.md` as the canonical authority.

- [ ] **Step 1: Append convention caveat to description**

The current description (frontmatter line 3) ends with `"phrasings like "run the audit", "is the build clean", "check my toolchain", "am I ready to push", "make sure CI will pass", "verify make targets".`

Append immediately after the final period:

> Requires the `logs/dev-<ts>-<cmd>.log` archive convention; see `docs/conventions.md`.

- [ ] **Step 2: Update body pointer**

Locate the body section after the "## Repo context" fence (around lines 14-25 of the current file). The skill currently tells the user to "add one with at minimum an `## audit` section." Update to:

> If `.claude/skill-context.md` is missing or has no `## audit` section, abort and direct the user to `docs/conventions.md` in the techne docs (or the `.github-template/` reference materials shipped with the plugin) for the canonical scaffolding template.

- [ ] **Step 3: Verify**

Run: `grep -n 'conventions.md' plugins/techne/skills/audit/SKILL.md`
Expected: two hits (one in description, one in body).

- [ ] **Step 4: Commit**

```bash
git add plugins/techne/skills/audit/SKILL.md
git commit -m "feat(skills/audit): point at docs/conventions.md as the canonical scaffolding source"
```

---

## Task 8: Write `scripts/dev-runner.sh`

**Files:**
- Create: `scripts/dev-runner.sh`

The reference script users `cp` into their own repo's `scripts/`. It wraps a single `make <target>` invocation: streams output to terminal and to a timestamped archive at `logs/dev-<UTC-timestamp>-<target>.log`, appending a `SUMMARY` block that the `audit` skill diffs against the terminal exit code.

- [ ] **Step 1: Create `scripts/` if it doesn't exist**

Run: `ls -ld scripts/`
If missing, run: `mkdir -p scripts`

- [ ] **Step 2: Write `scripts/dev-runner.sh`**

Full content:

```bash
#!/usr/bin/env bash
# techne dev-runner — wraps `make <target>` invocations and writes archives
# under logs/dev-<UTC-timestamp>-<target>.log with a SUMMARY block at the tail
# that techne:audit diffs against the terminal exit code.
#
# Usage:
#   ./scripts/dev-runner.sh <make-target>
#
# Drop-in: copy this file into your repo's scripts/ and call it from
# Makefile targets, or invoke directly. The script does not edit anything
# outside logs/.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <make-target>" >&2
  exit 64
fi

TARGET="$1"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="logs"
ARCHIVE="${LOG_DIR}/dev-${TS}-${TARGET}.log"
LATEST="${LOG_DIR}/dev-latest.log"

mkdir -p "$LOG_DIR"

# Truncate the stable-name pointer before each run; archives are append-only.
: > "$LATEST"

START_NS="$(date +%s%N)"

# Run the make target. Tee stdout+stderr to the archive and the stable pointer
# concurrently so the user sees live output while archives accumulate.
set +e
make "$TARGET" 2>&1 | tee -a "$ARCHIVE" "$LATEST"
RC=${PIPESTATUS[0]}
set -e

END_NS="$(date +%s%N)"
ELAPSED_SEC="$(awk -v s="$START_NS" -v e="$END_NS" 'BEGIN { printf "%.2f", (e - s) / 1e9 }')"

STATUS="PASS"
STEPS_FAILED=0
if [[ $RC -ne 0 ]]; then
  STATUS="FAIL"
  STEPS_FAILED=1
fi

{
  echo ""
  echo "=============================================================================="
  echo "SUMMARY"
  echo "=============================================================================="
  echo "total elapsed : ${ELAPSED_SEC}s"
  echo "steps run     : 1"
  echo "steps failed  : ${STEPS_FAILED}"
  echo "overall rc    : ${RC}"
  echo ""
  echo "per-step:"
  printf "  %s  rc=%d  %ss  %s\n" "$STATUS" "$RC" "$ELAPSED_SEC" "$TARGET"
  echo "=============================================================================="
} | tee -a "$ARCHIVE" "$LATEST"

exit "$RC"
```

- [ ] **Step 3: Make it executable**

```bash
chmod +x scripts/dev-runner.sh
```

- [ ] **Step 4: Smoke-test the script against an existing Make target**

Run from the techne repo (which has no Makefile, so the script should fail with a clear `make` error, not crash):

```bash
./scripts/dev-runner.sh nonexistent-target 2>&1 | tail -20
```

Expected: prints a `make: *** No rule to make target` message, then a `SUMMARY` block with `overall rc : 2` and `steps failed : 1`. The archive at `logs/dev-*-nonexistent-target.log` should exist.

Clean up the test artifacts after smoke:

```bash
rm -rf logs/
```

- [ ] **Step 5: Commit**

```bash
git add scripts/dev-runner.sh
git commit -m "feat(scripts): add reference dev-runner for the audit-skill archive convention"
```

---

## Task 9: Write `.github-template/workflows/docs.yml`

**Files:**
- Create: `.github-template/workflows/docs.yml`

The reference Pages workflow under `.github-template/` (deliberately not `.github/` — that path already has techne's own active workflow). Users `cp .github-template/workflows/docs.yml .github/workflows/` to adopt.

- [ ] **Step 1: Read techne's existing Pages workflow as reference**

Run: `ls .github/workflows/`
Expected: one or more workflow files; the docs deploy workflow should already exist.

Run: `cat .github/workflows/<docs-workflow>.yml`

Use the existing workflow as the basis for the reference; strip anything techne-specific. (If techne's workflow IS the canonical reference, copy it verbatim — but verify nothing AJ-coded leaks.)

- [ ] **Step 2: Create the template directory and write the workflow**

```bash
mkdir -p .github-template/workflows
```

Write `.github-template/workflows/docs.yml` based on techne's own workflow with these adaptations:

- Strip any AJ-coded comments
- Use `${{ github.repository }}` rather than hardcoded `ajbarea/techne` if any hardcoded refs exist
- Keep the standard pattern: checkout, install uv, `zensical build --clean`, upload artifact, deploy to Pages

Reference shape (verify against the actual file):

```yaml
name: Deploy docs site

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Build site
        run: uv run --group dev zensical build --clean
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

Pin all `uses:` action versions to the same values techne's own workflow currently uses (verified during Step 1). The user can re-pin after copying.

- [ ] **Step 3: Verify nothing AJ-coded leaks**

Run: `grep -nE "ajbarea|AJ|ajbar|ajsoftworks" .github-template/workflows/docs.yml`
Expected: empty.

- [ ] **Step 4: Commit**

```bash
git add .github-template/workflows/docs.yml
git commit -m "feat(template): ship reference Pages workflow under .github-template/"
```

---

## Task 10: Write `docs/conventions.md`

**Files:**
- Create: `docs/conventions.md`

The largest new artifact. Teaches the four conventions techne assumes: Makefile pattern, dev-runner archive, `.claude/skill-context.md` skeleton, `~/.claude/techne.toml`. References `scripts/dev-runner.sh` (Task 8) and `.github-template/workflows/docs.yml` (Task 9). Cross-refs the per-skill dependencies.

- [ ] **Step 1: Write `docs/conventions.md`**

Full content:

````markdown
# Conventions

Techne is opinionated. The skills assume a few conventions about how your repo is wired. This guide names them and shows the minimum each skill needs to work.

Each section flags which skill(s) depend on it. A repo can adopt only what it uses.

## The Makefile pattern

Techne's skills invoke your toolchain through `make` targets, not through raw tool commands. Wrap your build, lint, test, and check pipelines behind one-word targets:

```makefile
.PHONY: setup lint test ci

setup:
	uv sync --group dev

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest

ci: lint test
```

The interface is stable across heterogeneous tools (uv, npm, cargo, just, raw shell), CI-friendly, and self-documenting via `make help` if you adopt one of the standard help patterns.

**Required for:** `techne:audit`.
**Recommended for:** `techne:ci-audit`, `techne:theoros`.

## The dev-runner archive

`techne:audit` doesn't run `make` directly — it diffs your terminal exit code against a per-invocation log archive. Each `make <target>` produces `logs/dev-<UTC-timestamp>-<target>.log` ending with a `SUMMARY` block:

```
==============================================================================
SUMMARY
==============================================================================
total elapsed : 3.96s
steps run     : 1
steps failed  : 0
overall rc    : 0

per-step:
  PASS  rc=0     3.93s  lint
==============================================================================
```

Techne ships `scripts/dev-runner.sh` as a reference implementation. Copy it into your repo:

```bash
cp <path-to-techne>/scripts/dev-runner.sh scripts/
chmod +x scripts/dev-runner.sh
```

Then call it from your Makefile targets (or invoke directly):

```makefile
lint:
	@./scripts/dev-runner.sh lint
```

**Required for:** `techne:audit`.

## `.claude/skill-context.md` — per-repo skill config

Several skills read a single per-repo file at `.claude/skill-context.md`. This is the copy-pasteable skeleton:

````markdown
# Skill context

## repo
<one-paragraph description of what this repo is and who uses it>

## audit (techne:audit)
phases:
  - setup
  - lint
  - test
  - ci
fast_subset: [lint, test]
stop_early: [setup]
log_archive_glob: "logs/dev-*-{phase}.log"
do_not_run: []

## ci_audit (techne:ci-audit)
workflows_path: ".github/workflows"
ignore_warnings: []

## slop_ground_truth (techne:deslop / techne:reslop / techne:docsync)
authoritative_sources:
  - "src/"
  - "tests/"
test_locations:
  - "tests/"

## scan_scope (techne:deslop / techne:reslop)
include:
  - "src/"
  - "docs/"
exclude:
  - "site/"
  - ".venv/"

## docs_site (techne:docs-site)
config: "zensical.toml"
deploy_workflow: ".github/workflows/docs.yml"
build_command: "uv run --group dev zensical build --clean"

## theoros (techne:theoros)
```yaml
repl_command: <your repo's REPL command>
session_name: <your-repo-slug>-theoros
```
````

Each `##` section maps to one skill family. Adopt only the sections for the skills you intend to use; absent sections trigger a "skill needs scaffolding" message instead of a silent failure.

**Required for:** `techne:audit`, `techne:sisters`, `techne:theoros`.
**Recommended for:** `techne:deslop`, `techne:reslop`, `techne:docsync`, `techne:docs-site`, `techne:ci-audit`.

## `~/.claude/techne.toml` — user-level sister config

`techne:sisters` reads a user-level config file at `~/.claude/techne.toml` that lists the repos to audit drift across. See the **Configuration** section of the README for the worked example.

**Required for:** `techne:sisters`.

## `COMMITS.md` — local commit draft

`techne:auto-commit` writes a draft commit plan to `COMMITS.md` in your repo root. Gitignore it:

```
# techne:auto-commit local scratchpad
COMMITS.md
```

The file is intentionally local-only and is rewritten on every run.

**Required for:** `techne:auto-commit`.

## The docs-site workflow

`techne:docs-site` manages a Zensical-built GitHub Pages workflow. Techne ships a reference workflow at `.github-template/workflows/docs.yml`. Copy it into your repo:

```bash
cp <path-to-techne>/.github-template/workflows/docs.yml .github/workflows/
```

Then enable Pages in your GitHub repo settings (Settings → Pages → Source: GitHub Actions). The workflow runs on every push to `main` and on manual dispatch.

**Required for:** `techne:docs-site`.

## Adopting incrementally

You don't need all conventions at once. Common starting points:

- **Just want commit drafting?** Adopt the `COMMITS.md` gitignore line. That's it.
- **Want the audit pipeline?** Adopt the Makefile pattern + `scripts/dev-runner.sh` + the `## audit` section of skill-context.md.
- **Want cross-repo drift checks?** Adopt `~/.claude/techne.toml`. Sisters works without skill-context.md.
- **Want the full kit?** Adopt all conventions and the docs site workflow.
````

- [ ] **Step 2: Verify**

Run: `wc -l docs/conventions.md`
Expected: ~150-200 lines (substantive but not bloated).

Run: `grep -nE 'ajbarea|AJ|phalanx-fl|kourai-khryseai|vFL|/home/ajbar' docs/conventions.md`
Expected: empty.

Run: `grep -nE '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]' docs/conventions.md`
Expected: empty (no emoji).

Run: `grep -nE '[—–]' docs/conventions.md`
Expected: empty (no em-dashes or en-dashes).

- [ ] **Step 3: Commit**

```bash
git add docs/conventions.md
git commit -m "docs: add Conventions guide teaching the four techne conventions"
```

---

## Task 11: Cross-link Conventions guide from `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add cross-link in the Install section**

After the existing `## Install` block, before `## Configuration`, add:

```markdown
> **First-time setup:** techne is opinionated about a few conventions (Makefile pattern, dev-runner archive, `.claude/skill-context.md`). See [Conventions](docs/conventions.md) for the minimum each skill needs.
```

- [ ] **Step 2: Verify**

Run: `grep -n 'docs/conventions.md' README.md`
Expected: at least one hit.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): cross-link Conventions guide from install section"
```

---

## Task 12: Deslop `docs/architecture.md`

**Files:**
- Modify: `docs/architecture.md` (~190 → ~80-100 lines)

Replace ASCII-art tree, emoji section headers, and padded workflows with terse prose. Preserve the concept structure (Build / Documentation / Versioning / Multi-Repo) and the four typical workflows. Drop the four-numbered "Design philosophy" in favor of a single short paragraph.

- [ ] **Step 1: Rewrite the file**

Replace the entire contents with the following structure (the executor writes the prose against the spec's Section 4 acceptance criteria — no emoji, no em-dashes, no fragile counts, no marketing padding):

```markdown
# Architecture

Techne is a collection of independent, composable skills that share conventions but don't hard-depend on each other. This page maps the skill ecosystem, names the typical workflows, and states the design philosophy.

## Skill categories

**Build and toolchain.** `techne:audit` validates that your local build is clean (lint, test, end-to-end) by walking your Makefile dependency graph and diffing terminal output against per-invocation log archives. `techne:ci-audit` does the same for GitHub Actions runs — flags warnings, deprecations, and noise; fixes what's fixable in-repo (workflow YAML, action pins, dependency versions).

**Documentation and prose.** `techne:docs-site` maintains the Zensical-built Pages workflow, link integrity, and asset hygiene. `techne:docsync` verifies prose claims (CLI commands, paths, signatures, config keys) against the actual codebase. `techne:deslop` flags AI-generated slop in comments and docstrings; `techne:reslop` rewrites docstrings grounded in the implementation rather than deleting them outright.

**Versioning and observability.** `techne:auto-commit` groups working-tree changes into a structured commit plan at `COMMITS.md` for staged review before anything lands. `techne:theoros` starts an observed live dev session in a tmux pane — Claude drives the REPL, the human spectates read-only via `tmux attach -r`.

**Cross-repo consistency.** `techne:sisters` audits drift across the repos listed in `~/.claude/techne.toml` — CI action pins, toolchain pins, skill-context structural parity, GitHub merge settings, open PRs, branch hygiene. Read-only; reports findings, leaves fixes to follow-up work.

## Typical workflows

**Pre-push validation.** Group local changes with `techne:auto-commit`, validate the build with `techne:audit`, scan for prose slop with `techne:deslop`, push. When CI finishes, run `techne:ci-audit` against the run for warnings and deprecations.

**Documentation accuracy.** After a refactor, run `techne:docsync` to find stale claims. Review the drift report; rewrite affected docstrings with `techne:reslop` if rewrite is preferable to deletion. Run `techne:docs-site` to confirm link integrity hasn't regressed.

**Multi-repo release.** Run `techne:sisters` to surface CI/toolchain/branch drift across the linked repos. Fix the drift in each repo (action pins, Python versions, merge settings). Validate each with `techne:audit`. Coordinate merges in consistent order.

**Observed session.** For long-running tasks (multi-hour test suites, large refactors), spin up a tmux session with `techne:theoros`. Share the session name; collaborators attach read-only with `tmux attach -r -t <session>`. The transcript persists in tmux scrollback.

## Design philosophy

Skills are independent — each invocable without the others — but share conventions: `.claude/skill-context.md` for per-repo config, `~/.claude/techne.toml` for user-level config, the dev-runner log archive at `logs/dev-*.log`. Every skill writes a plan, report, or diff to disk first, then waits for human review before mutating the repo. Read-only audits + explicit human approval; never silent edits. See [Conventions](conventions.md) for the standard file locations and adoption path.

## See also

- [Conventions](conventions.md) — the standard file locations and adoption path
- [Examples](examples.md) — concrete workflows using the skills together
- [Skills reference](skills/index.md) — per-skill detail pages
```

- [ ] **Step 2: Verify**

Run: `wc -l docs/architecture.md`
Expected: ~80-100 lines (significantly shorter than the previous ~190).

Run: `grep -nE '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]' docs/architecture.md`
Expected: empty.

Run: `grep -nE '[—–]' docs/architecture.md`
Expected: empty.

Run: `grep -nE '\b(nine|9|six|6|eight|8|ten|10)\b' docs/architecture.md`
Expected: empty.

Run: `grep -nE 'AJ|ajbarea|phalanx-fl|kourai-khryseai|vFL' docs/architecture.md`
Expected: empty.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs(architecture): deslop rewrite, drop ASCII art, generalize prose"
```

---

## Task 13: Deslop `docs/examples.md`

**Files:**
- Modify: `docs/examples.md` (~390 → ~150-200 lines)

The largest single rewrite. Beyond deslop cosmetics, fixes hallucinated CLI flags (`/audit --verbose`, `/sisters --report-only`, `/reslop --file src/api.py`, `/deslop docs/ src/`) and fabricated output blocks. Replaces AJ-coded paths with placeholders. Tightens each of the six workflows.

- [ ] **Step 1: Rewrite the file**

Replace the entire contents with the following structure. The executor writes the prose against the spec's Section 4 acceptance criteria. Six workflows preserved, each tightened to ~20-30 lines. Output blocks are prose descriptions, not fabricated literal output. No emoji, no em-dashes, no fragile counts, no hallucinated flags.

```markdown
# Examples

Concrete workflows combining techne skills. Each one is a recipe for a real problem; the skill invocations match actual behavior, not hypothetical flags.

## Cross-repo consistency audit

You maintain a few related repos and want to make sure their CI pins, toolchain versions, and merge settings haven't drifted apart.

1. Configure the linked repos in `~/.claude/techne.toml` (see [Configuration](configuration.md)).
2. Run `/techne:sisters`.
3. Read the drift report. It groups findings by category — action-pin drift, toolchain-pin drift, GitHub merge-setting drift, open PRs, stale branches, local `main` divergence.
4. Apply fixes in each repo. Re-run `/techne:sisters` to confirm the drift is gone.

The skill is read-only; you commit the fixes manually.

## Pre-release documentation audit

Before tagging a release, verify your prose claims still match the code.

1. Run `/techne:docsync`. It surfaces stale claims: CLI flags that no longer exist, function signatures that have changed, configuration keys that have moved.
2. Review the drift report grouped by file.
3. For docstrings that are wrong but should be kept (not deleted), run `/techne:reslop` on the affected file; it rewrites the docstring grounded in the actual implementation.
4. Run `/techne:docs-site` to verify your published docs site builds clean and links resolve.
5. Tag and release once docs and code align.

## Clean multi-commit PR

You've been refactoring for days; the working tree has changes across many files and several logical concerns.

1. Run `/techne:auto-commit`. It writes a `COMMITS.md` plan grouping changes into conventional commits with proposed messages.
2. Review and edit `COMMITS.md` directly — re-group, rename, add detail, drop noise.
3. Run `/techne:deslop` to scan source comments and docstrings for AI-generated slop introduced during the refactor. Apply the suggested rewrites.
4. Run `/techne:audit` to validate lint, test, and any other Make targets pass.
5. Approve the commit plan; the skill stages files per commit, creates the commits, and pushes.
6. After CI finishes, run `/techne:ci-audit` to triage any new warnings or deprecations the workflow surfaced.

## Observed pairing session

A collaborator wants to watch you refactor a complex module in real time without driving the terminal.

1. Add a `## theoros` section to `.claude/skill-context.md` listing your REPL command and a session name (see [Conventions](conventions.md)).
2. Run `/techne:theoros`. It starts a detached tmux session named per the config.
3. Share the session name with collaborators. They attach read-only: `tmux attach -r -t <session-name>`.
4. You drive the work through Claude; collaborators see live output. The split-window layout is optional — add an `ops_command` to the skill-context if you want a tailing logs pane underneath the driver pane.
5. Tear down with `make theoros-down` (if you've adopted the tier-2 Makefile targets) or `tmux kill-session -t <session-name>`.

## CI noise cleanup

Your workflow is green but the run log is full of warnings: deprecated action versions, deprecation notices from third-party tools, policy-driven noise.

1. Run `/techne:ci-audit` against the latest workflow run on your branch. It categorizes findings: fixable in-repo (action pins, Python version, workflow YAML), unfixable / policy (bot output, security scanners), and noise.
2. Apply the in-repo fixes via the skill's proposed edits — typically workflow YAML pin bumps, occasional `pyproject.toml` Python-version updates.
3. Review with `git diff .github/`.
4. Commit and push with `/techne:auto-commit`.
5. Re-run CI; verify the warning count drops.

## Cross-repo API consistency

Three related codebases expose similar APIs, but the docs and signatures have drifted.

1. In each repo, run `/techne:docsync`. Each produces a per-repo drift report against its own docs.
2. Compare the three reports side-by-side; either standardize the docs (when the APIs should match) or update each repo's docs to clarify intentional differences.
3. Run `/techne:sisters` to confirm toolchain and CI pins are consistent across the three (mismatched dependencies can mask API-level drift as version drift).

## Tips for combining skills

- Run `/techne:auto-commit` before `/techne:deslop`, so the commit grouping reflects your work rather than the slop rewrite.
- Run `/techne:audit` before `/techne:ci-audit` to separate "is the local build clean" from "is CI clean."
- Run `/techne:docsync` before releases — drift between docs and code is the source of most "didn't they fix this?" bug reports.
- Run `/techne:sisters` after multi-repo refactors so the linked repos stay coherent.
- Use `/techne:theoros` for long-running operations where a collaborator wants async visibility without driving.

## See also

- [Architecture](architecture.md) — how the skills fit together
- [Conventions](conventions.md) — the file locations and patterns each skill assumes
- [Skills reference](skills/index.md) — per-skill detail
```

- [ ] **Step 2: Verify**

Run: `wc -l docs/examples.md`
Expected: ~150-200 lines.

Run: `grep -nE '/techne:[a-z-]+ --[a-z-]+' docs/examples.md`
Expected: empty (no hallucinated CLI flags).

Run: `grep -nE '/audit --|/sisters --|/reslop --|/deslop --' docs/examples.md`
Expected: empty.

Run: `grep -nE '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]' docs/examples.md`
Expected: empty.

Run: `grep -nE '[—–]' docs/examples.md`
Expected: empty.

Run: `grep -nE 'ajbarea|phalanx-fl|kourai-khryseai|vFL|/home/ajbar' docs/examples.md`
Expected: empty.

Run: `grep -nE '\bsix\b|\b6 workflows\b' docs/examples.md`
Expected: empty.

- [ ] **Step 3: Commit**

```bash
git add docs/examples.md
git commit -m "docs(examples): deslop rewrite, fix hallucinated flags, generalize repo names"
```

---

## Task 14: Deslop each `docs/skills/*.md`

**Files:**
- Modify: `docs/skills/audit.md`
- Modify: `docs/skills/auto-commit.md`
- Modify: `docs/skills/ci-audit.md`
- Modify: `docs/skills/deslop.md`
- Modify: `docs/skills/docs-site.md`
- Modify: `docs/skills/docsync.md`
- Modify: `docs/skills/reslop.md`
- Modify: `docs/skills/sisters.md`
- Modify: `docs/skills/theoros.md`

Each was inflated from ~32 to ~80 lines with duplicated SKILL.md content + invented features. Strip duplication; target ~40-50 lines each. The nine files are independent rewrites; safe to parallelize across subagents if using subagent-driven-development.

Per-file pattern:

- **Keep:** title, 1-2 line overview, "when to use" if it adds beyond the frontmatter, real usage example, `.claude/skill-context.md` configuration pointer (cross-link to Conventions), terse "See also" list.
- **Drop:** invented `--flag` arguments throughout, invented "Troubleshooting" sections with fabricated error scenarios, "Reads:" sections that just enumerate file paths users won't care about, padded "See also" lists.
- **Cross-link:** [Conventions](../conventions.md) for setup, related skills, the SKILL.md source under the plugin path.

- [ ] **Step 1: Rewrite each `docs/skills/*.md` against the per-file pattern**

The executor handles each file as a separate subagent dispatch (or sequentially). For each file:

1. Read the current `docs/skills/<name>.md` and the corresponding `plugins/techne/skills/<name>/SKILL.md`.
2. The docs page should be a *user-facing summary*, not a re-rendering of the SKILL.md. The SKILL.md frontmatter and body are read by Claude; the docs page is read by humans browsing the site.
3. Rewrite to ~40-50 lines following the keep/drop rules above.
4. Verify against the acceptance grep (no emoji, no em-dashes, no fabricated flags, no AJ-coded examples, no fragile counts).

Example target shape for `docs/skills/audit.md`:

```markdown
# `techne:audit`

Run your repo's `make` targets in dependency order and reconcile terminal output against the `logs/dev-<ts>-<cmd>.log` archive convention.

## When to use

Pre-push: validate the toolchain is clean before pushing to CI. "Is the build clean?" / "Am I ready to push?" / "Did the last refactor break anything silently?"

## Usage

Invoke by name in Claude Code:

```
/techne:audit
```

Modes are picked from natural-language phrasing. Say "run the full audit" or "fast check"; the skill reads the phase list and fast-subset from your `.claude/skill-context.md`.

## Prerequisites

This skill is opinionated. It requires:

- A `Makefile` with the phases listed in your `.claude/skill-context.md`'s `## audit` section.
- The dev-runner archive convention: each `make <target>` invocation writes `logs/dev-<UTC-timestamp>-<target>.log` ending with a `SUMMARY` block. Techne ships `scripts/dev-runner.sh` as the reference implementation.

See [Conventions](../conventions.md) for the setup walkthrough.

## See also

- [`techne:ci-audit`](ci-audit.md) — audit the cloud equivalent (GitHub Actions runs).
- [`techne:docsync`](docsync.md) — audit prose claims (Makefile commands, paths) against the code.
- [Conventions](../conventions.md) — the dev-runner archive convention.
```

Apply the equivalent pattern to each of the other eight skill docs. The SKILL.md file's frontmatter description is the authoritative one-liner; the docs page rephrases for human readers.

- [ ] **Step 2: Verify each file**

For each `docs/skills/*.md`:

Run: `wc -l docs/skills/<name>.md`
Expected: ~40-55 lines.

Run: `grep -nE '/techne:[a-z-]+ --[a-z-]+' docs/skills/<name>.md`
Expected: empty.

Run: `grep -nE '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]|[—–]' docs/skills/<name>.md`
Expected: empty.

Run: `grep -nE 'AJ|ajbarea|phalanx-fl|kourai-khryseai|vFL' docs/skills/<name>.md`
Expected: empty (with one possible kourai-khryseai exception in `theoros.md` if the worked-example reference is preserved).

- [ ] **Step 3: Commit (per-file or batched)**

If executing serially, batch all into one commit at the end:

```bash
git add docs/skills/
git commit -m "docs(skills): deslop per-skill docs; strip duplication and hallucinated flags"
```

If parallelizing across subagents, one commit per file with the same prefix is also fine.

---

## Task 15: Run repo-wide acceptance grep checks

**Files:**
- Read-only verification across `docs/`, `README.md`, `zensical.toml`.

- [ ] **Step 1: Emoji grep across user-facing docs**

```bash
grep -rnE '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]' docs/ README.md --exclude-dir=superpowers
```
Expected: empty output.

- [ ] **Step 2: Em-dash / en-dash grep across user-facing docs**

```bash
grep -rnE '[—–]' docs/ README.md zensical.toml --exclude-dir=superpowers
```
Expected: empty output.

- [ ] **Step 3: Fragile-count grep adjacent to skill terms**

```bash
grep -rnEi '\b(nine|9|six|6|eight|8|ten|10)\b.*(skills|workflows|features|agents|datasets)' docs/ README.md zensical.toml --exclude-dir=superpowers
```
Expected: empty (or only matches load-bearing context, e.g., a deliberate hero stat — review each hit).

- [ ] **Step 4: Hallucinated-flag grep**

```bash
grep -rnE '/techne:[a-z-]+ --[a-z-]+' docs/ README.md --exclude-dir=superpowers
grep -rnE '/audit --|/sisters --|/reslop --|/deslop --|/docsync --|/ci-audit --|/auto-commit --|/docs-site --|/theoros --' docs/ README.md --exclude-dir=superpowers
```
Expected: empty for both.

- [ ] **Step 5: AJ-coded reference grep**

```bash
grep -rnE 'ajbarea|/home/ajbar|phalanx-fl|kourai-khryseai|vFL' docs/ README.md zensical.toml pyproject.toml --exclude-dir=superpowers
```
Expected: empty across user-facing docs. (Internal artifacts under `docs/superpowers/**` retain AJ-coded references for accuracy; they're excluded.)

- [ ] **Step 6: If any grep returns hits, fix them inline and re-run**

Do not proceed to Task 16 until all five greps return empty for the user-facing scope.

- [ ] **Step 7: Commit if any fixes were applied**

```bash
git add -A docs/ README.md zensical.toml pyproject.toml
git commit -m "docs: address residual acceptance-grep findings"
```

If no fixes were needed, skip the commit.

---

## Task 16: Smoke-test the plugin end-to-end

**Files:**
- Read-only smoke test against the techne repo itself.

The goal: confirm the plugin still installs and the skills still load after the refresh, and that the README install command actually works from a clean Claude Code session.

- [ ] **Step 1: Verify marketplace.json + SKILL.md frontmatter are syntactically valid**

```bash
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))" && echo "marketplace.json valid"
```
Expected: `marketplace.json valid`.

For each SKILL.md file, verify the YAML frontmatter parses:

```bash
for f in plugins/techne/skills/*/SKILL.md; do
  echo "=== $f ==="
  python3 -c "
import sys, yaml
content = open('$f').read()
if not content.startswith('---'):
    sys.exit('no frontmatter')
end = content.index('---', 3)
yaml.safe_load(content[3:end])
print('ok')
"
done
```
Expected: each file prints `=== <path> ===` followed by `ok`.

- [ ] **Step 2: Install the plugin from a clean Claude Code session**

Manual step — drive from a fresh `claude` invocation (separate terminal):

```
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

Expected: install completes; the `Discover` tab shows techne with the skills listed.

- [ ] **Step 3: Confirm all skills are surfaced**

In the fresh Claude Code session, list available skills (per the session UI). Verify the techne-namespaced skills appear: `techne:audit`, `techne:auto-commit`, `techne:ci-audit`, `techne:deslop`, `techne:docs-site`, `techne:docsync`, `techne:reslop`, `techne:sisters`, `techne:theoros`.

If any are missing, debug the SKILL.md frontmatter (most likely cause: a YAML parse error from the previous editing pass).

- [ ] **Step 4: Run one skill against a real repo**

Pick a repo that has the dev-runner archive convention (e.g., one of AJ's existing repos like kourai-khryseai or phalanx-fl, or this techne repo if it has a Makefile). From the Claude Code session in that repo's directory:

```
/techne:audit
```

Expected: the skill reads `.claude/skill-context.md`, runs the phases, diffs against archives, and prints a verdict.

If the skill aborts because `.claude/skill-context.md` is missing or malformed, that's expected and informative — it means the prerequisite is being enforced as the spec intends.

- [ ] **Step 5: Document any unexpected behavior**

If a skill misbehaves, capture the symptom and address inline. If the refresh accidentally broke a skill, the most likely culprit is a SKILL.md frontmatter edit in Tasks 6 or 7 — diff the file against `HEAD~N` to find the change.

---

## Task 17: Verify Pages site builds clean

**Files:**
- Read-only verification of the built site.

- [ ] **Step 1: Build the site locally**

```bash
uv run --group dev zensical build --clean
```
Expected: build completes without errors. The `site/` directory is regenerated.

- [ ] **Step 2: Verify the Conventions page renders**

Run: `ls site/conventions/`
Expected: `index.html` present (or similar Zensical-default structure).

Run: `grep -lE 'Conventions' site/index.html`
Expected: the home page or nav references the Conventions page.

- [ ] **Step 3: Verify the deslopped pages don't have orphan emoji or em-dashes in the rendered HTML**

```bash
grep -rE '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]|[—–]' site/architecture/ site/examples/ site/skills/ 2>/dev/null | head
```
Expected: empty or only matches in code-fence content (verify by inspection).

- [ ] **Step 4: Confirm `docs/superpowers/**` was NOT rendered as orphan pages**

Run: `ls site/superpowers 2>&1`
Expected: "No such file or directory".

If zensical did render superpowers pages, add an exclude rule to `zensical.toml` and rebuild:

```toml
[project.plugins.exclude]
patterns = ["superpowers/**"]
```

(Verify the exact zensical config key for excludes against the zensical 2026 documentation — the key name may differ from `patterns`.)

- [ ] **Step 5: Commit any config fixes**

If the exclude rule was added:

```bash
git add zensical.toml
git commit -m "docs(zensical): exclude docs/superpowers/** from rendered site"
```

---

## Task 18: Final pre-review readiness check

**Files:**
- Read-only summary.

A meta-task that asserts the spec's Acceptance Criteria rollup is satisfied.

- [ ] **Step 1: Walk the Acceptance Criteria from the spec**

For each item in the spec's `## Acceptance criteria (rollup)` section, verify by file/grep:

1. The three slop files are deleted, `.gitignore` updated — `ls COMMITS.md IMPROVEMENTS.md DEPLOYMENT_READY.md 2>&1` → 3× missing.
2. `docs/conventions.md` exists and teaches the four conventions.
3. `scripts/dev-runner.sh` and `.github-template/workflows/docs.yml` exist.
4. `README.md`, `pyproject.toml`, `marketplace.json`, `zensical.toml`, and the portable SKILL.md frontmatter descriptions are generalized — Task 15 greps confirm.
5. `docs/architecture.md`, `docs/examples.md`, and every `docs/skills/*.md` pass acceptance — Task 15 greps confirm.
6. The theoros spec/plan are at `docs/superpowers/specs/` and `docs/superpowers/plans/`.
7. The Pages site builds clean — Task 17 confirms.

- [ ] **Step 2: Run `/techne:deslop` against the techne repo itself (dogfood)**

In a Claude Code session opened in the techne repo:

```
/techne:deslop
```

Expected: zero or near-zero new findings. Any findings indicate residual slop the executor should address before declaring the refresh done.

- [ ] **Step 3: Surface the readiness summary**

Print a final summary to terminal:

```
=== Techne refresh readiness ===
Slop files removed:        yes / no
.gitignore updated:        yes / no
Conventions guide:         yes / no (line count)
dev-runner.sh:             yes / no (executable)
.github-template/docs.yml: yes / no
README generalized:        yes / no (grep clean)
pyproject generalized:     yes / no
zensical generalized:      yes / no
SKILL.md descriptions:     yes / no (grep clean)
architecture.md:           yes / no (line count, grep clean)
examples.md:               yes / no (line count, grep clean)
docs/skills/*.md:          yes / no (line count, grep clean)
theoros spec/plan relocated: yes / no
Pages site builds clean:   yes / no
deslop dogfood clean:      yes / no
```

- [ ] **Step 4: If everything passes, the refresh is ready for Anthropic's review**

The marketplace form has already been submitted (per the spec's Section 5 status). The refresh lands on `main`; the marketplace listing, once approved, will point at the clean repo. No further action required from the executor.

If any check fails, address inline and re-run Task 15 + Task 18 until clean.

---

## Self-Review Notes

This plan was checked against the spec at `docs/superpowers/specs/2026-05-19-techne-refresh-design.md`:

**Spec coverage:**
- Section 1 (dies/stays/added/rewritten) → Tasks 1, 2, 3-7, 8-14
- Section 2 (Conventions guide) → Tasks 5, 8, 9, 10, 11
- Section 3 (positioning rewrite) → Tasks 3, 4, 5, 6, 7
- Section 4 (docs deslop) → Tasks 12, 13, 14, 15
- Section 5 (marketplace submission path) → Status acknowledged; cleanup ordering reflected in task sequencing; submission form already submitted per the spec's status note. No submission task in the plan (already done by user).

**Placeholder scan:** none found in the plan body. Specific file paths, exact greps, and concrete code blocks throughout.

**Type/identifier consistency:** the skill names (`/techne:*`), filenames, and convention paths match across tasks. The same `logs/dev-<ts>-<cmd>.log` pattern is referenced consistently.

**Scope check:** single implementation plan; all 18 tasks are sequencable in one session or one PR chain. Tasks 14.1-14.9 (per-file skill doc deslop) can parallelize across subagents if using subagent-driven-development.
