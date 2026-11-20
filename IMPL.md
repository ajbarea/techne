# techne — Implementation scratchpad

The work in flight right now: current branch, slice, what is done, what is next, how to verify.
Forward plans live in [ROADMAP.md](./ROADMAP.md); finished work lives in git and GitHub. The
cleanup check holds this file to 50 lines.

## Cleanup check (branch feat/cleanup-check-390, issue #390)

- Slice: one deterministic check that finished work is recorded only in git + GitHub.
  `plugins/techne/_shared/cleanup.py`: `check` (ROADMAP done-log + budget, IMPL budget, agent
  instruction files by lines and bytes, transient files' owner + expires/reviewed), `done-log`
  (print for harvest), `prune` (delete; refuses untracked/dirty/linked ROADMAP, `prune: off`,
  a `registered_report` sister or an unreadable roster).
- ✅ Sisters check 18 (SKILL.md table, output block, checks.md section), clean mode's done-log
  harvest steps; `## cleanup` in conventions, the skill-context template and docs/skills/sisters.md.
- ✅ CI: `make guards` runs `cleanup.py check --ci .`; `.github/workflows/cleanup.yml` is the
  reusable workflow other repos call, pinned by SHA (checks out the script at `job.workflow_sha`).
- ✅ techne itself migrated: Shipped log pruned (266 lines) after harvest. Open follow-ups went to
  #391 (shared pin check, actionlint); the rest is a record git already holds.
- ✅ Tests: `tests/test_cleanup_check.py`, every guard's boundary cell, run through the script.
- ✅ Heph's 3rd input: `rules` part (lessons, bug classes need a date within 90 days; prune pass
  done: 18 reviewed, `stale-forward-compat-prediction` retired) and `flaky` part (retry markers
  need `quarantine: until` within 30 days).
- ✅ PR #394 open. Round 1 (fresh Opus reader): 1 Blocking + 7 Should-fix, all fixed: roster guard
  matches worktrees/clones and fails closed (sphragis marked in techne.toml); `prune:` parsed in any
  spelling, config errors refuse; Markdown `Scan` (ATX indent, setext, CommonMark fences, list
  content) + `span_hazard` refusal, differential vs markdown-it-py; `without()` edits only cut edges;
  `frontmatter()` via read_text; `--no-dates` for PR gates + weekly dated run; mutation tests.
- 📋 Next: kill CI mutation survivors (tests, or a written reason per equivalent), bench A/B vs
  main (Heph: git_guards-git-status +19%; this PR does not touch phylax), round 2 reader.
- Renumbered planned checks: #257 is now check 19, #259 check 20.
- Verify: `make lint`; `uv run pytest tests/test_cleanup_check.py`; `make guards`;
  `python3 plugins/techne/_shared/cleanup.py check ~/ajsoftworks/<sister>` on real repos.
