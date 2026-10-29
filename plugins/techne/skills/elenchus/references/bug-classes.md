<!-- budget: 4400 words -->
# Bug-class catalog

Every class of bug this fleet has already paid for once. Authors walk it before asking for review; readers walk it while reviewing and tag each Blocking or Should-fix finding with its class slug. A finding that fits no class is tagged `new: <short name>`, and the daily fold-back adds it here from the findings ledger (see **After merge** in SKILL.md).

The **core rubric** (classes 1 to 9) is walked on every review: for each, find the falsifying case or clear it explicitly. The **learned classes** are walked where the diff touches their trigger: a parser, a hook, a destructive op, a test of async work, a released artifact, a sweep, a command the agent itself runs.

Each class has the same four fields:

- **Symptom:** what you observe when the bug is present.
- **Question:** the one question, asked of the diff, that catches it.
- **Guard:** the test, check or structural fix that prevents it.
- **Incidents:** where it bit, as `repo#PR round (date): what happened`, joined by `; `, newest last, at most three; adding a fourth drops the oldest, which git history keeps. A private repo is named by what it is, not by name. When an addition would pass the word budget, merge overlapping classes or trim incidents first; raising the budget is a deliberate edit in that PR.

A class whose guard became a mechanical check (a lint rule, test or hook) gets a fifth field last, **Retired:** the check and where it runs; readers skip it unless that check is missing.

## Core rubric

### 1. destructive-op-reachability: Destructive-op reachability

- **Symptom:** an `rm -rf`, overwrite, `DROP`, `truncate` or force-push runs on a target nobody meant: the source folder, the home directory, a sibling's data.
- **Question:** for every destructive op, which exact input or invocation reaches it, and can that input resolve under the thing being wiped?
- **Guard:** a refusal-path test per reachable input (the source inside the destination, `.`, `..`, `~`, a symlink, an empty variable), written in the same change as the op.
- **Incidents:** a private plugin installer (2026-06-30): `bash <dest>/plugin/install.sh` resolved its source folder under `<dest>`, which `rm -rf "$dest"` then wiped; a private rm-approval hook r1 to r10 (2026-10-21): 16 path-protection gaps in an rm-approval hook.

### 2. unmirrored-parallel-guard: Parallel-path mirroring

- **Symptom:** a new path that mirrors an existing one passes its tests, yet one input cell reaches a failure the sibling path guards against, because the structure was copied and the guard or its regression test was not.
- **Question:** for every guard and regression test on the sibling path, does the new path have both, and which cell of the input matrix (type x location x state) is untested? Test-first does not find it: it tests the behaviour someone specified, and nobody specified the missing cell.
- **Guard:** one shared helper that every parallel path calls, so a guard cannot be added to one path alone; otherwise the input matrix written as a parametrized test over every path.
- **Incidents:** a private plugin installer (2026-06-30): the folder install lacked the ZIP path's guard and its test; techne#189 r1 to r18 (2026-10-21): one `GIT_*` env strip missed in five places and a UTF-16 decode missing on three read paths, hit in 15 of 18 passes until the reads shared one helper.

### 3. migration-tolerance: Migration tolerance

- **Symptom:** state written by the old code (a saved session, a config, a cache, a database row) crashes or misreads under the new code after an upgrade.
- **Question:** does every field the new code reads have a default when state from the previous release lacks it?
- **Guard:** a test that loads a fixture saved by the previous release; new fields follow their siblings' access pattern (`.get(k, default)`, not `dict["k"]`).
- **Incidents:** a private MCP server (2026-06-29): a session reopen crashed on `dict["k"]` where the rest of the loader used `.get`.

### 4. unreached-surface: Reachability to the real surface

- **Symptom:** every test passes, yet the feature is dead: the change landed on an inner copy, not the registered wrapper, the shipped path or the docstring the model reads.
- **Question:** is the changed symbol the one the harness registers, ships or shows, and who consumes it across the whole repo?
- **Guard:** a test through the registered entry point (the wrapper, the CLI, the installed plugin), not the inner function.
- **Incidents:** a private MCP server (2026-06-29): enriched tool guidance landed on the inner function, not the FastMCP-registered wrapper.

