# techne — Implementation scratchpad (feat/denied-calls-399)

The active TODO list for whatever's in flight right now. Queued specs live in [ROADMAP.md](./ROADMAP.md).

## phylax denied-calls log (issue #399, PR #404)

- Slice: each phylax deny is one row in `~/.local/state/phylax/denied-calls.jsonl`; the same session's
  next call a phylax hook sees is logged under the same id. Local only, 0600, redacted, 1,000-char cap.
- ✅ agy's first pass (squashed into this branch's single commit).
- ✅ Opus review fixes:
  - Latency: CI's email_greeting went 2.03x to 2.60x of the python3 floor (eager pathlib, uuid and regex
    compiles on every call), and CodSpeed's triage benches doubled (a scandir and an exception on every
    Bash call). Now the pending folder exists only while a record waits; git_guards checks it with one
    `access()` and imports nothing; denial_log imports no pathlib/uuid and compiles its patterns lazily.
  - Guard names: each git_checks refusal records its guard (`Verdict.deny(guard, why)`) and the shape
    check names the shape (`command_shapes.guard_of`), replacing a guess from the reason text and a
    "first option alphabetically" pick.
  - register.ts now passes `session_id`: main-thread denials all landed in one shared "default" session.
  - The logged command is the command, not the whole hook JSON; Agent prompts and email bodies are cut.
  - Redaction adds Anthropic, OpenAI project, AWS, Slack, Google keys, URL credentials, `--password X`;
    `gh auth login` and similar look-alikes are kept (gh auth login, --with-token < file). Reasons are redacted too.
  - `same_effect` renamed `same_action` and documented as a word-overlap guess; `seconds_after` added.
  - One JSONL appender (`hooks/jsonl_log.py`) shared with secret_scan's log. Doctor counts deny and
    next_call rows of the last 7 days across the rotated file.
  - GitGuardian 40877600 was a fake fixture (`supersecret123`) in eb59726; the squash drops that commit.
- ✅ Gate trimmed to 3.4 us (39aaabd): no expanduser/join. Local latency: email_greeting 2.30x, model_guard
  1.96x, git_guards 1.21x/1.72x, all within budget; `make plugin-test` clean (17 mod tests, tsc).
- ✅ Bench red (CI git_guards-no-git wall 1.27x vs 1.09x): wall is noise-dominated (main alone 1.05-1.22x
  locally), but hyperfine's instructions ratio showed a real +0.033: `git_guards.py` runs as __main__,
  which Python never caches, so its 31 new lines recompiled on every Bash call (~130 us). The slow path
  moved into denial_log (`next_bash_call`, `shapes_denied`) and the path into git_options (both cached):
  instructions now main 1.199 vs branch 1.208, compile +17 us. Wider fix for every hook filed: #409.
- ✅ Abandoned records: a session that ended after a deny kept the folder, and every session's slow path,
  forever. A deny now sweeps records older than an hour; another session's record costs one access()
  and no JSON parse (`_raw_session_id`, differential-tested against the full parse).
- ✅ Never-block: the git_guards slow path was unwrapped after the move; a broken or missing denial_log
  refused every Bash command. Restored try/except, with a test (missing and raising module).
- ✅ Test isolation: hook tests and mutation runs wrote 574 rows and mutant-named files into the real
  ~/.local/state/phylax. conftest now gives every test its own XDG_STATE_HOME; junk moved to scratch.
- ✅ Round 2 (fresh restart, Opus): CI mutation red (88 survivors) and bench red.
  - Most survivors were refusal-message lines the PR only re-wrapped (ruff's trailing comma put
    them in the diff); refusals now keep main's lines (`why = (...)`, then `deny(KEY, why)`).
  - Real gaps killed: each refusal site's guard (16 sites, one command each), file modes on both
    open paths and the folder race, same_action's pr/issue branch, raw_value and stale-age
    boundaries, rotation at the cap, clip's scan window, HOME unset, the inline gates vs
    pending_any. Redundant `str(tool_input)` args and the "git_guard" fallback removed.
  - 8 strict equivalents in mutation/equivalent.toml, each with its proof.
  - Perf: model_guard and email_greeting imported denial_log on every call (2.2 ms warm vs a
    12.5 ms floor); agy's commit had widened their bench ratios to hide it. Baseline restored to
    main's; both now gate on one access(). CodSpeed's -16% is in-process repeated main() calls
    (one more os.environ lookup + access per call, cProfile); per process it is a few us.
