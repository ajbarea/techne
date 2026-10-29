You are working in a git repository checked out in the current directory. A user reported this bug:

<bug_report>
{report}
</bug_report>

A fix is already in the working tree (`git diff {base}` shows it, new files included). A reviewer found these problems with it:

<review_findings>
{findings}
</review_findings>

Fix each finding that is correct, with a regression test where the finding is testable. If you judge a finding wrong, leave the code as it is and say why in your reply.

The repository's test command is: `{test_command}`
Run it before you finish. The machine has no network access; the dependencies are already installed. Work only in the current directory and `$TMPDIR`.

When you are done, reply with one line per finding: fixed, or not fixed and why.