### 5. boundary-input: Boundary and empty inputs

- **Symptom:** null, an empty string, zero rows, an unset environment variable, a missing file or an extreme value throws, mis-buckets or silently does nothing.
- **Question:** which boundary input reachable from a real caller breaks this, judged by running it, not by checking the formula?
- **Guard:** a parametrized test over the boundary cells (empty, one, first, last, the `>= N` edge, the largest value the CLI accepts).
- **Incidents:** pharos (2026-08-05): a logistic called stable in self-review raised `OverflowError` once `|log_pos - log_neg| > 709.8`, a value the CLI could produce.

### 6. looks-done-not-done: Looks done is not done

- **Symptom:** lint and tests are green, but the value path was never run end to end: a test mocks the seam it claims to cover, or one config typo aborts the whole boot.
- **Question:** what run, outside the unit tests, shows the feature working, does any test mock the very wiring under test, and has each gate or detector been seen to fire?
- **Guard:** an end-to-end run of the shipped path (start the server, run the CLI, load the plugin) recorded in the PR; a test through the unmocked wiring; a test where each gate fires (see class `vacuous-guard`).
- **Incidents:** a private MCP server (2026-06): a one-line config typo aborted the whole MCP server boot while tests passed.

### 7. flake-vs-real-red: Flake versus real red

- **Symptom:** a red check is blamed on the change when it is a pre-existing flake, or dismissed as a flake when the change caused it.
- **Question:** does the failing check touch code this change reached, and does it fail on `main` too?
- **Guard:** rerun the check on `main` before attributing it; never merge on red; a flake on `main` is a real bug with its own issue (see class `async-flake-excluded-not-awaited`).
- **Incidents:** none recorded.

### 8. claim-code-drift: Claim and code drift

- **Symptom:** the PR body, a docstring, a comment or a `Closes #N` says something the code does not do, and a `Closes` retires a gap that is still open.
- **Question:** does each sentence of the description, each changed docstring and each closing keyword match what the code now does?
- **Guard:** reread the description against the final diff after the last push; docs that state numbers read them from the code or a registry a test checks.
- **Incidents:** techne#189 (2026-10-21): 11 drift findings in one loop; techne#194 r2 to r5 (2026-10-22): each fix left the PR body or IMPL.md describing the guard it replaced; techne#200 r2 (2026-10-24): the PR body described the first commit.

### 9. wrong-altitude: DRY and right altitude

- **Symptom:** a special case is bolted on where the existing tolerance should have absorbed it, or a near-duplicate path is left for the next change to diverge.
- **Question:** is this the deep fix folded into the existing mechanism, and does a near-duplicate want consolidation now?
- **Guard:** consolidate in the same change, or record the duplicate in the deferred-findings ledger with its follow-up issue.
- **Incidents:** techne#189 (2026-10-21): one duplicate flagged in eight rounds before it was deferred to #190.

## Learned classes

### shell-semantics-mismatch: A hook's model of the shell is not the shell

- **Symptom:** a guard that parses a command line allows or denies a string bash runs differently: a comment, newline, quote, glob or expansion the parser reads one way and bash another.
- **Question:** for each token rule in the parser, what does bash itself do with this string, and has a test asked bash rather than the parser's author?
- **Guard:** a differential test that feeds generated strings to both the parser and the real shell and fails on any disagreement; after a second round of new corners, stop parsing and delegate to the real implementation, or deny the shape outright.
- **Incidents:** a private rm-approval hook r1 (2026-10-21): `rm -rf logs/a # note`, a newline, then `rm -rf ~`, where shlex's comment rule hid the second line, and new bash corners turned up in all 10 rounds until a 3,000-string differential against bash in r10.

### check-time-vs-run-time: Checked state is not the state at run time

