# schole

Read-only Brightspace (D2L) course sites for Claude Code: new announcements and content, what is due, and what came due unsubmitted, through the site's API after one browser sign-in.

```
/plugin marketplace add ajbarea/techne
/plugin install schole@techne
```

`schole-fetch --list --classes DIR` shows which course modules hold new or changed files and which of them a class repo already has by title; it reads the content tree only and downloads nothing.

Then run `/schole:setup`. Install, first use and troubleshooting: [https://ajbarea.github.io/techne/plugins/schole/](https://ajbarea.github.io/techne/plugins/schole/). Setup runbook: [AGENTS.md](AGENTS.md).
