# phylax

Opt-in Claude Code hooks: refuse attribution lines in commits and PRs, refuse staging COMMITS.md, refuse commits and pushes that carry a secret, refuse issue and PR bodies past their length budget, warn on commits in a main checkout, refuse a subagent call that would silently inherit the session's model, restart idle sessions onto an updated Claude Code, and route work to cheaper models while the usage allowance burns too fast.

```
/plugin marketplace add ajbarea/techne
/plugin install phylax@techne
```

Then run `/phylax:setup`. Install, first use and troubleshooting: [https://ajbarea.github.io/techne/plugins/phylax/](https://ajbarea.github.io/techne/plugins/phylax/). Setup runbook: [AGENTS.md](AGENTS.md).