- **Symptom:** a guard validates a path or object, then the command acts on something else: a symlink created later in the same command, a file swapped between check and use, an env var the command sets.
- **Question:** between the moment the guard reads the state and the moment the command acts, what can change it, including the command itself?
- **Guard:** resolve once and act on the resolved value (a realpath, a file descriptor, a pinned SHA), or deny the shapes that create state mid-command; a test that creates the state inside the guarded command.
- **Incidents:** a private rm-approval hook r2 (2026-10-21): `ln -s ~ hl; rm -rf hl/` passed a check that saw no `hl` yet.

### over-broad-trigger: The guard fires on commands it was not meant for

- **Symptom:** a deny or rewrite note hits a benign command that shares a word with the dangerous one, so users learn to route around the guard or switch it off.
- **Question:** which legitimate commands share this trigger's word or shape, and does each still pass with no note?
- **Guard:** a table of benign look-alikes tested beside every trip case; deny notes that name a command the user can actually run.
- **Incidents:** a private rm-approval hook r5 (2026-10-21): `git rm --cached` denied with a rewrite note meant for `rm`; techne#194 r1 to r3 (2026-10-22): a model guard refused agents that pin their own model, then calls whose `model` Claude Code drops, until it stood down instead of modelling the host.

### unmodeled-host-config: The code assumes one host, version or config

- **Symptom:** it works on the author's machine and crashes or silently skips on another OS, an older interpreter, a managed-settings path, or a config location the code never read.
- **Question:** which OS, interpreter versions, networks and config locations does this run under, and which of them has a test or a CI leg?
- **Guard:** hook and doctor tests on the oldest supported interpreter (`make test-hooks-oldest`); every config path the platform defines listed and tested; an unknown host fails closed with a named reason.
- **Incidents:** a private rm-approval hook r9 (2026-10-21): the macOS managed-settings path was not read; techne#194 r4 (2026-10-22): Explore and Plan pin `inherit` in the Claude Code binary, which the docs did not say; techne#202 (2026-10-23): epistole, built on WSL2 (no IPv6 behind NAT), hung every Gmail call on a Mac whose IPv6 route dropped packets, because httplib2 and urllib3 try addresses in turn.

### hot-path-latency: Slow work on a path that runs on every call

- **Symptom:** a hook or per-prompt check adds noticeable delay to every command: network calls, filesystem walks over 9P or NFS, sequential subprocesses.
- **Question:** how often does this path run, and what is its worst-case wall time on the slowest supported filesystem and network?
- **Guard:** return before any slow call when the trigger is absent; batch or cache the slow call; a test that times the hook against a budget.
- **Incidents:** techne#189 r1 (2026-10-21): three sequential `gh` calls per run; a private rm-approval hook r4 (2026-10-21): `/mnt` listed over 9P on every call.

### order-nondeterminism: Output depends on iteration or scheduling order

- **Symptom:** a verdict, file or test result changes between runs on the same input: set or dict order, `PYTHONHASHSEED`, directory listing order, thread timing.
- **Question:** does any result depend on the order of a set, a directory listing, a hash or concurrent completion?
- **Guard:** sort before deciding or emitting; run the test under several `PYTHONHASHSEED` values or shuffled inputs.
- **Incidents:** a private rm-approval hook r5 (2026-10-21): the hook's decision depended on `PYTHONHASHSEED`.

### unenumerated-input-shape: An input shape the code never listed

- **Symptom:** a valid but uncommon input (a bare repo, a worktree of a bare repo, a submodule, a detached HEAD, a path with spaces or a leading dash) takes a branch nobody wrote for it.
- **Question:** what shapes can this input take in the wild, and is each one a test case or an explicit refusal?
- **Guard:** the shape list written into the test module as a parametrized table before the code; an unknown shape fails closed with a named reason.
- **Incidents:** techne#189 r4 (2026-10-21): a bare repo's worktree (common dir not `.git`) broke the repo-kind check; techne#200 r3 (2026-10-24): a renamed file's old blob name escaped `rev-list --objects`; techne#222 r1 (2026-10-27): odd/even running heads went unrecognised.

### asymmetric-signal: One source wins whoever set it

