# Examples

Concrete workflows combining techne skills. Each one is a recipe for a real problem; the skill invocations match actual behavior, not hypothetical flags.

## Cross-repo consistency audit

You maintain a few related repos and want to make sure their CI pins, toolchain versions, and merge settings haven't drifted apart.

1. Configure the linked repos in `~/.claude/techne.toml` (see [Configuration](configuration.md)).
2. Run `/techne:sisters`.
3. Read the drift report. It groups findings by category: action-pin drift, toolchain-pin drift, GitHub merge-setting + branch-protection drift, Codecov config, log-retention, Dependabot coverage, open PRs, stale branches, local `main` divergence.
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
2. Review and edit `COMMITS.md` directly: re-group, rename, add detail, drop noise.
3. Run `/techne:deslop` to scan source comments and docstrings for AI-generated slop introduced during the refactor. Apply the suggested rewrites.
4. Run `/techne:audit` to validate lint, test, and any other Make targets pass.
5. Approve the commit plan; the skill stages files per commit, creates the commits, and pushes.
6. After CI finishes, run `/techne:ci-audit` to triage any new warnings or deprecations the workflow surfaced.

## Observed pairing session

A collaborator wants to watch you refactor a complex module in real time without driving the terminal.

1. Add a `## theoros` section to `.claude/skill-context.md` listing your REPL command and a session name (see [Conventions](conventions.md)).
2. Run `/techne:theoros`. It starts a detached tmux session named per the config.
3. Share the session name with collaborators. They attach read-only: `tmux attach -r -t <session-name>`.
4. You drive the work through Claude; collaborators see live output. The split-window layout is optional; add an `ops_command` to the skill-context if you want a tailing logs pane underneath the driver pane.
5. Tear down with `make theoros-down` (if you've adopted the tier-2 Makefile targets) or `tmux kill-session -t <session-name>`.

## CI noise cleanup

Your workflow is green but the run log is full of warnings: deprecated action versions, deprecation notices from third-party tools, policy-driven noise.

1. Run `/techne:ci-audit` against the latest workflow run on your branch. It categorizes findings: fixable in-repo (action pins, Python version, workflow YAML), unfixable / policy (bot output, security scanners), and noise.
2. Apply the in-repo fixes via the skill's proposed edits: typically workflow YAML pin bumps, occasional `pyproject.toml` Python-version updates.
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
- Run `/techne:docsync` before releases; drift between docs and code is the source of most "didn't they fix this?" bug reports.
- Run `/techne:sisters` after multi-repo refactors so the linked repos stay coherent.
- Use `/techne:theoros` for long-running operations where a collaborator wants async visibility without driving.

## See also

- [Architecture](architecture.md): how the skills fit together
- [Conventions](conventions.md): the file locations and patterns each skill assumes
- [Skills reference](skills/index.md): per-skill detail
