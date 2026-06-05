# Getting Started

Install techne and run your first skill in minutes.

## Prerequisites

You'll need:

- **Claude Code**: The IDE plugin (visit the marketplace to install if you haven't already)
- **GitHub CLI** (`gh`): Several skills use this to interact with GitHub. Install: [github.com/cli/cli](https://github.com/cli/cli)
- **A git repository**: All skills work within git repos. Initialize one if needed: `git init`

## Installation

From inside Claude Code:

```bash
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

Verify the install:

```bash
/help techne:audit
```

This should display the help text for the `audit` skill. If you see "Command not found", refresh Claude Code and try again.

## First Workflow

Let's walk through a typical use case: **validating your local build before pushing**.

### 1. Pick Your First Skill

Choose based on what you're trying to do:

| Want to... | Use |
|---|---|
| Validate your local build is clean (lint, test, etc.) | [`techne:audit`](skills/audit.md) |
| Organize your pending changes into logical commits | [`techne:auto-commit`](skills/auto-commit.md) |
| Check GitHub Actions for warnings and failures | [`techne:ci-audit`](skills/ci-audit.md) |
| Clean up AI-generated slop in your code | [`techne:deslop`](skills/deslop.md) |
| Rewrite docstrings grounded in the code | [`techne:reslop`](skills/reslop.md) |
| Verify documentation claims match the code | [`techne:docsync`](skills/docsync.md) |
| Maintain your Zensical docs site | [`techne:docs-site`](skills/docs-site.md) |
| Ground plan decisions in current best practice | [`techne:research-grounded`](skills/research-grounded.md) |
| Audit sister repos for consistency | [`techne:sisters`](skills/sisters.md) |

### 2. Run Your First Skill

Example: `techne:audit` to validate the build.

```bash
techne:audit
```

Expected output:

```
Running techne:audit on <your-repo>

Target: setup ... OK (log matches)
Target: lint  ... OK (log matches)
Target: test  ... OK (log matches)

All targets passed. Your build is clean.
```

If any target fails or drifts, the skill will highlight it clearly and suggest fixes.

### 3. Review & Approve

All skills write a plan, report, or diff to disk **before** making changes. Review it carefully, then approve:

```bash
# You see a report or diff
# Review it: does it look right?
# If yes, say "go" or "apply" to execute
# If no, edit manually or ask for refinements
```

### 4. Next: Multi-Skill Workflows

Once you're comfortable with one skill, combine them:

```bash
# Validate locally
techne:audit

# Organize your changes
techne:auto-commit
# Review COMMITS.md, then say "go"

# Check GitHub Actions output
techne:ci-audit

# Clean up prose before merging
techne:deslop src/
```

See [Examples](examples.md) for real-world workflows.

## Configuration

### Per-Repo Configuration

Several skills read repo-specific facts from `.claude/skill-context.md`, one `##` section per skill family (markdown headers, not top-level keys). For example:

```markdown
## audit
phases: [setup, lint, test, ci]
fast_subset: [lint, test]

## slop_ground_truth
authoritative_sources:
  - "src/"
```

See [Conventions](conventions.md) for the full skeleton, and [Configuration](configuration.md) for the user-level `~/.claude/techne.toml`.

### Multi-Repo Configuration

If you manage multiple repositories (sister repos), create `~/.claude/techne.toml`:

```toml
github_user = "your-github-username"
workspace_root = "/path/to/your/workspace"

[[sisters]]
name = "repo-one"
status = "active"

[[sisters]]
name = "repo-two"
status = "active"

[[sisters]]
name = "repo-three"
status = "active"
```

Then use `techne:sisters` to audit cross-repo consistency. See [Configuration](configuration.md) for details.

## Common Questions

**Q: Can I use only one skill?**  
A: Yes! Each skill is independent. You can use `audit` without `ci-audit`, or `docsync` without any others.

**Q: What if a skill tries to modify my code and I disagree?**  
A: All skills write a plan or diff first. Review it, edit manually if needed, and approve before execution. You're always in control.

**Q: Can I customize skill behavior?**  
A: Yes. Use `.claude/skill-context.md` for per-repo overrides, and `~/.claude/techne.toml` for multi-repo config. See [Configuration](configuration.md).

**Q: Does `techne` modify my git history?**  
A: Only if you approve. Skills like `auto-commit` stage and commit, but they ask for your permission first. Skills like `audit` and `docsync` are read-only by default; they surface issues, you decide whether to fix them.

**Q: What's the difference between `deslop` and `reslop`?**  
A: `deslop` finds and trims AI-slop (verbose, redundant prose). `reslop` rewrites docstrings grounded in the actual code. Use `deslop` for triage; use `reslop` when you want replacement prose, not deletion. See [Examples](examples.md#pre-release-documentation-audit) for a real workflow.

**Q: How do I debug issues?**  
A: The skills are prompt-driven, not CLI tools with flags; steer them in natural language. Ask Claude to explain what a skill is doing, or tell it what looked wrong and rerun. If one gets stuck, cancel and try a different approach.

## Troubleshooting

**"Command not found: techne:audit"**  
- Ensure you ran `/plugin install techne@techne` inside Claude Code.
- Refresh Claude Code and try again.
- Check that you're in a git repository (`git status` should work).

**"gh: command not found"**  
- Install GitHub CLI: [github.com/cli/cli](https://github.com/cli/cli)
- Authenticate: `gh auth login`

**"Skill runs but output looks wrong"**  
- Re-run and tell Claude what specifically looked off. There are no `--verbose`/`--debug` flags; the skills are prompt-driven, so natural language is the control surface.
- Check `.claude/skill-context.md` for any overrides that might affect behavior.
- Ask Claude to explain what the skill is doing.

**"Sister repo config not working"**  
- Verify `~/.claude/techne.toml` exists and is readable.
- Check the repo names match your actual directories.
- Ask `techne:sisters` which repos it detected from the config.

## Next Steps

- **[Explore All Skills](skills/index.md)**: Detailed reference for each skill
- **[Architecture Guide](architecture.md)**: Understand how skills fit together
- **[Real-World Examples](examples.md)**: See skills in action across different workflows
- **[Configuration Reference](configuration.md)**: Customize skills for your repos
- **[techne on GitHub](https://github.com/ajbarea/techne)**: Source code and issue tracker