- **Symptom:** a value committed to the repo, or set by one party, overrides every other party's setting, so one clone's choice silently applies to everyone.
- **Question:** who can set each input this decision reads, and should a shared committed value outrank a local one, or the reverse?
- **Guard:** an explicit, documented precedence order, tested with conflicting values from each source.
- **Incidents:** techne#189 r1 (2026-10-21): a committed `owner: solo` decided the repo kind for every clone.

### undiagnosable-failure: Every failure reads the same

- **Symptom:** a check fails, but its message cannot say why: stderr discarded, exceptions collapsed to one line, every cause mapped to one exit code.
- **Question:** if this fails on a user's machine, does the output name the cause well enough to fix it without a rerun under a debugger?
- **Guard:** keep the first line of stderr or the exception in the message; one test per failure cause asserting its distinct reason.
- **Incidents:** techne#189 r8 (2026-10-21): stderr went to DEVNULL, so every failure read the same.

### option-injection: A value is parsed as an option

- **Symptom:** a user-controlled value starting with `-` (a host, a path, a branch name) is read by the called program as a flag.
- **Question:** can any argument passed to a subprocess start with `-`, and is it placed after `--` or rejected?
- **Guard:** `--` before positional values, or refuse a leading dash; a test with a value like `-oProxyCommand=x`.
- **Incidents:** techne#189 r10 (2026-10-21): an ssh host starting with `-` reached `ssh -G`.

### unvalidated-destructive-override: An override reaches a destructive command unchecked

- **Symptom:** a new env var, preference or argument is interpolated into `rm`, `rsync --delete`, an overwrite or a shell string, so `.`, `..`, a real user folder or a quote destroys data or injects a command.
- **Question:** which commands does this override reach, and what stops a dangerous value before each one?
- **Guard:** an allow-list pattern plus a refusal of a non-empty foreign folder, with refusal tests for `.`, `..`, a real user folder and a quote, all in the same change as the override.
- **Incidents:** klepsydra#31 (2026-10-20): `KLEPSYDRA_STAGE` in `scripts/build-windows.sh` could aim `rsync --delete` at a real folder in the Windows user profile, and a `'` injected PowerShell.

### inconsistent-verdict-quantifier: Halves of one check use different quantifiers

- **Symptom:** a negative control passes even with detection killed in one cell, because one half asserts `all(...)` over every cell and the other `bool(filtered)`, an `any` over a subset.
- **Question:** across the family of verdicts in this file, is each one an any or an all, and do they agree?
- **Guard:** read the verdicts side by side along one dimension; trip the control by silencing one cell and requiring the verdict to flip.
- **Incidents:** pharos#31 (2026-08-16): one of eight verdicts used `bool(filtered_list)`, and a reproduce pass and `/code-review high` both missed it.

### vacuous-guard: A guard or check that cannot fail

- **Symptom:** a check passes everywhere, including on the case it was written to reject, while tests are green and the prose calls it enforced.
- **Question:** what input makes this guard fail, and has anyone switched off the thing it protects and watched a test go red?
- **Guard:** a mutation check: flip each guard condition in turn and confirm a test fails (mutmut for Python, Stryker for JS and TS, or by hand for a few conditions); assert that edit scripts changed the file.
- **Incidents:** a private copy eval (2026-09-18): `\bmg\b` never matched "10mg"; a private rm-approval hook r9 (2026-10-21): tests stayed green with the guard logic off until r10's mutation check; techne#201 r2 (2026-10-24): reverting two doctor `is True` gates to `bool` left every test green.

### instance-patch: The same fix again instead of a guard

- **Symptom:** the same correction is made a second, third, fourth time (a widened regex, a re-stamped provenance, a re-typed table), and wrong output ships between fixes.
- **Question:** is this the second time this fix was needed (say so out loud), and what structural change would make a third impossible, or why is a guard not worth it?
- **Guard:** on the second occurrence, build the guard (a canonical format instead of a wider regex, a generated table, a CI assert) and trip it before trusting it.
- **Incidents:** pharos (2026-08-06): artifact provenance re-stamped four times before `tests/test_artifact_provenance.py`; pharos (2026-08-06): five hand-typed doc tables corrected before they became generated blocks; techne#189 r2 to r10 (2026-10-21): an owner-marker regex widened round after round, 15 findings, until the canonical-marker redesign.