- ✅ CI round 2: validate green; one survivor left (the first open, flags dropped), killed by a repeated-deny test. Local latency budgets pass (email_greeting 2.34x of 2.6x). Interleaved hyperfine, instructions vs the python3 floor, main/branch: git_guards-no-git 1.199/1.216, model_guard-agent 2.024/2.304, email_greeting-draft 2.558/2.832; the last two are refusal cases, so that is the cost of logging a denial (import 0.7 ms warm + two writes), paid only on a refusal.
- ✅ Verify round 3 (fresh Opus, 1 Blocking + 3 Should-fix): the `rb` equivalence proof was false (bytes json.loads reads UTF-16): entry dropped, mutant killed by a UTF-16 record test; clip drops the word its window cuts, so a token cut short can never slide into view after a long redaction; the never-block test runs over all four hook paths; docs say gone-folder refusals are logged and what Agent and email refusals log.
- ✅ Verify round 4 (fresh Opus, 3 Should-fix): two equivalence hashes went stale with a docstring
  edit (recomputed; CI's mutation shard fails on any stale entry); JSON/dict-repr keys and an
  unclosed quote at the cut leaked (both redacted now); the redactor gained private key blocks,
  JWTs, Stripe, Hugging Face, Authorization values and command-line credentials.
- ✅ Verify round 5 (fresh Opus, 4 Should-fix): `-u`/`--user` fired outside curl (docker, sudo):
  now curl-only; the JWT and mysql patterns were quadratic on repeated input: anchored and
  bounded; `gh secret set --body` and `docker login -p` redacted; docs state redaction is best
  effort. Weak-redaction recurred four rounds, so two property tests now sweep every pattern:
  adversarial repeats under a time budget, and 50+ ordinary commands left unchanged.
- ✅ Verify round 6 (fresh Opus, 2 Should-fix): the timing test barely separated linear from
  quadratic, so it now asserts on scaling (4x input, under 9x time; quadratic shows 16x); ordinary
  commit text was mangled ("Bearer support", "auth: handle", `--secret id=`, `--with-token <`,
  `$(gh auth token)`): Bearer/Basic need token-shaped values, a bare `key:` needs a
  secret-looking value, flag values skip references and redirects; PyPI and npm tokens added.
- ✅ Verify round 7 (fresh Opus, 1 Blocking + 1 Should-fix): the new `key: value` rule was
  quadratic (an unbounded lookahead) and the hand-picked fragment list missed it; routine commit
  text was still mangled. Values now pass one shape gate (SECRET_WORD, case-sensitive, every
  lookahead bounded), Bearer/Basic one credential shape; the adversarial sweep is generated from
  every keyword x separator (catches the unbounded lookahead: 18 failures).
- ✅ Verify round 8 (fresh Opus, 1 Blocking + 1 Should-fix): a prose `key: value` secret cannot be
  told from a code identifier (getAccessToken2), so that rule and the bare Authorization one are
  gone (a missed prose secret is the stated limit); Bearer/Basic need mixed case plus a digit or
  base64 symbol; bounded runs gained an unbounded tail, so a token over 255 characters is
  replaced whole. The reader's 9 mangled commit lines joined the ordinary corpus.
- ✅ Verify round 9 (fresh Opus, 2 Blocking): the `--flag value` rule rewrote commit and PR titles
  naming a flag ("add --token flag"), and `KEY=` read a search pattern's closing quote as a value
  (`grep "api_key="`): a flag value must be more than a plain lower-case word, and a KEY= value
  cannot start at a quote then a space, or be None/null/true. 11 lines joined ORDINARY.
- ✅ Verify round 10 (fresh Opus): each over-redaction fix opened an under-redaction (the
  lower-case flag-word exemption let `docker login --password <word>` through). Decided:
  privacy over readability in a local log, so over-redaction is the accepted direction (docs say
  so); the exemption is reverted; `KEY=` needs a value right after `=` (bash `GH_TOKEN= gh`);
  the `"key":` rule mirrors the search-pattern quote guard.
- ✅ Verify round 11 (fresh Opus, 5 Blocking): the curl rule was quadratic on a long `=` tail
  (classes overlapped after `-u`), which the repeat-fragment sweep never tried, so a head plus
  long-tail sweep now runs over every pattern; `KEY=` matched only a keyword at the end of the
  name (AWS_SECRET_ACCESS_KEY, SECRET_KEY_BASE, GH_PAT now redact); credential headers, curl
  --proxy-user/-U/--oauth2-bearer, uv/twine -p/-t, npm _authToken and token-only URL userinfo
  added; command-anchored patterns repeat (bounded) to catch a second flag. The PR was
  CONFLICTING after #405/#406, so no CI ran: main merged in. GitGuardian's flag was IMPL.md
  quoting a sample password: replaced.
- ✅ Bench red (Heph, run 45349496741: model_guard-agent +22.6%, email_greeting-draft +20.8%): both
  cases are refusals, and each refusal compiled every redaction pattern in a fresh process
  (clip ~4.2 ms). Each pattern now has literal triggers (TRIGGERS; a property test holds them
  conservative, another that a secret-free refusal runs no pattern), so a refusal compiles only
  what its text can match. Mean of 20, interleaved, instructions vs floor (main / before / after):
  model_guard-agent 2.024 / 2.806 / 2.371 before the all-of triggers (phylax's own reason
  "pass model:" still fired three patterns; now none); email_greeting-draft 2.556 / 3.327 / 2.645.
  bench/run.py now also reports means.
- ✅ Re-bench (mean of 20, instructions vs floor, main/after): model_guard-agent 2.024/2.116,
  email_greeting-draft 2.558/2.651, git_guards-no-git 1.199/1.216: all within 15%.
- ✅ GitGuardian: both incidents were fake values (a fixture; IMPL.md quoting a sample password);
  fixtures now build CLI secrets at runtime, and the branch is squashed onto main as one commit
  (tree unchanged; old history in local branch backup/denied-calls-399-presquash), so no commit
  in the PR carries either. Check green on 93d2042.
- ✅ Last verify's items: the timing sweeps use CPU time (median of 3), so load no longer fails
  them; command-anchored flags moved to ANCHORED, run per quote-aware shell segment that names
  the command, so a flag any distance away is seen in one linear pass (no bounded gap, no
  repeat loop); cookies, http.extraHeader, subscription-key and Cookie headers, npm set and
  _password, attached forms (-ualice:x, -pX, -bX). Sweeps cover the anchored flag patterns and
  redact() as a whole; the sweep caught an unanchored npm pattern before commit.
- ✅ Verify on b8bc147 (3 Blocking, 1 Should-fix): segments split on false separators (`2>&1`,
  `\&`, `$(a; b)`), so command flags now run on the whole call once all its words appear
  (segments() gone); Authorization after -H is redacted (scheme word kept); the prefilter test
  patched re.subn, which redact() no longer calls (now re.sub, plus a positive control);
  docker/uv/npm/gh/aws words checked apart, so global options do not hide them. Nits taken:
  quoted curl -u, -HName:, --pass, -E/--cert, aws configure; the next-call record is claimed
  by a rename, so two calls at once log one row; docs note the parallel-batch case.
  4 mutants red (prefilter, all-of words, claim, scheme).
- ✅ Verify on 2553a05 (2 Blocking, 1 Should-fix): aws `--secret-string` (a flag name holding
  the word not at its end) and its escaped-JSON example (the key trigger missed `password\"`),
  `ssm put-parameter --value`, bundled `curl -su`; Nits taken: quoted npm key, `curl -x u:p@`.
- CodSpeed (advisory; only validate is required): in-process the pending check is 3.1 us
  (access() 1.7 us, the path 1.1 us), -18 to -20% on a triage that does almost nothing else;
  whole-process hyperfine stays within 15%.
- ✅ Verify on 8d6b300 (1 Blocking, 1 Should-fix): az forms from Microsoft's docs (`az login
  --service-principal -u app -p X`, `az acr login -p`, `az keyvault secret set --value`,
  `--account-key`) and attached `curl -bX`/`-EX`, which the docs called covered.
- ✅ Closed-list sweep on 05d10ec (14 tools, one pass): quoted values with spaces in every
  anchored rule; new entries for git (user:pass@ proxy, smtp pass), wget, kubectl, gcloud,
  psql, ssh-keygen and every mysql* tool (-p, password X, user:pass@host, SQL that sets a
  password); aws --value/--sse-c keys/ParameterValue, az key flags, curl proxy pass/cert, uv
  auth; sshpass -p anywhere (the docs said so); KEY= learns passphrase. Each entry's triggers
  name what its patterns need, so an ordinary git refusal runs none (the trigger test now
  checks pattern matches, not command words). 49-template sweep test, 8 keep lines.
- ✅ Heph: x_safe_id__mutmut_9 registered as equivalent ('X' already passes isalnum()); key
  recomputed locally and matches CI's.
- ✅ Verify on 35759c2 (2 Should-fix): the long-tail sweep flaked under CI load (USERINFO
  started a match after every `=` and scanned 256 characters: `=` is out of the user part,
  now ~20x cheaper); MySQL's SET PASSWORD FOR, IDENTIFIED WITH ... BY and PASSWORD('X') forms
  (each gap bounded, so a run of spaces stays linear). The trigger test reads SWEEP too.
- ✅ Verify on c20f6f3 (2 Should-fix): the SQL gaps stopped at a newline, so multi-line SQL in a
  heredoc leaked again, and a quoted plugin name (IDENTIFIED WITH '...' BY) leaked: gaps now
  stop at `;`. Nits taken: an empty proxy user (`:X@host`), whitespace gaps to 200.
- ✅ Verify on 28e3bde (1 Should-fix): a `;` inside a quoted account name ('a;b'@h) ended the
  gap: gaps now step over a quoted string whole (two branches on different first characters,
  so linear: 3.0-4.4x time at 4x input). Two Nit cases pinned in SWEEP.
- 📋 Next: one verify on this regex, CI green incl. mutation, merge.
- Verify: `uv run pytest tests/test_denial_log.py tests/test_phylax_doctor.py tests/test_git_guards.py
  tests/test_model_guard.py tests/test_email_greeting.py tests/test_command_shapes.py tests/bench`;
  `make plugin-test`; `uv run pytest tests/test_hook_latency.py` under the heavy lock.
