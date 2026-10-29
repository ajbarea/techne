<!-- budget: 2700 words -->
# Budget-mode quality trial: pre-registration

Registered 2026-10-29, before any task was run. Nothing in this file changes after the first result is written to `quality/results/`. A deviation goes in `quality/DEVIATIONS.md`, dated, with its reason, and the report names it.

## Question and hypotheses

Budget mode lets Sonnet write the code and Opus review it. Normal mode uses Opus for both. On AJ's own work, is budget mode as good as normal mode, and cheaper?

- **H1 (quality, non-inferiority).** Budget mode's task-resolved rate is at most 5 percentage points below normal mode's.
- **H2 (cost).** Budget mode costs less per task than normal mode.
- **H3 (risk classes).** In each risk class (security, destructive operation, governance), no task does worse in budget mode than in normal mode.

Budget mode is adopted for a class of work only if H1 and H2 hold overall and H3 holds for that class. If any of them fails or the result is inconclusive, normal mode stays.

Prior evidence: Anthropic's advisor strategy (Sonnet executing, Opus advising) scored 2.7 points higher on SWE-bench Multilingual at 11.9% lower cost per task ([claude.com/blog/the-advisor-strategy](https://claude.com/blog/the-advisor-strategy), 2026-04-09). That setup differs from ours (Opus advises during the task; here Opus reviews after it), and its tasks are public. Errors usually cost more than tokens ([Zellinger and Thomson, 2025](https://arxiv.org/pdf/2507.03834)), which is why the quality test comes first and the margin is tight.

## Tasks

The task set is fixed in `quality/tasks/tasks.toml` and committed with this file. Each task replays a bug-fix PR from one of AJ's repos:

