# techne — Implementation scratchpad (fix/private-names-push-396)

The active TODO list for whatever's in flight right now. Queued specs live in [ROADMAP.md](./ROADMAP.md).

## Private-names guard blocks the push itself (issue #396, PR #403)

- Slice: the repo's pre-push hook (`scripts/git-hooks/pre-push`, installed by `make setup` via
  `scripts/install_git_hooks.sh`) runs `check_private_names.py --pre-push`, which scans exactly
  the refs git sends (commits, messages, annotated tags, ref names) against the target remote's
  tracking refs. phylax's `check_push_hook` makes sure the hook runs: it refuses `--no-verify`, a
  per-command `core.hooksPath` (`-c`, `--config-env`, `GIT_CONFIG_*`), a missing or foreign hook,
  and a push into a folder that does not exist yet. It runs none of the repo's code.
- ✅ agy's first pass: kept the sisters check 17 hook gap (now also accepts a chained hook).
- ✅ Round 1 (on #396) and round 2 (fresh Opus, 1 Blocking + 5 Should-fix): phylax's own model of
  a push kept missing what git sends (bare `git push` of a private-named branch, `--follow-tags`),
  so the scan moved wholly to the hook, which reads git's real ref list; phylax only enforces
  that it runs (fixes the repo-code execution, the over-broad same-command refusal, and the
  check-time folder gap). The hook excludes only the target remote's refs. Scanner is 3.9-safe.
  Installer: skips outside a repo, any core.hooksPath, a foreign or symlinked hook; works from a
  worktree. 15 hand mutants red; test_private_names runs on TECHNE_GUARD_PYTHON (3.9 too).
- ✅ Round 3 (fresh Opus, 1 Blocking + 4 Should-fix): phylax string-matched where hooks live
  (GIT_CONFIG_GLOBAL files, `-c alias.p='push --no-verify'` got past); now it asks git
  (`rev-parse --git-path hooks` with the push's -c and environment) and checks the hook there;
  the alias lookup sees -c; a push after a `git config` or any word naming hooks in the same call
  waits; an installed techne hook proves the repo ships the scan (bare clones, --work-tree); the
  hook reads the scanner from HEAD and fails closed without it; a URL push uses the remote that
  URL belongs to, else scans all history; sisters and phylax share one mark list. 11 more hand
  mutants red.
- ✅ Round 4 (fresh Opus, 2 Should-fix): the word rule held ordinary pushes ("webhook" in a
  message, `make test-hooks-oldest`) yet missed `printf >> .git/config`: a push now waits only for
  an earlier write or mode/existence change under the git dir, common dir, hooks folder or a git
  config file, a `core.hooksPath` token, or a `git config` write. One `git_env` (only the
  variables that locate repo and config, so no GIT_TRACE file) feeds the alias, repo and hooks
  lookups; flags in variables are expanded; an unreadable push argument refuses. 13 more mutants.
- ✅ Round 5 (fresh Opus, 1 Blocking + 5 Should-fix): a `--config-env` variable set on the line
  never reached phylax's lookup, so git errored and phylax took that for "no repo" (also an
  attribution-guard regression through aliases). Now: --config-env variables join the lookup
  env; a failed lookup on a command that sets config, repo options or locating variables
  refuses; an alias git could not read refuses; trace2 is forced off in every phylax git call;
  same-call paths are compared through symlinks and globs, and `mv` counts both sides; known
  variables are expanded and `$(git branch --show-current)` (directly or through a variable)
  passes. 9 more mutants red; redundant guards removed rather than left untested.
- ✅ Round 6 (fresh Opus, 3 Blocking + 2 Should-fix): passing each `--config-env` variable into
  phylax's git let a PATH or GIT_TRACE_PERFORMANCE steer phylax's own subprocess: now each
  `--config-env=K=VAR` becomes `-c K=<value>` and only locating variables pass; an alias's own
  -c/--config-env options are kept and checked; a push whose folder (`cd`/`-C` to a value this
  check cannot expand) or repo variable cannot be read is refused in any repo, with
  `$(git rev-parse --show-toplevel)` accepted; `send-pack` and `http-push` refused in a hooked
  repo. 11 mutants red; a dead fsmonitor ordering option removed.
- ✅ Round 7 (fresh Opus, 2 Blocking + 5 Should-fix): git takes unique prefixes (`--no-veri`):
  now read as git reads them; a config file written earlier in the call and read through
  GIT_CONFIG_* or an include holds the push (and an alias from it); `env -C`/`--chdir` targets
  are checked like `cd`; `unset` is followed and `env -i`/`-u` on a push refused; a push setting
  GH_*/GITHUB_*/PATH (which can make the scan skip) refused; unquoted and `src:dst` current-branch
  substitutions pass; a test for a lookup that fails with only -c options. 10 mutants red.
- ✅ Round 8 (fresh Opus, 1 Blocking + 4 Should-fix): `$(git branch --show-current) --no-verify`
  hid the flag in the substitution's trailing group: an unquoted substitution counts only when a
  separator or the end follows it. Structural for the recurring "make the scan skip" class: the
  hook now fails closed when gh cannot list the private repos, with the owner taken from the
  push URL, so phylax's GH_*/PATH and env -i/-u refusals are gone (also the over-broad refusals
  in plain repos). A push reading a config file after any earlier command in the call waits
  (git writes files too); env options parse as getopt does, and an unread spelling is refused;
  `git config KEY` is a read. 8 mutants red.
