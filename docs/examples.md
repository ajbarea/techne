# Examples

Real-world workflows combining techne skills to solve common problems.

## Example 1: Sister-Repo Consistency Audit

**Goal**: Ensure three federated learning projects (phalanx-fl, vFL, kourai-khryseai) have consistent CI action pins and toolchain versions.

**Step-by-step**:

1. **Set up sister registry** — Create `~/.claude/techne.toml`:

```toml
github_user   = "ajbarea"
workspace_root = "/home/ajbar/ajsoftworks"

[[sisters]]
name   = "phalanx-fl"
status = "active"

[[sisters]]
name   = "vFL"
status = "active"

[[sisters]]
name   = "kourai-khryseai"
status = "active"
```

2. **Run the audit**:

```bash
/sisters
```

Expected output: A drift report showing which repos have stale Python versions, pinned action SHAs, or branch hygiene issues.

3. **Fix drift** — For example, if phalanx-fl still uses `Python 3.10` but vFL and kourai use `3.12`:

Update `phalanx-fl/pyproject.toml`:
```diff
- python = "^3.10"
+ python = "^3.12"
```

4. **Verify** — Run sisters again to confirm alignment:

```bash
/sisters --report-only
```

---

## Example 2: Pre-Release Documentation Audit

**Goal**: Ensure all markdown docs and README claims match the actual codebase before shipping v1.0.

**Step-by-step**:

1. **Audit doc/code drift**:

```bash
/docsync
```

Expected output: A drift report grouped by file.

Example issues:
- `docs/getting-started.md:42` — CLI command `/audit --verbose` doesn't exist
- `README.md:5` — Function signature `fetch_user(user_id)` is now `fetch_user(user_id: int) -> Optional[User]`
- `docs/configuration.md:10` — Config key `site_author` → should be `author`

2. **Review and accept fixes**:

```
❌ Drift in docs/getting-started.md:42
   CLI flag "--verbose" not supported; remove it
   ✓ Accept fix? [y/n]
```

3. **Audit site mechanics** — Ensure the docs site itself is healthy:

```bash
/docs-site
```

4. **Rewrite stale docstrings** — If prose is wrong but needs rewrite (not deletion):

```bash
/reslop --file src/api.py
```

Before:
```python
def get_users():
    """
    Retrieves a list of all users from the database.
    This function is essential for multi-user applications
    and provides a comprehensive user list retrieval capability.
    """
    return db.query(User).all()
```

After:
```python
def get_users() -> List[User]:
    """Return all users from the database."""
    return db.query(User).all()
```

5. **Clean up slop** — Remove AI-generated verbose comments:

```bash
/deslop docs/ src/
```

6. **Tag & release** — Once docs match code, tag and release.

---

## Example 3: Clean Multi-Commit PR

**Goal**: Create a well-organized PR with logical, conventional-commit-style commits instead of a messy single monolithic commit.

**Scenario**: You've been refactoring auth for two days, with 47 changed files across multiple features and fixes.

**Step-by-step**:

1. **Stage and review your changes**:

```bash
git status
```

You have unstaged changes in many files.

2. **Draft a commit plan**:

```bash
/auto-commit
```

Output: Creates `COMMITS.md` with grouped commits:

```markdown
feat(auth): add JWT refresh token rotation

- Implement rotating refresh tokens with 7-day expiry
- Wire new endpoint into the auth router
- Add edge-case tests for rotation

Files: src/auth/tokens.py, src/auth/routes.py, tests/auth/test_tokens.py

---

fix(auth): handle expired tokens gracefully

- Check token expiry before use
- Return 401 instead of 500 on expired tokens

Files: src/auth/middleware.py, tests/auth/test_middleware.py

---

refactor(auth): consolidate token utilities

- Extract common token logic into utils.py
- Reduce duplication across auth modules

Files: src/auth/utils.py, src/auth/tokens.py, src/auth/refresh.py
```

3. **Review the plan** — Read through `COMMITS.md` and adjust groupings if needed.

4. **Clean up commits** — Before committing, scan for slop:

```bash
/deslop src/auth/
```

Removes verbose comments like:
```python
# This helpful utility validates that the token is still valid
# and hasn't expired yet, which is critical for security.
def is_valid(token):
    return token.expiry > now()
```

Becomes:
```python
def is_valid(token):
    """Return True if token hasn't expired."""
    return token.expiry > now()
```

5. **Validate the build locally**:

```bash
/audit
```

Ensure lint, test, and any other make targets pass.

6. **Execute the commit plan**:

Say "go" to the skill, and it:
- Stages files per commit
- Creates commits with your messages
- Pushes to your branch
- Optionally creates a PR

7. **Monitor CI**:

```bash
/ci-audit
```

After CI finishes, audit the run for warnings or deprecations. Fix any in-repo issues (e.g., outdated GitHub Actions pins).

---

## Example 4: Observed Pairing Session

**Goal**: A teammate wants to watch you refactor a complex module in real time without driving the terminal.

**Scenario**: You're refactoring a 2,000-line parser from imperative to functional style. Your teammate is in a different timezone and wants async visibility.

**Step-by-step**:

1. **Set up Tier 1 Theoros** in `.claude/skill-context.md`:

```yaml
theoros:
  project_root: /home/ajbar/ajsoftworks/my-project
```

2. **Start the observed session**:

```bash
/theoros
```

Output:
```
Started observed tmux session: theoros-2026-05-18-15-30-42
Attach read-only with:
  tmux attach -r -t theoros-2026-05-18-15-30-42
```

3. **Share the session ID** with your teammate (Slack, email, Discord).

4. **Teammate attaches**:

```bash
tmux attach -r -t theoros-2026-05-18-15-30-42
```

They see the session in real time as you (Claude) run:
- Code navigation and analysis
- Tests to understand current behavior
- Refactoring edits
- Validation runs
- Commit preparation

5. **Continuous observation** — Your teammate can:
- Watch commands execute
- See errors and fixes in real time
- Understand the reasoning from the session transcript
- Ask questions async (message you, not drive the session)

6. **Wrap up** — The tmux session persists, so teammates can review the full transcript later.

---

## Example 5: CI Noise Cleanup

**Goal**: Your workflow run is green but has 47 warnings. Identify and fix what you can in-repo.

**Scenario**: Codecov, Renovate, and deprecated GitHub Actions are producing noise.

**Step-by-step**:

1. **Audit CI warnings**:

```bash
/ci-audit
```

Output: Categorized report:

```
⚠️  Fixable in-repo (6 issues):
  ❌ actions/setup-python@v3 deprecated → update to v5
  ❌ Python 3.9 EOL → upgrade to 3.12 in pyproject.toml
  ❌ codecov/codecov-action@v3.1.0 → no longer maintained, use official wrapper

⚠️  Unfixable / policy (41 issues):
  ℹ️  Renovate bot: dependency updates waiting (policy: manual merge)
  ℹ️  GitGuardian: potential secret detected (but it's a test fixture, safe)
```

2. **Apply in-repo fixes**:

The skill updates:
- `.github/workflows/*.yml` (action versions)
- `pyproject.toml` (Python version)
- `.github/settings.yml` (branch protection, if needed)

3. **Review the changes**:

```bash
git diff .github/workflows/
```

4. **Commit and push**:

```bash
/auto-commit
# Review COMMITS.md
# Say "go" to auto-commit
```

5. **Re-run CI** — Wait for the workflow to complete and verify the warnings are resolved.

---

## Example 6: Cross-Repo API Consistency

**Goal**: Three codebases expose similar REST APIs. Ensure signatures and response shapes are documented consistently.

**Scenario**: phalanx-fl, vFL, and kourai-khryseai all have `/metrics` endpoints, but the docs claim different response shapes.

**Step-by-step**:

1. **Audit each repo's API docs**:

```bash
# In phalanx-fl
/docsync docs/api.md

# In vFL
/docsync docs/api.md

# In kourai-khryseai
/docsync docs/api.md
```

Each produces a drift report for its repo.

2. **Cross-reference** — Look at the actual endpoints:

```bash
# Review all three APIs side-by-side
grep -A 20 "def.*metrics" phalanx-fl/src/api.py
grep -A 20 "def.*metrics" vFL/src/api.py
grep -A 20 "def.*metrics" kourai-khryseai/src/api.py
```

3. **Standardize docs** — If the APIs intentionally differ, update each repo's docs to clarify (using docsync's proposed fixes). If they should be identical, create an issue for API alignment.

4. **Verify with sisters** (optional):

```bash
/sisters
```

To ensure all three repos are at matching toolchain versions (dependencies that might affect API behavior).

---

## Tips for Combining Skills

1. **`auto-commit` first, then `deslop`**: Group changes first, then clean up prose within those commits.

2. **`audit` before `ci-audit`**: Validate your build locally, then double-check GitHub Actions output.

3. **`docsync` before releasing**: Always verify docs match code before tagging a release.

4. **`sisters` after multi-repo refactors**: Coordinate and verify consistency across the team.

5. **`theoros` for long operations**: Use observed sessions for complex audits or refactors so teammates can follow along.

---

## See Also

- [Architecture](architecture.md) — how skills fit together
- [Skills Reference](skills/index.md) — detailed docs for each skill
- [Configuration](configuration.md) — customize skills for your repos