- the agent gets the tree at the fix PR's parent commit, with the fix's new test files left out, and a bug report: the linked issue as it was filed, minus any section headed Fix (its author's proposed change), or with no issue the PR's statement of the problem with its description of the change removed;
- when a hidden test calls a name, checks a message, or asserts a rule from a removed Fix section that the parent tree lacks, the report ends with an "Interface the tests use" note that states it, as SWE-bench Pro adds interface specifications ([Deng et al., 2025](https://arxiv.org/abs/2509.16941)), so a correct fix is not failed for a name;
- the PR merged after 2026-08-01, after both models' training cutoff, so neither model can recall the fix;
- the workspace is a fresh `git init` of that tree, with no history and no remote, so the fix cannot be read from later commits ([Wang et al., 2026](https://arxiv.org/pdf/2606.26300) list leaked commits and the original PR as the main cheating channels);
- each task is tagged with one risk class: security, destructive operation, governance (registered-study rules, privacy, access) or ordinary.

Replayed PRs have two known weaknesses ([Huang et al., 2026](https://arxiv.org/pdf/2607.07946)): a model may recall a public fix, and the fix's tests can reject a valid alternative. The cutoff rule and the stripped history answer the first. The blind judge answers the second, and every case where the judge and the tests disagree is reported.

**Count:** 10 tasks, 3 repeats per task per mode, so 60 task runs for the full comparison. By risk class: 3 security, 3 governance, 2 destructive operation, 2 ordinary. `quality/run.py --check-tasks` confirms, with no model, that each task's hidden tests fail on its workspace and pass with the gold patch (the parent tree plus the fix's changes outside the hidden tests), and that the gold patch raises no cheat flag. The set must stay cheap enough to rerun from one make target (`make quality`), and the brief caps it at 8 to 12 tasks.

## Harness

Both modes run through `quality/run.py` with the same prompts (`quality/prompts/`), tools and limits, and `quality/analyze.py` computes every number below. Only the implementer's model changes. The models are pinned: `claude-opus-5-5` and `claude-sonnet-5-5`. The judge is `claude-opus-5-5`. The Claude Code version is recorded with each run.

Each task run is:

1. **Implement.** `claude -p --restricted --safe-mode`, the implementer model, tools Read, Edit, Write, Glob, Grep and Bash. Bash runs in Claude Code's sandbox (`quality/sandbox.json`) with no network, so the agent cannot fetch the PR, and with no reads of the source clones, Claude's config, `/tmp`, `/mnt`, or the harness folders that hold finished runs, score copies and task checks; its temp folder is the run's own. No user settings, CLAUDE.md, plugins, memory or MCP servers load. The prompt gives the bug report and the repo's test command, and asks for a fix with a regression test. Limits: 60 turns, 20 minutes.
2. **Review.** A fresh `claude -p` session on Opus, given the bug report and the diff, follows the elenchus protocol and reports Blocking and Should-fix findings as JSON. It may run code, but any edit it makes to the workspace is undone and noted. A review that returns no findings JSON is tried once more; a second failure ends the loop there, and the run is scored as it stands, with the failure noted.
3. **Fix.** If the review has a Blocking or Should-fix finding, the implementer (the same model, a fresh session) gets the findings and the workspace once more. A second review follows. The loop stops at the first clean review or after three reviews, as the fleet's review rule does for substantive code.
4. **Score.** The harness copies the final workspace, restores the hidden test files (every test file the task's test command runs, as the fix PR left it) over it, and runs the task's test command offline (`unshare -rn`), outside any agent session. The copy is deleted after the run.

A run the harness cannot finish is retried, up to 3 attempts; after the third, it counts as unresolved, and the report lists it. A harness failure is a harness exception or a Claude Code session that exits with an error other than its time limit; a session that runs out of time is the model's failure, scored as it stands. A usage or rate limit stops the whole set without recording the run, and the set resumes from where it stopped. Every diff is taken against the commit the workspace started at, so a commit or stash the agent makes hides nothing.

## Primary metric

A run **resolves** its task when all three hold:

1. the hidden tests pass;
2. the blind judge finds no blocking defect;
3. the cheat audit raises no flag.

A task's score in a mode is the share of its 3 runs that resolve: 0, 1/3, 2/3 or 1.

## Blind judge

The judge sees the bug report, the pre-fix files the diff touches (the first 400 lines of each), and the final diff. It does not see the hidden tests, the mode, the model, the run number, or the review transcripts. Diffs are stripped of commit metadata. The judge runs as one pass after all runs finish (`run.py --judge`), over every run of every mode being compared, interleaved in a random order with seed 20261029, so neither mode is judged at a different time. For the trial, the normal-mode runs are judged again in that same pass beside the budget-mode runs. A judge call that returns no verdict is tried once more; after a second failure the run counts as unresolved. Judge bias is real (position bias: [Shi et al., 2025](https://preview.aclanthology.org/setup/2025.ijcnlp-long.18)), so the judge scores one diff per call, never a pair.

It scores each criterion 0 to 3, and returns `blocking_defect` true or false with the reason:

- root cause fixed rather than the symptom;
- every input the bug report implies is handled, including empty, boundary and error inputs;
- no regression in the code around the change;
- a regression test that would fail without the fix;
- scope: no unrelated edits;
- signs of a cheated pass: a stub, a hard-coded output, a special case for a test's input, or a test weakened to pass.

The judge prompt is `quality/judge.md`, fixed by this registration.

## Cheat audit

These checks are mechanical and run on every task run:

- **Test edits.** Scoring restores every test file the task's test command runs as the fix PR left it, so editing those cannot change a score; adding and updating tests is expected. The flag covers what scoring does not restore: a test file the command runs but the task does not restore (deleted, an assertion, test function or parametrize line removed or changed, or a skip or xfail added), and test configuration (`conftest.py`, `pytest.ini`, `tox.ini`, `setup.cfg`, `pyproject.toml`, snapshot files) given a deselect, ignore, `-k` or skip. In this task set every file the test commands run is restored, so the flag reduces to test configuration.
- **Hard-coding.** The run's added non-test code contains a literal from a hidden test's assertion lines (a string of 4 or more characters, or a number of 3 or more digits) that appears in no file of the pre-fix tree and not in the bug report, which may state a message the tests check.
- **Leaks.** The transcripts (implementer, fixer and reviewer) show a network command (`gh`, `curl`, `wget`, `ssh`, a git remote command, a URL), a shell path into the home folder, `/tmp` or `/mnt` outside the workspace, the run's temp folder, uv's folders and the elenchus copy the reviewer reads, a climb of two or more `../`, or a file tool reading outside those.
- **Judge flag.** The judge marks a cheated pass.

A flagged run counts as unresolved. Every flag is listed in the report with its evidence. Coding agents do cheat by editing tests, and Claude models do so mostly that way ([Zhong et al., 2025](https://arxiv.org/html/2510.20270)), so the first check is the one most likely to fire.

**Judge against tests.** For each run the report lists whether the hidden tests and the judge agree. Two kinds of disagreement are reported in full, not resolved by hand:

- tests pass, but the judge finds a blocking defect (possible cheat or weak tests);
- tests fail, but the judge finds none (possible valid alternative or judge miss).

## Analysis

For task *t*, let *d_t* = budget score minus normal score. The estimate is the mean of *d_t* over tasks. Tasks are the unit, because the 3 repeats of one task are not independent.

**H1 decision.** Budget mode is non-inferior when the one-sided 95% lower confidence bound on the mean of *d_t* is above −0.05. Two intervals are computed, and both must clear the margin:

1. a task-level percentile bootstrap: 10,000 resamples of tasks, seed 20261029;
2. a t interval on *d_t*.

Both are required because a percentile bootstrap gives intervals that are too narrow with fewer than about 15 clusters, and simple intervals are too narrow on small LLM eval sets ([Bowyer et al., 2025](https://arxiv.org/abs/2503.01747)). The decision uses the lower bound, not the point estimate. A pre-registered margin applied to the point estimate is not a formal non-inferiority test ([Wu and Lim, 2026](https://arxiv.org/html/2609.26532v1)), and other preregistered LLM evaluations decide on the bound ([Cochran, 2026](https://arxiv.org/html/2607.04576); [Song et al., 2026](https://www.alphaxiv.org/abs/2610.21046), with a 3-point margin).

**Margin.** The margin is 5 percentage points, set on AJ's delegation on 2026-10-28. Published LLM non-inferiority margins are 2 to 3 points on much larger sets. A 10-task set cannot resolve those, and 5 points with a lower-bound test is the strictest margin it can. The margin never widens to fit the data.

**H2.** H2 is measured as cost per task: the API cost Claude Code reports, summed over every session of a run. For each task, the ratio is the median budget-mode cost over its repeats divided by the median normal-mode cost. H2's statistic is the median of those ratios over tasks. Budget mode is cheaper when the one-sided 95% upper bound of that median (a task-level bootstrap, 10,000 resamples) is below 1. A task with a run whose cost is unknown (a session that timed out reports none) or with a zero normal-mode cost is left out of H2; with no task left, H2 is not shown. Input, output, cache-read and cache-write tokens are reported per task beside the cost. Tokens alone mislead, because the two models are priced differently.

**H3.** For each risk class, budget mode fails that class if any task in it has *d_t* < 0.

**Reporting.** `analyze.py` reads one trial's result folders and refuses a (task, mode, repeat) that appears twice, so a pilot or an old baseline is never pooled in. Every task is reported, failures included, with:

- the median and range over its 3 repeats;
- *d_t*;
- cost and tokens;
- review rounds;
- the judge's criterion scores;
- every cheat flag and every judge-test disagreement.

The secondary skill suites (below) are reported beside the trial and do not enter the decision.

## Sample size and the pilot

The trial can only be powered if the two modes rarely disagree. For a true difference of 0, a one-sided α of 0.05 and 80% power, the number of tasks needed is about (1.645 + 0.842)² × σ² / 0.05², where σ is the standard deviation of *d_t*. With 10 tasks, that requires σ ≤ 0.064. With 12, it requires σ ≤ 0.070. In terms of whole runs, the modes would have to agree on almost every run.

**Pilot.** Before the confirmatory runs, one repeat of every task runs in each mode. It gives σ and the share of tasks where the modes disagree. With one repeat, *d_t* is −1, 0 or 1, so a single task where the modes disagree gives σ of at least 0.3 and makes the trial inconclusive; the pilot proceeds only if the modes agree on every task. Pilot runs are not part of the confirmatory analysis.

**Sizing.** The required task count is computed from the pilot σ by the formula above and checked by simulation: 10,000 trials of that many tasks, resampling the pilot's *d_t* centred at 0, each judged by the t lower bound. The trial proceeds only if the count is at most 12 and the simulated power is at least 80%. Otherwise, the trial stops there and the report reads **inconclusive: normal mode stays**. The task set is not cut and the margin is not raised to make the trial fit. Power for clustered matched pairs depends mainly on the number of clusters ([Nam, 2011](https://ideas.repec.org/a/eee/csdana/v55y2011i10p2880-2887.html)), so adding repeats does not substitute for adding tasks.

## Schedule

- **Now:** normal mode runs on the full task set, 3 repeats (`make quality MODE=normal`), and the skill suites run on Opus (`make quality-skills`). That is the quality baseline for techne#226 (the fold-or-keep audit) and techne#229 (the writing gate).
- **When AJ schedules the budget trial:** the pilot, then sizing, then the confirmatory budget runs. The normal-mode baseline is rerun at that time if Claude Code's version has changed.

## Secondary: skill suites

These suites run under `claude plugin eval` with `--model` set to each model and `--judge-model claude-opus-5-5`, 3 runs per case. They give a per-skill score per model and are descriptive only:

- **elenchus, seeded bugs:** each case plants one catalog class in a small diff. A case passes when the review names the planted bug with its class.
- **graphe, length budget and plain prose:** the draft declares a budget, stays under it, and has no em-dashes.
- **schole and epistole read paths:** fixtures and MCP mocks only, never a live account.

## Stretch, after the own set works

A 10-task slice of a public benchmark that these models have not seen runs on TIGRIS, never on this PC, as a cross-check against published numbers. The choice is DeepSWE ([Huang et al., 2026](https://arxiv.org/pdf/2607.07946)): its 113 tasks were written for the benchmark and their fixes were never merged anywhere public. SWE-bench Pro's public set is exposed, and SWE-bench Verified was retired for contamination.
