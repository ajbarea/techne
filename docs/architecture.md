# Architecture

Techne is a plugin of nine independent, composable skills that audit code, build pipelines, CI workflows, documentation, and cross-repo consistency. This guide explains how they fit together and when to use each in your workflow.

## The Skill Ecosystem

```
┌─────────────────────────────────────────────────────────────┐
│                    Techne Plugin System                      │
└─────────────────────────────────────────────────────────────┘
            
            ┌──────────────────────────────────────┐
            │  Configuration & Observability       │
            │  • ~./.claude/techne.toml            │
            │  • Centralized skill settings        │
            └──────────────────────────────────────┘
                            │
                ┌───────────┼───────────┐
                │           │           │
                ▼           ▼           ▼
            
    ┌──────────────────┐  ┌──────────────────┐
    │   Build & Code   │  │   Docs & Prose   │  
    │   • audit        │  │   • docs-site    │
    │   • ci-audit     │  │   • docsync      │
    │   • deslop       │  │   • deslop       │
    │   • reslop       │  │   • reslop       │
    └──────────────────┘  └──────────────────┘
            │                       │
            │ (local workflows)     │ (doc accuracy)
            │                       │
            └───────────┬───────────┘
                        │
            ┌───────────┴───────────┐
            │                       │
            ▼                       ▼
    ┌──────────────────┐  ┌──────────────────┐
    │  Versioning      │  │  Multi-Repo      │
    │  • auto-commit   │  │  • sisters       │
    │  • theoros       │  │  • docsync       │
    └──────────────────┘  └──────────────────┘
            │                       │
            │ (PRs, commits)        │ (drift audit)
            │                       │
            └───────────┬───────────┘
                        │
                        ▼
                ┌──────────────────┐
                │  Your Workflow   │
                └──────────────────┘
```

## Skill Categories

### 🔧 Build & Toolchain

**`audit`** — Validate your local build is clean before pushing.
- Reads: `Makefile` dependency graph + `logs/dev-*.log` archives
- Use when: "Is the build good?" / pre-push validation
- Pairs well with: `ci-audit` (audit the cloud version)

**`ci-audit`** — Audit GitHub Actions workflow runs for warnings, failures, noise.
- Reads: GitHub Actions logs via `gh` CLI
- Use when: "CI failed" / "what's the warning?" / post-run cleanup
- Pairs well with: `audit` (audit local build)

### 📚 Documentation & Prose

**`docs-site`** — Maintain Zensical site config, deploy, links, assets.
- Reads: `zensical.toml`, `.github/workflows/docs.yml`, CSS/JS files
- Use when: "Site deploy broke" / "nav is stale" / adding new doc pages
- Pairs well with: `docsync` (verify prose accuracy)

**`docsync`** — Verify docs claims (commands, paths, versions) match code.
- Reads: markdown prose + actual source files
- Use when: "Did this command still exist?" / post-refactor drift audit
- Pairs well with: `docs-site` (verify site mechanics)

**`deslop`** — Scan for AI-generated slop in comments, docstrings.
- Reads: source code comments and docstrings
- Use when: "Clean up verbose AI commentary" / pre-release audit
- Pairs well with: `reslop` (rewrite docstrings grounded in code)

**`reslop`** — Rewrite docstrings grounded in actual implementation.
- Reads: function bodies, call sites, tests
- Use when: "This docstring is wrong but needs rewrite, not delete"
- Pairs well with: `deslop` (triage slop first)

### 🔀 Versioning & Observability

**`auto-commit`** — Group working-tree changes into a structured commit plan.
- Reads: working-tree diff
- Use when: "Group changes logically" / "draft commits before pushing"
- Pairs well with: all other skills (works on your current diff)

**`theoros`** — Observed dev session in tmux (Claude drives, you watch).
- Reads: shell environment + skill context
- Use when: "I want to watch without driving" / remote pairing / recording
- Pairs well with: `audit`, `ci-audit` (watch them run)

