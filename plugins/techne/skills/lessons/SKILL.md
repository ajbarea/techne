---
name: lessons
description: Read, add or retire a decided quality lesson so a correction carries forward to the next deck, paper, docs site or app. Use before building or restyling a web app or a project's user-facing surface, when the owner corrects how something looks or reads ("from now on", "that was wrong", "make sure we remember this"), or when asked which lessons apply. Slides, papers and docs sites load their own lessons at the start of the work; this is the way in for an app's UI and the way to record a new lesson.
---

# Lessons

`<plugin-root>` is the plugin's root directory, two levels above the directory holding this SKILL.md.

A lesson is a decision that made the work better, kept so the next piece starts ahead. Lessons live in `_shared/lessons/`, one file per surface, and each skill loads only its own: `common.md` for all, then `slides.md` or `paper.md` (graphe), `docs-site.md` or `project.md` (techne).

## Read them

For an app or a project's user-facing surface, read `<plugin-root>/_shared/lessons/common.md` and `<plugin-root>/_shared/lessons/project.md` before starting, then open that file's reference to beat and name one way the new work is better and one way it is worse before calling it done.

## Who changes them

The lesson files belong to the techne repository, `ajbarea/techne`, and change only through a pull request there: never edit the installed plugin cache, which an update overwrites. Before adding or retiring a lesson, check that the user maintains it: `gh repo view ajbarea/techne --json viewerPermission` must print `ADMIN`, `MAINTAIN` or `WRITE`.

- If it does not, or `gh` cannot tell, change no lesson file and open no pull request. Write the rule in the entry shape below and, if the user agrees, add it to the project's `CLAUDE.md` (or `AGENTS.md`), which the agent reads at the start of every session.
- Otherwise use a clone (`gh repo clone ajbarea/techne` if there is none) and a worktree on a new branch; paths below are relative to its root.

## Add one

Do this at the moment of the correction, in the same turn, instead of writing a memory note or a recap.

1. Pick the surface file. A lesson about every surface goes in `common.md`, kept identical in `plugins/graphe/_shared/lessons/` and `plugins/techne/_shared/lessons/`.
2. Add one entry at the top of the file's list, in this shape:

   ```
   ### slug: Short name

   - **Rule:** One line, in the general form, that the next agent can act on.
   - **Why:** One line.
   - **Since:** YYYY-MM-DD
   - **Check:** gate: <path>#<identifier>, test: test_name or guidance: <why it cannot be computed>.
   ```

3. Prefer a gate. If the rule can be computed, add it to the relevant checker with a test, and name both in **Check**. `tests/test_lessons.py` fails a gate whose named test never mentions it.
4. The file is public. State the general rule: no teammates' names, private incidents, course details or unpublished results. A fact only one repo cares about goes in that repo's `.claude/skill-context.md`.
5. Raise the file's `budget` line only if the words are needed, or merge entries. In the clone, run `make test-unit` before opening the pull request.

The installed copy updates on the next plugin update.

## Retire one

When a later decision supersedes a lesson, delete its body and leave one line under `## Retired` in the same file: `- \`old-slug\`, retired YYYY-MM-DD by \`new-slug\`: what changed.` Git keeps the body; the line stops the next agent from reintroducing it. A retired line that names a slug no live lesson has fails the test.

## Not this skill

- Reviewing code for a bug class: `techne:elenchus`, which has its own catalog.