- 📋 Deferred: `bash -c` / `eval` / pipe-into-`sh` wrappers and `!` shell aliases skip every guard: #410.
- 📋 Built on #404's branch (`wip/private-names-on-404`); after #404 squash-merges, rebase onto
  main, resolve #406's checks.md/SKILL.md row-17 edits, force-push to fix/private-names-push-396.
- 🔧 Round 9 (fresh Opus, 1 Blocking + 2 Should-fix) fixes in this commit, NOT yet re-reviewed:
  push reading input (`<`, `N<`, heredoc, /dev or /proc config) refused in a hooked repo; the
  hook saves git's ref lines and runs git with /dev/null stdin; the scanner's own git/gh read
  /dev/null and gh ignores GH_REPO; owner = union of the repo owner and a properly parsed URL
  owner; the substitution check reads only the push's own words, redirections allowed; the
  env-option refusal removed (getopt parsing + fail-closed hook cover it).
- ✅ Round 10 (fresh Opus, 1 Blocking + 1 Should-fix): an alias hid `--no-verify` after the branch
  substitution (the check anchored on the word push): it now reads the whole call; in hook mode
  an empty private listing refuses unless gh is signed in as the owner (another account of the
  same person hides the names); the hook's message says how to install gh or sign in; a test
  for /dev/stdin config without a redirection. 3 mutants red.
- ✅ Round 11 (1 Blocking, 1 Should-fix): `$(git branch --show-current) &>/dev/null --no-verify`
  passed (the regex read `&` of `&>` as a separator; quote tricks too). Third time for this
  class, so the regex model is gone: in a hooked repo a push call may hold only a simple
  double-quoted substitution or an unquoted SAFE_REFS one followed by file redirections or
  N>&M and then a separator or the end (READABLE_SUBSTITUTION); any other `$(` or backtick is
  refused, pointing at the quoted form. A differential test runs 126 lines through bash with a
  git stand-in and fails if any line hands git --no-verify and phylax allows it. The hook now
  refuses whenever gh's login is not an owner (a partial listing from a collaborator account
  passed). 3 mutants red.
