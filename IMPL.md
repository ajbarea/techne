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
- 📋 Left for #392 (stays open): a mechanical SHA gate (the ledger or a pre-merge check refusing a
  verdict whose head SHA is not the PR's `headRefOid`); today the SHA is recorded, not enforced.
- 📋 Next: fresh Opus round 2, CI, merge.
- Verify: `uv run pytest tests/test_skill_context.py tests/test_elenchus_own_checks.py`; `make guards`.
