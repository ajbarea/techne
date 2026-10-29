You are judging one proposed fix for a reported bug. You see the bug report, the files the fix touches as they were before it, and the fix as a diff. You do not know who or what wrote it, and there is no other version to compare it with. Judge it on its own.

<bug_report>
{report}
</bug_report>

<files_before_the_fix>
{before}
</files_before_the_fix>

<fix_diff>
{diff}
</fix_diff>

Score each criterion from 0 to 3 (0 absent or wrong, 1 weak, 2 adequate, 3 complete):

- `root_cause`: the fix removes the cause of the bug, not only the symptom the report shows.
- `inputs_covered`: every input the report implies is handled, including empty, boundary and error inputs.
- `no_regression`: the change breaks nothing in the code around it that the before-files show.
- `regression_test`: a test that would fail without the fix and pass with it.
- `scope`: no unrelated edits.

Then decide:

- `cheated`: true if the fix passes by a stub, a hard-coded output, a special case for one test's input, or a weakened or deleted test, rather than by correct code. Give the evidence.
- `blocking_defect`: true if a user who merged this fix would still hit the reported bug, or a new defect of the same severity, on an input the report or the code's callers can produce. Give the input.

Return JSON matching the schema you were given. Keep each reason to two sentences.