### green-exit-not-a-verdict: The exit code reports the last process, not the work

- **Symptom:** a step reports success while the log says failure or nothing was produced. Seen on `gh run watch --exit-status` and `gh pr checks --watch` (exit 0 when checks finish, pass or fail), a verify piped to `tail` (`&&` commits on red), a backgrounded pipe or task notification (the wrapper's code, not the command's), `latexmk` with every citation `[?]`, `tar --strip-components` extracting nothing, `python -m` on a module with no `__main__` guard, and ugrep exiting 2 on a complex pattern that `if grep` reads as no match.
- **Question:** was the exit code captured from the command itself, and does the output, or the count of produced artifacts, agree with it?
- **Guard:** `cmd > log 2>&1; rc=$?`, then read the log; never put a verify left of a pipe or gate a commit on one; read `gh run view <id> --json conclusion` after a watch.
- **Incidents:** pharos (2026-08-06): a notification said exit 0 for a run whose log said `MAKE_CI_EXIT=2`; a private MCP server's CI (2026-07-04): `gh pr checks --watch` exited 0 while `lint-and-test (3.12)` failed.

### overlapping-gate-runs: A second gate or an unbounded watcher reports a superseded run

- **Symptom:** completion notices arrive for runs of an earlier tree, so a stale result is reported as current; a watcher outlives its run by hours.
- **Question:** is exactly one gate and one bounded watcher in flight, and which tree does this result measure?
- **Guard:** one gate at a time; stop the old watcher before a new run; bounded polls, never an `until` with no exit; read the log, not the notification.
- **Incidents:** pharos (2026-08-06): three superseded-run notices in one session and an unbounded watcher that ran 3 h 13 min.

### kill-by-pattern: Killing or cleaning up by pattern hits a sibling's processes

- **Symptom:** a child process dies mid-suite with -15 or -9 and no signal from the test, and reads as a flake; a shared helper worktree vanishes mid-task.
- **Question:** does every kill target a PID this command started, and does any cleanup touch something another session owns?
- **Guard:** capture `$!` and kill that PID; bind port 0, not a fixed port; never `pkill` or `killall` by pattern; a shared helper worktree gets a named branch; never remove the worktree your own session stands in (a hook then starts in a deleted folder).
- **Incidents:** techne (2026-10-17): a subagent's `pkill` of its http servers SIGTERMed another worktree's visual-QA subprocess; techne (2026-10-17): a detached helper worktree was cleaned up while a sync agent used it.

### rebase-arms-live-test: A rebase turns a refusal-path test into a live request

- **Symptom:** a test asserting "X is refused" through the real transport makes a real network call after a rebase changes its precondition; the suite hangs near 0% CPU with an ESTABLISHED socket.
- **Question:** does any test rely on a host or path being absent that the merged-in branch now provides?
- **Guard:** a suite-level socket guard in `conftest.py` with an allow-list of hosts; run the suite offline after every rebase (`unshare -rn sh -c 'ip link set lo up; <test command>'`); a hang near 0% CPU with an ESTABLISHED socket in `ss -tnp` is a live request.
- **Incidents:** sphragis#39 (2026-09-23): a `fetch --org chromium` test, rebased onto a branch that added a REST host, queried chromium-review during a declared collection stop.

### async-flake-excluded-not-awaited: Racing async fields hidden by exclusion

- **Symptom:** a test compares two independently enqueued async results and passes only when both happen to reach the same stage; one CI leg reds now and then.
- **Question:** does the test poll to a stable terminal state and then assert the whole record, or does it exclude the fields that race?
- **Guard:** poll with a short interval and a timeout, then compare the full result, excluding only fields unique by construction (ids, timestamps); sweep the suite for the same pattern; no rerun-until-green plugin.
- **Incidents:** a private MCP server's CI (2026-07-04): a submit-response comparison raced state, finished_at, cumulative_rows and result, and reded the 3.12 leg.