- ✅ Round 12 (2 Blocking, same class, 4th time): the regex matched `""$(...)""` across a closing
  quote and missed `$(...)#` (bash keeps the #), and $'\x2d-no-verify' was decoded wrongly by
  strip_heredocs. Structural fix: shell_tokens(), a one-pass quote-aware lexer over the command
  as written (before strip_heredocs), splits words, redirections and separators as bash does;
  in a hooked push call every word holding `$(`, a backtick or `$'` must be a whole simple
  quoted substitution or a bare SAFE_REFS one followed only by redirections and a separator.
  Bash differential widened (quote-across, `#`, `>&2`, escaped and prefix spellings of the
  flag); a 21-row lexer table; 9 mutants red, one equivalent branch deleted.
- ✅ Round 13 (1 Blocking, 2 Should-fix): process substitution (`2> >(cat >&2) --no-verify`,
  `--repo >(true)`) put the words after `)` out of reach (5th time for the class): a `(` or
  `)` of the call's own (subshell, group, <( ), >( )) now refuses a hooked push. The heredoc
  commit and `gh pr create --body "$(cat <<'EOF'...)"` were refused: the lexer now reads
  strip_heredocs(as_bash=True), bodies out, comments and $'...' kept. Deep `"$(` nesting
  raised RecursionError and could fail open: one loop with its own stack, and any exception
  in the push check refuses. Expansions count only outside single quotes. 7 mutants red, one
  redundant form deleted.
- ✅ Round 14 (1 Blocking, 3 Should-fix): `x="main --no-verify"; git push origin $x` (the flag
  loop expanded a variable to one word; 6th time for the class): a variable whose value holds
  a space, or any IFS assignment, refuses. Pushes hidden from the parser (a heredoc body, a
  backtick comment, `${...}` quotes): a backstop reads the letters, not the shapes; in a
  hooked repo, a call naming more pushes than the parser checked and holding a hook skip
  (no-veri, hookspath, include.path, includeif, git_config_, config-env, quotes and
  backslashes out) refuses. Escaped backticks no longer count as expansions; one opener copy
  per line in strip_heredocs (was quadratic). 10 mutants red; hidden lines checked with bash.
- ✅ Round 15 (4 Should-fix): the backstop counted "push" in prose and refused 8 of this branch's
  own commit messages; it now counts only pushes bash runs that the parser did not read:
  command words (the lexer's against the parser's own words, which also closes the alias
  case) and push text inside a substitution or an unquoted heredoc's substitution. IFS refuses
  on any mention (IFS+=, read IFS, printf -v IFS). strip_heredocs now matches bash on three
  lines bash confirmed: a body starts after a quote the opener's line left open, << inside
  ${...} is text, and ${...} in double quotes nests quotes (all guards share it; every suite
  green). 9 of 9 mutants red after pinning.
- ✅ Round 16 (2 Blocking): a bare `${x:+ #}` hid the rest of the line from the lexer (its #
  read as a comment); a heredoc body began inside a `$(` or backtick opened after `<<` on the
  same line, and `# )` inside `$(` closed it. The lexer sends a bare `${` through
  _construct_end with a `}` frame, which skips comments inside `$(`; strip_heredocs starts a
  body only at the depth `<<` was read, with backtick frames, and ends a comment at a closing
  backtick (every guard suite green); `<(`/`>(` text refuses on its own; `$((` no longer
  counts as a command substitution. 7 mutants red.
- ✅ Round 17 (3 Should-fix, all (b) lines built to hide a skip): the heredoc depth rule counted a
  subshell's `(`, which bash does not wait on (`cat <<EOF | (cat`); every `$((` read as
  arithmetic though `$((cmd) )` is a subshell; a comment in an open backtick rescanned the
  text. strip_heredocs gives `<(` its own frame and compares only the frames bash waits on (a
  running count, linear); the lexer decides `$((` with the shared is_arith; a backtick
  comment looks for its end within its own line. Round 16's two untested lines (the `${`
  frame in double quotes, `(` only inside `$(`) and this round's are pinned: 7 mutants red.
- ✅ Round 18 (1 Should-fix, (b); mergeable under the stated rule): is_arith said "arithmetic"
  when it could not tell (past ARITH_SCAN, an unclosed quote), the safe side for `<<` but not
  for its two new callers. arith_reading() now answers True, False or None, skipping escapes,
  quotes and a subshell's comments as strip_heredocs does; is_arith keeps the old default for
  the other guards; command_expansion treats undecided as a command; the backstop refuses an
  undecided `((`. The plain-frame counter is pinned (bash-checked bodies), and the refusal
  message names subshells. 7 mutants red.
- 📋 Next: rebase onto main (#404 merged as caefd65), force-push to fix/private-names-push-396,
  PR body, CI, one verify on the rebased head, merge.
- Verify: `uv run pytest tests/test_private_names.py tests/test_secret_guard.py
  tests/test_git_guards.py tests/test_denial_log.py tests/test_sisters_security_floor.py`, also with
  `TECHNE_GUARD_PYTHON=$(uv python find --no-project 3.9)`; `make lint`.
