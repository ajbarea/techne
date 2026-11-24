# Friction log: <surface> (<YYYY-MM-DD>)

> One person's tour is a hypothesis. Rank classes by severity x frequency and keep human reactions separate from machine checks.

## Context

- **Target:** <URL or app command>
- **Surface:** <surface name>
- **Date:** <YYYY-MM-DD>
- **Tour size:** <S | M | L>
- **Visitor persona:** <who is touring and their background>
- **Experience level:** <first-time | occasional | domain-expert>
- **Goal:** <what the visitor is trying to accomplish>
- **Parts covered:** <list of features or flows in scope>
- **Tasks:**
  1. <task 1>
  2. <task 2>
  3. <task 3>

## Summary

- **What worked:** <one or two lines on smooth steps>
- **Top friction classes:** <highest-ranked classes from the close step>

## Tour log (human reactions)

Severity: `blocker` (stops the task), `slows` (causes detour or hesitation), `polish` (rough edge).

| Step | Task | Expected | Happened | Severity | Screenshot |
|---|---|---|---|---|---|
| 1. <feature> | <task> | <what the user expected> | <what happened> | <blocker \| slows \| polish> | `<YYYY-MM-DD>-<surface>/01-<slug>.png` |

## Machine findings (measured)

Measured after the tour; kept separate from the visitor's reactions.

- **Console and network errors:** <none, or count and messages>
- **Load time:** <initial load ms and key transitions>
- **Contrast (WCAG AA):** <pass, or failing selectors and ratios>
- **Phone width (390x844):** <horizontal overflow px, clipped or wrapping issues>

## Ranked classes and issues

One issue per class of friction, not per instance.

| Rank | Friction class | Severity | Frequency | Issue |
|---|---|---|---|---|
| 1 | <class name> | <blocker \| slows \| polish> | <count of steps> | <issue link> |

## Lessons recorded

- <none, or link to `/techne:lessons` entry if the pattern applies across projects>
