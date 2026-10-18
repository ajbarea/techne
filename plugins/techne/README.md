# techne

Code-repo skills: toolchain audits, CI log review, adversarial pre-merge review, commit planning, GitHub catch-up, cross-repo drift, slop cleanup, and doc/code drift.

```
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

Then run `/techne:setup`. Install, first use and troubleshooting: [https://ajbarea.github.io/techne/plugins/techne/](https://ajbarea.github.io/techne/plugins/techne/). Setup runbook: [AGENTS.md](AGENTS.md).

## Options

`clean_finished_work` (off by default, set in `/config`): at session start, remove worktrees and branches whose PR merged and that nothing is using, and report what a merge left behind. Details: [auto mode](https://ajbarea.github.io/techne/skills/sisters/#auto-mode).
