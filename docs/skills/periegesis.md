---
description: "Walk the user through a live app feature by feature in a shared browser to find human UX friction, run a cognitive walkthrough, log reactions apart from machine checks, and file ranked issues."
---

# `techne:periegesis`

Walk the user through a live app one feature at a time in a shared browser window so they decide where human UX friction sits, record a structured friction log, and file one ranked issue per class of friction.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

περιήγησις is a guided tour (Pausanias' *Periegesis*), said "perry-uh-JEE-sis". You act as the tour guide and the user is the visitor.

## When to use

- "Walk me through the app." / "Tour the app."
- "Find UX friction." / "Run a usability walkthrough."
- "Keep a friction log on this site or playground."

Not for pre-merge code review ([`techne:elenchus`](elenchus.md)), a tmux CLI smoke ([`techne:theoros`](theoros.md)), or a Zensical docs-site build check ([`techne:docs-site`](docs-site.md)).

## Usage

```text
/techne:periegesis
```

## The four stages

1. **Setup.** Agree in one short message on the target (URL or local app), visitor persona, tour size (`S`, `M` or `L`), covered parts, and 3 to 6 realistic tasks. Open a shared Playwright browser at `1920` wide so the user watches the same window, and create the log from `templates/friction-log.md`. If `keryx` is installed and on, narrate each step aloud.
2. **Tour.** Cover one feature at a time. Say what the feature is for and ask the user to try a task before explaining how. After their reaction, ask at most one follow-up from the four cognitive walkthrough questions (will they try the right thing, notice the control, connect it to their goal, and see progress). Never defend the design during the tour.
3. **Log.** Record each friction in `docs/friction/<YYYY-MM-DD>-<surface>.md`: step, task, expected, happened, severity (`blocker`, `slows` or `polish`), and a screenshot path. Measure console errors, load time, WCAG contrast and phone width (`390x844`) in a separate **Machine findings** section so measured telemetry never mixes with the user's reactions.
4. **Close.** Group findings by class, rank by `severity x frequency`, open one GitHub issue per class of friction (linked from the log), invoke [`techne:lessons`](lessons.md) when a friction reveals a recurring pattern across projects, and close the browser.

Never fix app code during the tour; fixes go through the filed issues afterwards.

## See also

- [`techne:theoros`](theoros.md): observed live REPL sessions in tmux for CLI tools.
- [`techne:docs-site`](docs-site.md): automated Zensical site build and visual QA checks.
- [`techne:lessons`](lessons.md): record a decided quality lesson when a friction pattern applies across projects.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/periegesis/SKILL.md) holds the full instructions Claude follows for this skill.
