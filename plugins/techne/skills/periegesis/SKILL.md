---
name: periegesis
description: "Walk the user through a live app feature by feature in a shared browser to find human UX friction, run a cognitive walkthrough, record a friction log, and file ranked issues. Use when asked to \"walk me through\", \"tour the app\", \"find UX friction\", run a \"usability walkthrough\", or keep a \"friction log\". Not for pre-merge code review (techne:elenchus), a tmux REPL smoke (techne:theoros), or a Zensical docs-site audit (techne:docs-site)."
disable-model-invocation: false
---

# Periegesis

`<skill-dir>` is the directory holding this SKILL.md.

περιήγησις: "a guided tour" (Pausanias' *Periegesis*), said "perry-uh-JEE-sis". You are the tour guide, and the user is the visitor. Walk them through a live app one feature at a time in a shared browser so they decide where human user-experience friction sits, then turn each class of friction into a tracked issue.

## Rules of the tour

- **Never fix during the tour.** Fixes go through the filed issues afterwards.
- **Never defend the design during the tour.** When the user hesitates or misclicks, record what happened instead of explaining why the interface works that way.
- **Keep human reactions apart from machine checks.** The user's reactions live in their own section; console errors, load time, contrast and phone-width layout live in a separate measured section.
- **One issue per class of friction.** Group repeated instances under one class instead of opening one issue per click.

## Method

`# research(2026-11)`

- **Context before chronology (Stripe friction logs):** state who is touring, their experience level, what they are trying to do, which parts are covered, and the tour size (`S`, `M` or `L`). Narrate step by step, then file tracked issues (`https://dev.to/stripe/how-we-use-friction-logs-to-improve-products-at-stripe-i6p`).
- **Four questions at each step (cognitive walkthrough):** walk through realistic tasks. Ask four questions at each step: will the user try to do the right thing, will they notice the control, will they connect it to their goal, and will they see progress (`https://your.wa.gov/cx-resources/cognitive-walkthrough/`).
- **One person's log is a hypothesis (Chameleon friction logs):** rank classes by `severity x frequency`. Keep the visitor's reactions separate from machine-measured findings (`https://chameleon.io/blog/friction-logs`).

## 1. Setup

Agree on the tour scope with the user in one short message:

1. **Target:** the live URL or local app server to open.
2. **Visitor persona:** who is touring, how experienced they are with the domain and tool, and their main goal.
3. **Coverage and size:** which parts of the app are in scope and the tour size (`S` for one flow, `M` for a surface, `L` for the full app).
4. **Tasks:** 3 to 6 realistic tasks the visitor will try during the tour.

Once agreed:

- Open a shared Playwright browser at `1920` wide (`1920x1080`) so the user watches the same window. Use the Playwright MCP browser (`browser_navigate` and `browser_resize` to `1920` by `1080`) when available; otherwise launch headed Chromium in a backgrounded Playwright session (`uv run --no-project --with playwright==1.63.0 python ...`) so the window stays open between steps.
- Copy `<skill-dir>/templates/friction-log.md` to `docs/friction/<YYYY-MM-DD>-<surface>.md` in the target's repository, fill the **Context** block, and create `docs/friction/<YYYY-MM-DD>-<surface>/` for screenshots.
- **Optional voice:** if `keryx` is installed and active, narrate each tour step aloud in one short line before the user tries it.

## 2. Tour

Walk one feature at a time:

1. State in one or two sentences what the feature is for, without explaining how to operate it.
2. Ask the user to try one of the agreed tasks while you watch the shared window.
3. Pause for the user's reaction in a few words.
4. Ask at most **one** follow-up from the four cognitive walkthrough questions:
   - Will the user try to do the right thing?
   - Will they notice the control?
   - Will they connect the control to their goal?
   - Will they see progress?
5. Save a screenshot under `docs/friction/<YYYY-MM-DD>-<surface>/` whenever friction appears or a key state changes.
6. Only after the user has reacted and you have logged the step, explain how the feature works if they are stuck, then move to the next feature. Never justify or defend the design.

## 3. Log

Record each friction the user names as one line in `docs/friction/<YYYY-MM-DD>-<surface>.md` under **Tour log**:

- `step`: step number and feature name
- `task`: which agreed task was attempted
- `expected`: what the visitor expected to happen
- `happened`: what actually happened
- `severity`: `blocker` (stops the task), `slows` (causes detour or hesitation) or `polish` (visual or wording rough edge)
- `screenshot`: PNG path relative to the log file (`<YYYY-MM-DD>-<surface>/...`)

After the tour tasks finish, run machine checks on the same target and record them in **Machine findings**, never mixed with the user's reactions:

- **Console and page errors:** uncaught exceptions, failed requests and `console.error` lines.
- **Load time:** initial load and key route or view transitions.
- **Contrast:** WCAG AA contrast check (`axe-core` via `axe-playwright-python==0.1.8` or computed-style check).
- **Phone width (`390x844`):** horizontal overflow, clipped controls and readable text at mobile width. Run in a separate headless pass or restore `1920x1080` afterwards so the shared window stays wide.

## 4. Close

1. Group the logged frictions into classes (for example, missing feedback, hidden control, unclear label) and rank them by `severity x frequency`. Note in the summary that one person's tour is a hypothesis until confirmed across users or sessions.
2. File one GitHub issue per **class** of friction (not one per instance) with `gh issue create`, picking labels defined in the target repo (such as `enhancement`; check `gh label list` if unsure), and link each issue from the log's **Ranked classes and issues** table.
3. When a friction is a pattern that would recur in other projects, invoke `/techne:lessons` to record a decided quality lesson.
4. Close the shared Playwright browser.
5. Remind the user that fixes happen through the filed issues afterwards, not during the tour.