### sweepable-flag-fixed-constants: A sweep flag with fixed companion constants

- **Symptom:** changing a flag (`--fleet`, `--clients`, `--n`) silently measures a different regime under the old labels; skipped rows print like measured failures.
- **Question:** do the companion constants scale with the flag, and does any sentinel (`None`, `-1`) mean two opposite things?
- **Guard:** express constants as positions (majority, two-thirds, all but one); assert the ladder reproduces every committed constant at the default; no silent skip guards.
- **Incidents:** pharos (2026-08-06): `COMPOSITIONS = (5, 6, 7)` measured 5-of-5 unanimity under the label "majority" at `--fleet 5`.

### metric-own-denominator: A score computed over a subset the intervention changes

- **Symptom:** a metric rises without anything being corrected, because its denominator is the set the action changes.
- **Question:** does the denominator stay fixed when the thing being measured changes?
- **Guard:** fix the denominator before the intervention; recompute the headline label by label in an independent pass.
- **Incidents:** pharos (2026-08-05): two findings' headline tables scored agreement over unanchored tasks, so anchoring a wrong item lifted the score.

### stale-forward-compat-prediction: A placeholder's prediction of an API is trusted as fact

- **Symptom:** code written ahead of an upstream release matches a predicted shape, not the real one, and a migration estimate built on it misses most of the work.
- **Question:** has every placeholder's predicted shape been checked against the upstream migration guide or release?
- **Guard:** read the upstream guide before estimating; treat each mismatch as scope; rewrite the stub's comment to admit the wrong prediction.
- **Incidents:** kourai a2a-sdk 1.0 (2026-04-29): a firewall predicted a unified `Part`, but the release shipped a flat `Part(text=...)` and matched only by protobuf permissiveness.

### ingestion-scrub-not-release-scrub: Identities leak into released artifacts

- **Symptom:** names, emails, usernames or ids from mined sources appear in committed results, fixtures or example ids, while substring exclusions drop real people.
- **Question:** is every tracked file scanned for identities before release, and are exclusions structural matches on the parsed local part and domain?
- **Guard:** a release-time scan of every tracked file of every extension; structural exclusions, never substrings; redact the release, not the corpus, flag redacted rows, and recompute the verdicts to show no number moved; the same substitution on both sides of any join key.
- **Incidents:** sphragis (2026-09-21): the first guard watched `datasets/results/*.json` and missed a test fixture with three contributors' names and addresses, and a substring exclusion on `rit.edu` also matched an unrelated address on a `.edu.cn` domain; techne#194 r4 (2026-10-22): negative test cases written to keep private names out put two of them in.

### rejected-idea-returns: A design dead end reappears in the build

- **Symptom:** an approach already rejected with evidence (costly polling, a cross-boundary call, unlicensed assets) comes back during implementation.
- **Question:** is each rejected idea recorded with its evidence and a test that fails if the build drifts back to it?
- **Guard:** a "rejected ideas and their guards" table (idea, evidence, guard) in the spec, with the guard tests written before the feature code.
- **Incidents:** klepsydra (2026-10-18): the design named three regressions to guard (polling `claude agents --json` at about 170 MB per call, the Windows app calling `wsl.exe`, borrowed-license faces) and wrote their tests first.

### unbounded-agent-resource: An agent's own command exhausts the machine

- **Symptom:** a search, build or model job an agent started runs for many minutes or holds gigabytes, and the shared host (WSL, a CI runner) swaps or crashes, taking other sessions with it.
- **Question:** what is the worst-case time and memory of this command on the largest input it can see, and how many like it run at once?
- **Guard:** cap heavy jobs (`systemd-run --user -p MemoryMax=2G`, `timeout`); bound searches over minified or generated files (`grep -m`, `rg --max-columns`, never `.{0,N}` with a large N); one heavy job at a time.
- **Incidents:** a WSL workstation (2026-10-21): `grep -o '.\{0,6000\}'` over a minified bundle ran 23 min and held 3.8 GB; a WSL workstation (2026-10-21): two concurrent 3.5 GB rembg jobs crashed WSL at 12:26.
