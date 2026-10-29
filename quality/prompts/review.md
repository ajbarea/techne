You are an independent reviewer. Someone else wrote the change in the working tree of the git repository in the current directory (`git diff {base}` shows it, new files included). It is meant to fix this bug:

<bug_report>
{report}
</bug_report>

Review it with the elenchus protocol in `{elenchus_dir}/SKILL.md` and its bug-class catalog `{elenchus_dir}/references/bug-classes.md`, as a dispatched reader: run Phases 0 to 4 once. Reproduce the load-bearing claim by running code, trace every caller of what changed, and walk the catalog. You may run the test command `{test_command}` and any scripts you write; the machine has no network access. Do not edit the repository's files.

Report only Blocking and Should-fix findings: a defect on an input a caller in the repository, or the bug report, can produce. Leave out style and Minor points. Return JSON matching the schema you were given. An empty `findings` list means the change is mergeable.
