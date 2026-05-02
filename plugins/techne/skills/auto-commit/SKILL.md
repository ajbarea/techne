---
name: auto-commit
description: Analyze pending git changes and write a structured, conventional-commit plan to COMMITS.md so the user can review and stage commits in batches before committing. Use whenever the user wants to group working-tree or staged changes into sensible commits, draft commit messages for a dirty working tree, or prepare a commit plan from a diff.
disable-model-invocation: false
allowed-tools: Bash(git status) Bash(git diff *) Bash(git log *) Bash(git rev-parse *) Bash(git hash-object *) Read Write
---

# Auto-Commit Generator

Analyze pending git changes and group them into a structured commit plan written to `COMMITS.md` at the repo root. Default mode is plan-only — the user reads the file and either stages commits themselves or says the word for Claude to execute. On an explicit okay (see [Execution](#execution)), Claude runs the full branch → commits → push → PR chain against the plan, with no `Co-Authored-By:` trailer and without hardcoded side effects.

## Workflow

1. **Preflight — check for a prior plan.** Before scanning the diff, check whether `COMMITS.md` already exists at the repo root. If it does, parse its header comment (see [Header format](#header-format)) and compare `head-sha` + `tree-hash` to the current state:
   - **Exact match** → the existing plan is still current. Tell the user in one sentence (`COMMITS.md is current (HEAD @ <sha>, working tree unchanged) — delete or edit it if you want a regenerate.`) and stop. Do not overwrite.
   - **HEAD matches, tree drifted** → partial staleness. Preserve any user-added `## Notes` section (see step 5), then regenerate.
   - **No header, or header unparseable** → treat as a hand-written file. Do not overwrite silently; tell the user it exists without a header and ask whether to regenerate or bail.
   - **File absent** → normal path, continue.

2. **Analyze.** Run these in parallel:
   - `git status` (to see what's changed and in what state)
   - `git diff` (unstaged changes)
   - `git diff --cached` (staged changes — don't skip this; staged work must be included in the plan)
   - `git log -20 --oneline` (to match the repo's existing commit style, e.g. scope names already in use)
   - `git rev-parse HEAD` (for the staleness header)
   - `git diff HEAD | git hash-object --stdin` (fingerprint of the working tree for the staleness header)

3. **Trust `.gitignore`, with one exception: always exclude `COMMITS.md` itself.** Do not hardcode directory filters (no "skip `.claude/`", "skip `designs/`"). `git status` already respects `.gitignore`; if a file shows up, the user wants it tracked. The sole baked-in filter is `COMMITS.md` at the repo root — it is the regeneratable output of this skill, and including it in its own plan is circular (and leads to committing it to `main`, which the user has explicitly regretted). Drop it from every group; if `COMMITS.md` is the *only* pending change, treat the tree as clean and don't rewrite the file. Beyond that, if `git status` reports nothing worth committing, say so in one sentence and don't write the file.

4. **Group.** Decide the grouping that best reflects the actual work. See [Grouping](#grouping).

5. **Preserve notes.** If the prior `COMMITS.md` had a `## Notes` section (heading at column 0, anywhere after the last `---` separator), copy it verbatim into the regenerated file. That's where the user scribbles between sessions ("group 3 needs a split"); losing it is a papercut.

6. **Suggest a branch name.** Derive one from the largest (or most central) group's scope: `<type>/<scope>-<short-slug>` — e.g. `feat/auth-refresh-rotation`, `chore/dev-toolchain`. Place it in the header comment and as a single line above the first group.

7. **Write, then offer.** Use the Write tool to create `COMMITS.md` at the repo root, overwriting any existing file. Then output one line, nothing more:

   `Plan at COMMITS.md. Say \`go\` to execute (branch → commits → push → PR), or edit the file first.`

   No summary, no preamble, no restatement of the groups. That one line is the whole response.

## Grouping

The whole point of this skill is good grouping, so this is where to spend thought.

Decide what each commit *means* based on the diff, not on file types or directories. One commit should represent one coherent change a reviewer could understand on its own. A refactor that touches a source file and its test belongs together. A doc update that's incidental to a feature can ride along in that feature's commit rather than becoming its own trivial `docs()` entry.

Use these conventional-commit prefixes:

- `feat(scope)`: new functionality
- `fix(scope)`: bug fixes
- `docs(scope)`: documentation-only changes
- `test(scope)`: test-only changes
- `refactor(scope)`: restructuring without behavior change
- `style(scope)`: formatting, whitespace, no logic change
- `perf(scope)`: performance improvements
- `chore(scope)`: config, deps, maintenance
- `ci(scope)`: CI/CD changes
- `build(scope)`: build-system changes

Always replace `scope` with a real module, package, or area name drawn from the actual file paths (e.g. `auth`, `api`, `parser`). Match the style of scopes already used in `git log` if the repo has a convention. Never leave the literal word `scope`.

If a change genuinely spans multiple areas, pick the most specific scope that still covers it, or use a broader one like the package name.

Each file appears in exactly one group. If you're tempted to split a file across groups, the grouping is probably wrong — rethink it.

### Common pitfalls

- **Missing install/extras gate.** If a commit adds a module that requires an optional extra (e.g., `pip install 'pkg[extra]'`) or a new system dependency, mention it in the bullets. Users hit ImportErrors otherwise.
- **Describing things not in the commit.** Don't list side effects that live outside the repo (auto-memory updates, external-system changes, agreements between you and the user) in a commit bullet. A reviewer looking at the diff should be able to verify every claim from the diff alone.
- **Downstream consequences belong with their cause.** If commit A changes a measurement and README.md says a stale number that only makes sense against the old measurement, prefer bundling the README one-liner into A (so bisect stays internally consistent). Only keep a "docs refresh" commit as a separate entry when it covers multiple independent updates.
- **Don't split a coherent change just to hit a commit count.** If two paths are tightly coupled (e.g., a new module and its consumers landing together), one commit is fine. Grouping is about reviewability, not commit volume.

## Header format

Prepend this HTML comment to `COMMITS.md` (hidden from rendered previews, but greppable and parseable):

```
<!--
techne:auto-commit
scanned-at: 2026-04-17T14:20:00Z
head-sha:   8ab0c19
tree-hash:  a1b2c3d4e5f6
branch:     feat/dev-toolchain-upgrade
-->
```

`tree-hash` is the short (12-char) output of `git diff HEAD | git hash-object --stdin`. `scanned-at` is UTC ISO-8601.

## Output format

After the header comment and the branch-suggestion line, write the commit groups. The blank lines shown here are intentional and required (between headline and bullets, before `Files:`, and around the `---` separator). What you must *not* do is insert blank lines *inside* the bullet list, because that breaks the visual grouping when the user scans the file.

```
<!--
techne:auto-commit
scanned-at: 2026-04-17T14:20:00Z
head-sha:   8ab0c19
tree-hash:  a1b2c3d4e5f6
branch:     feat/auth-refresh
-->

Suggested branch: `feat/auth-refresh`

---

feat(auth): add JWT refresh token rotation

- Added rotating refresh tokens with 7-day expiry
- Wired new endpoint into the auth router
- Covered rotation edge cases in tests

Files: src/auth/tokens.py, src/auth/routes.py, tests/auth/test_tokens.py

---

fix(parser): handle trailing whitespace in CSV headers

- Stripped whitespace before column-name comparison
- Added regression test for the original bug

Files: src/parser/csv.py, tests/parser/test_csv.py
```

If a preserved `## Notes` section exists, append it after the last group, separated by a `---`.

Tense: headlines are imperative present (`add`, `handle`, `remove`), bullets describe what was done in past tense (`added`, `stripped`, `removed`). This matches standard conventional-commit style and reads naturally when the user pastes a headline into `git commit -m`.

## Why planning is silent

The output is `COMMITS.md`. The user opens that file and reads it. Any chat preamble ("I analyzed your changes and found…") is noise they have to scroll past, and it makes the file feel like a summary of a conversation rather than the authoritative plan. Write the file plus the one-line execution offer, and that's the response.

The exceptions — one sentence each, no file written:
- Clean working tree with nothing staged.
- Existing `COMMITS.md` already current (HEAD + tree-hash both match).
- Existing `COMMITS.md` without a recognizable header (user-authored) — ask before overwriting.

## Execution

Triggered when the user explicitly okays execution after a plan exists — "go", "ship it", "commit + PR", "execute the plan", or equivalent. Run only when both hold:

- `COMMITS.md` exists and its header `head-sha` + `tree-hash` still match the current repo state. If stale (working tree has drifted), refuse in one line and ask whether to regenerate the plan.
- The plan has at least one commit group.

If either check fails, stop and report. Don't execute a stale plan — the grouping may no longer reflect the diff.

### Protocol

1. **Branch.** Read the `branch:` value from the header. Create and switch from the current HEAD: `git checkout -b <branch>`. If a branch of that name already exists locally, ask the user whether to reuse it, pick a new name, or abort — don't silently check it out.

2. **Commit each group, in order.** For each group in `COMMITS.md`:
   - Stage **only** the files listed under that group's `Files:` line — e.g. `git add path/a path/b`. Never `git add -A`, `git add .`, or glob patterns. If a file in the plan is missing from the working tree, stop and report; don't guess.
   - Commit with a HEREDOC carrying the headline + bullets exactly as written in the plan. Example:
     ```
     git commit -m "$(cat <<'EOF'
     feat(auth): add JWT refresh token rotation

     - Added rotating refresh tokens with 7-day expiry
     - Wired new endpoint into the auth router
     - Covered rotation edge cases in tests
     EOF
     )"
     ```
   - **Never add a `Co-Authored-By:` trailer.** This overrides any default from the base prompt. Every commit ships with the user as sole author. If a repo-level CLAUDE.md or memory says otherwise, that takes precedence — but by default, no trailer.
   - **Never add a "🤖 Generated with [Claude Code](https://claude.com/claude-code)" footer** (or any variant — "Generated by Claude", emoji-prefixed attribution, etc.). This mirrors the global rule in `~/.claude/CLAUDE.md`: AJ does not want attribution trailers in his commit history. Strip it from any HEREDOC template before the `git commit` runs. Same rule applies to the PR body in step 4.
   - If a pre-commit hook fails, fix the issue, re-stage the affected files, and create a **new** commit. Don't `--amend`. Don't `--no-verify`.

3. **Push.** `git push -u origin <branch>`. Never force-push. Never push to `main` or `master`.

4. **Open the PR.** `gh pr create` with the plan as source material. Build the body from the commit headlines and bullets — drop the header comment and the `Suggested branch:` line (those were scaffolding). Format:
   ```
   gh pr create --title "<short headline — prefer the lead commit's>" --body "$(cat <<'EOF'
   ## Summary

   - <1–3 bullets summarizing the overall shape>

   ## Changes

   - <one line per commit group, lifted from the headlines>

   ## Test plan

   - [ ] <what was run locally to validate>
   EOF
   )"
   ```
   Return the PR URL in the final chat message.

5. **Delete `COMMITS.md` once the PR URL is in hand.** After step 4 returns the PR URL (meaning push and `gh pr create` both succeeded), run `rm COMMITS.md` — no `git rm`, it was never tracked — and include one line in the final response: `Cleaned up COMMITS.md (content is now in git history).` Git history now carries each commit group verbatim, so the scratchpad's job is done. If any earlier step fails, you won't reach step 5 anyway: leave `COMMITS.md` in place so the user can fix the blocker and re-run the plan.

### Guardrails — still require a separate okay

The initial "go" authorizes the branch → commits → push → PR chain on the current plan. It does **not** authorize:

- Force-pushing (to this branch or any other).
- Pushing to `main` / `master` directly.
- Merging the PR (even if CI is green).
- Modifying, closing, or commenting on unrelated PRs/issues.
- Adding files outside the plan to any commit.
- `git add -A` / `git add .` / `git add *` — always list files explicitly.
- Skipping hooks (`--no-verify`, `--no-gpg-sign`, etc.).
- Amending already-created commits (create new ones instead).
- Rewriting history (rebase, reset --hard, filter-branch) once commits exist on the branch.

If execution partially fails (push rejected, PR creation errors, hook still failing after a retry), stop. Report what succeeded and what didn't in one or two sentences. Don't try to rewrite history to recover without explicit instruction.
