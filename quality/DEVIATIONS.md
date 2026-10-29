<!-- budget: 600 words -->
# Deviations from the pre-registration

Each entry is dated, gives its reason, and is named in the report. `PREREGISTRATION.md` itself does not change.

## 2026-10-29: task notes completed before the baseline restarts (#249)

**What changed.** `quality/tasks/tasks.toml`: the "Interface the tests use" note on eight of the ten tasks now states every name, message and rule the hidden tests check that the bug report did not give. sphragis-186 and sphragis-212 gained a note; techne-220, techne-162, techne-174, techne-166, techne-206 and sphragis-149 had theirs completed. The bug reports themselves are unchanged. `quality/run.py --check-tasks` now also fails a task whose hidden tests need a name, or wording the fix adds, that the report does not state.

**Why.** The registration's task rule already required these notes ("when a hidden test calls a name, checks a message, or asserts a rule ... the report ends with an Interface note that states it"), but the task set was committed with gaps no check caught. The first four Opus baseline runs all failed their hidden tests. In three of them, nothing in the report could have told any model what the tests check: `artifacts()` (sphragis-186), `grants_file()` and the unreadable-file wording (sphragis-149), and the nested `CLAUDE.local.md` wording and nested-repo rule (techne-206). Every mode would fail such a task, so it would always score *d_t* = 0, which pulls a non-inferiority test toward "no difference" and hides a real loss ([ICH E10](https://gmp-compliance.org/guidelines/gmp-guideline/ich-e10-choice-of-control-group-and-related-issues-in-clinical-trials) calls this missing assay sensitivity). SWE-bench Verified removed tasks for the same two faults, an under-specified issue and tests that reject valid solutions ([OpenAI, 2024](https://openai.com/index/introducing-swe-bench-verified/)), and SWE-bench Pro adds interface notes like these ([Deng et al., 2025](https://arxiv.org/abs/2509.16941)).

**What it can bias.** The change was made before any budget-mode run and applies to both modes, so it cannot favour either. The notes state what the tests check, not how to fix the bug. Task selection, risk classes, margin, metric and analysis are unchanged.

**The four void runs.** techne-206, techne-166, sphragis-149 and sphragis-186, repeat 3, normal mode, under the old task hash. They stay in `quality/results/2026-10-29-baseline-void/` and are reported, but they are not pooled: `analyze.py` already refuses a set whose input hashes differ. In techne-166, a quoted relative name with a backslash was accepted as a Chrome profile. The old note's "a Windows path" allowed that reading, so the note now says a drive-letter path. The run's reviewer had flagged the same input as Should-fix, so part of that miss was the model's.

**Restart.** The baseline reruns from the start in `quality/results/2026-10-29-baseline-2/`, under the new task hash.
