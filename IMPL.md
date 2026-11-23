# techne — Implementation scratchpad (feat/elenchus-base-rules-392)

The active TODO list for whatever's in flight right now. Queued specs live in [ROADMAP.md](./ROADMAP.md).

## elenchus reads its hints from the base branch (issue #392, PR #405)

- Slice: `_shared/skill_context.sh --base[=REF]` prints `.claude/skill-context.md` as committed on the
  base (default: origin/HEAD, else origin/main); `own_checks.py` lists the files a change edits that are
  part of its own checks; the report header names the reviewed head SHA.
- ✅ agy's first pass (d73e914, 0bddf98).
- ✅ Opus round 1 (not mergeable: 3 Blocking, 3 Should-fix) fixed:
  - The base read fell back to `main`, then `HEAD~1`, then the working tree, all of which can be the
    PR's own copy (master-default remote, base without the file, shallow clone). Now nothing stands in:
    a missing ref or file is said and nothing is printed in its place; the header names the ref read.
  - `--base REF` guessed whether a word was a ref or a path (`upstream/main` read as a path); now
    `--base=REF` only.
  - The one test kept the PR's edit uncommitted and survived 5 of 7 mutants; now a matrix over
    committed PR branches (master default, upstream remote, detached HEAD, another folder, missing
    base, missing file), every mutant of the base read killed.
  - The "edits its own check" list named a file that does not exist and missed skill-context; now
    `scripts/own_checks.py` with a tested rule table (old and new name of a renamed check).
- ✅ Opus round 2 (not mergeable: 1 Blocking, 2 Should-fix) fixed in the parked commit:
  - A tag or local branch named `origin/main` shadowed the remote ref: one resolver in skill_context.sh
    now prefers `refs/remotes/REF`, refuses a name that is also a branch or tag, resolves to a SHA and
    prints the full ref + short SHA; it refuses a base that is the reviewed commit or a remote branch
    of the reviewed branch's own name (single-branch clone points origin/HEAD at the PR).
  - own_checks.py resolves its base through `skill_context.sh --base-sha` (no second copy); rule table
    extended to the fleet's files (.gitlab-ci.yml, ruff.toml, biome.json, scripts/mutation.py, ...)
    and narrowed (`hooks/` only at the root or in a plugin; `check_*` only under scripts/).
  - `--base` after the target is refused. Every mutant of the new guards is killed.
- 📋 Not done yet (round 2 Minor): SKILL.md should say "git fetch the base and rerun" when the ref is
  missing (review without hints only when the base has no file), name refs/remotes/origin/<baseRefName>,
  and add the stacked-PR line; PR body table needs the new header shape.
- 📋 Left for #392 (stays open): a mechanical SHA gate (the ledger or a pre-merge check refusing a
  verdict whose head SHA is not the PR's `headRefOid`); today the SHA is recorded, not enforced.
- 📋 Next (after the 5h reset): the SKILL.md Minors above, then a fresh Opus round 3 at the high
  tier, CI, merge.
- Verify: `uv run pytest tests/test_skill_context.py tests/test_elenchus_own_checks.py`; `make guards`.
