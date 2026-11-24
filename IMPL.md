# techne — Implementation scratchpad (feat/elenchus-base-rules-392)

The active TODO list for whatever's in flight right now. Queued specs live in [ROADMAP.md](./ROADMAP.md).

## elenchus reads its hints from the base commit (issue #392, PR #405)

- Design (round 5): `_shared/skill_context.sh --base=<id> [--head=<id>]` prints `.claude/skill-context.md`
  as committed on the base commit. Both values are full commit ids only (40 or 64 hex, by the repo's
  object format, peeled to a commit and equal to it): a PR's `baseRefOid`/`headRefOid`, or before a PR
  `gh api repos/{owner}/{repo}/commits/HEAD --jq .sha`. Every ref name is refused, `--base` alone and
  `--head` alone are refused, a base that holds the head is refused (`merge-base --is-ancestor`), and
  git's full `--local-env-vars` list is stripped. `--base-sha` prints `<base> <head>`.
- `elenchus/scripts/own_checks.py --head <id> <base id>` resolves through `--base-sha`, reads
  `git diff -z --no-renames base...head`, and lists check files by name rules plus any file the base's
  Makefile, pre-commit config or workflows name (tokenized; comments, YAML filter lists and
  folderless globs left out).
- History: round 1 (fallbacks to HEAD~1/working tree), rounds 2-4 (ref-name shapes: shadowing tags and
  branches, single-branch clones, a guessed origin/HEAD default) each found a new ref shape; the class
  recurred four times, so round 5 removed ref names altogether.
- 📋 Left for #392 (stays open): a mechanical gate refusing a verdict whose head SHA is not the PR's
  `headRefOid`; today the report records the SHA.
- ✅ Round 5 fixes: replacement objects and grafts off for every read (both scripts); the base is always
  the default branch's commit (a stacked PR's baseRefOid is author-controlled); a shallow clone with no
  shared history is refused; injected GIT_CONFIG* kept as git_env.py keeps it; ls-tree presence check;
  filter lists skipped by key; gate-only hits marked as the weaker signal.
- ✅ Round 6 fixes: every repo-root file counts as a check unless prose, image or app source (the
  name list had grown in three commits); `--file=PATH` reads any path from the base through the same
  guarded read (catalog recipe uses it; blob-level replace tested); elenchus no longer loads the
  working tree's hints at all; refusals name the commits/HEAD recipe; `--no-relative`; `$VAR/` paths.
- ✅ Round 7 (hold on 1, then mergeable): the root rule excludes only prose, images, content and
  named docs, so root code config (vitest.setup.ts, .eslintrc.js, requirements.txt) counts; every
  root tool config and workflow is a gate file, one hop deep; a local review (no --head) adds
  uncommitted and untracked files; the recipe names the repo (`-R`); odd or folder `--file` paths
  are refused.
- ✅ Round 8 (fresh Opus verify): round 6-7 fixes confirmed, 22 hand mutants all red; one
  Should-fix: subfolder tool config (src-tauri/Cargo.toml, web/tsconfig.json) listed as none, the
  name list's fifth miss. Structural fix: any folder holding a package manifest (on the base or
  added by the change) is a root, its own non-prose files are checks and gate files (tokens also
  read from that folder), and dotfiles count at any depth; .githooks/ and .husky/ are gate files.
  Live: klepsydra and myo-lever repros now list the loosened config; 4 hand mutants red.
- ✅ Round 9 (fresh Opus): 3 Should-fix fixed structurally: a UTF-16 root gate file crashed the
  script (gate files now read as bytes through one `cat-file --batch`, UTF-16 by BOM, binaries
  skipped); a flat-layout package listed its source (a package folder now counts only its
  config-shaped files and manifests; setup.py is no manifest); dot-folder config was missed (any
  dot-folder or dotfile at any depth counts). Package tokens are normalized (`../shared/x`).
  Gate globs match folder by folder (`agents/*` names folders, not every file under them).
  Locked by a sweep table of 35 documented tool-config locations x 3 places, negatives, and 6
  hand mutants. Live: kourai agent edits no longer strong; fl-execution UTF-16 no crash;
  myo-lever and klepsydra config listed.
- ✅ Round 10 (fresh Opus): 4 Should-fix fixed: git output read as bytes and decoded as file
  names (a non-UTF-8 name crashed ls-tree), output printed escaped; prose (AGENTS.md, CLAUDE.md)
  is never a gate file; the folderless-glob guard and cat-file's newline-name filter now have
  tests; config by shape (`*.conf.js`, `.neon`, `.dist`, `.props`, `*.csproj`, Bazel, CMake,
  Rakefile, Dockerfile) and Dart/.NET/CMake/Bazel package roots; UTF-8 BOM; prose in a
  dot-folder is not a check; path_glob's unreachable bracket code removed. SKILL.md states the
  coverage limit: a file the list leaves out is not cleared. 7 hand mutants red.
- ✅ Round 11 (fresh Opus): 3 Should-fix fixed, each with a test its mutant fails: cat-file's
  `missing` branch (a root gitlink), the file-name round trip (a non-UTF-8 gate file's token is
  read; its name prints escaped), and root prose like LICENSE.txt no longer a strong check.
  Nits left for a follow-up: prose rule files in dot-folders (.cursor/rules, .gemini) are not
  listed; a name with a newline prints on two lines; CMakeLists.txt as a manifest.
- ✅ Round 12 (fresh Opus): clean; its wording Nit fixed in SKILL.md. Follow-up Nits: see the issue linked in the PR.
- 📋 Next: CI green, merge (squash, delete branch); #392 stays open for the SHA gate.
- Verify: `uv run pytest tests/test_skill_context.py tests/test_elenchus_own_checks.py`; `make guards`.