### 🔗 Multi-Repo Consistency

**`sisters`** — Cross-repo drift audit (CI pins, toolchain, branch hygiene).
- Reads: `~/.claude/techne.toml` + each sister repo's config
- Use when: "Are the sisters in sync?" / multi-repo consistency check
- Pairs well with: all skills (coordinate across repos)

## Typical Workflows

### Workflow 1: Pre-Push Validation

1. **Make local changes** → work on your feature branch
2. **`auto-commit`** → group changes into logical commits, review the `COMMITS.md` plan
3. **`audit`** → validate the build is clean (lint, test, etc.)
4. **`deslop`** → scan comments for slop, tighten prose
5. **Approve & push** → once happy, execute auto-commit's push chain
6. **`ci-audit`** → when CI finishes, audit the workflow run for warnings

### Workflow 2: Documentation Accuracy

1. **Refactor code** → change a function signature, move a file, update a CLI flag
2. **`docsync`** → find all stale doc claims that now contradict the code
3. **Review drift report** → decide what to fix
4. **`reslop`** (optional) → rewrite affected docstrings grounded in new code
5. **Update docs** → accept the proposed fixes from docsync
6. **`docs-site`** → audit the site for broken links after doc changes

### Workflow 3: Multi-Repo Release

1. **Coordinate changes** across sister repos (phalanx-fl, vFL, kourai-khryseai, etc.)
2. **`sisters`** → audit drift in CI action pins, Python versions, branch hygiene
3. **Fix inconsistencies** → update stale pinned versions in all repos
4. **`auto-commit`** on each repo → stage coordinated changes
5. **`audit`** on each repo → validate builds are clean
6. **Push & coordinate** → merge to main in consistent order

### Workflow 4: Observed Session (Pairing)

1. **Start a long-running task** (multi-hour test suite, large refactor)
2. **`theoros`** → spin up an observed tmux session
3. **Share the session ID** with teammates: `tmux attach -r -t theoros-<id>`
4. **Claude works** (running commands, audits) while you and teammates spectate
5. **Review the full transcript** at the end in the tmux history

## Design Philosophy

### 1. **Skills are Independent**

Each skill is self-contained. You can invoke `audit` without `ci-audit`, or `docsync` without `docs-site`. They share conventions (e.g., `.claude/skill-context.md` for config) but don't hard-depend on each other.

### 2. **Read-Only Audits + Human Review**

Every skill writes a plan, report, or diff to disk *first*. Nothing is committed or pushed without your review. The pattern is:
- **Inspect** → skill audits and writes a report
- **Review** → you read the report and decide
- **Execute** → you approve, skill makes changes (or you make them manually)

### 3. **Conventional File Locations**

All skills agree on a set of standard locations:
- `~/.claude/techne.toml` → user-level config (sister repos, GitHub user)
- `.claude/skill-context.md` → per-repo skill config
- `.github/workflows/docs.yml` → docs deploy workflow
- `COMMITS.md` → draft commit plan (local, never committed)
- `logs/dev-*.log` → local build log archives

### 4. **Composability Within Workflows**

Skills work together naturally:
- `audit` + `ci-audit` = validate locally + cloud
- `docsync` + `reslop` = find stale docs + rewrite them grounded in code
- `auto-commit` + `deslop` = structure commits + clean up prose
- `sisters` + all skills = coordinate across repos

## Extension Points

While techne ships with nine skills, the architecture supports adding more:

1. **Custom skills** in the plugin repo (e.g., `techne:mystats`, `techne:mybuild`)
2. **Skill context overrides** per repo (`.claude/skill-context.md`)
3. **Integration with other tools** (Makefile targets, shell scripts, GitHub Actions)

See the [Configuration](configuration.md) guide for per-repo customization details.

## See Also

- [Getting Started](getting-started.md) — install and run your first skill
- [Skills Reference](skills/index.md) — detailed docs for each skill
- [Configuration](configuration.md) — configure skills per-repo or globally
