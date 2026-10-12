# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

### Onboarding pass — every plugin as easy to set up and cite as epistole (spec 2026-10-12)

**Why.** A new user should get from `/plugin install` to a first working command without reading
source, and the marketplace should be citable by DOI. Today only epistole has a setup entry point;
techne, graphe, dokimasia and phylax have no README; a missing `latexmk` is a Python traceback and a
missing `uv` is silent in keryx; the cited version 1.2.0 has no tag, release or DOI.

**Decisions** `# research(2026-10)`
- One pattern, copied from epistole, for each plugin that has setup (techne, graphe, phylax; epistole
  already has it): `plugins/<p>/AGENTS.md` is the runbook an agent follows; `skills/setup/SKILL.md`
  (`/<p>:setup`) reads it and runs a read-only doctor. dokimasia needs only `uv`, so it gets a README
  and docs page, not a setup skill.
- Doctors are stdlib Python run with `uv run --no-project`; each check prints one line,
  `ok|missing|optional <name>: <detail>`, and a missing one adds `fix: <exact command>`
  (Debian/Ubuntu and macOS lines). Exit 0 when nothing required is missing. Shared check helpers live
  in `plugins/techne/_shared/doctor_lib.py`, copied to each plugin's `_shared/` (the guard keeps
  copies identical). Doctors never install; the setup skill may run a user-approved non-sudo fix
  (`gh auth login`, `playwright install chromium`) through `!`.
- Checks: techne: git, `gh` installed and signed in, `tmux` (theoros), the repo's
  `.claude/skill-context.md` (offer the conventions skeleton), `~/.claude/techne.toml` (optional).
  graphe: `uv`, `latexmk` + `pdflatex`, poppler (`pdftotext`, `pdfinfo`, `pdffonts`, `pdftoppm`),
  Playwright Chromium, LibreOffice or PowerPoint (optional, pptx only). phylax: Claude Code version
  for the mod, `python3` ≥ 3.9, which options are on, and for `restart_on_update` `/proc`, `tmux` or
  `wt.exe`, and a private state dir.
- Errors name the next command: fix every vague path the inventory found (graphe `latexmk` and
  poppler tracebacks, catchup `gh` missing, theoros `tmux` missing, audit/sisters missing config ->
  `/techne:setup`, epistole and keryx `uv` missing).
- Docs: each plugin gets a README (what, install, prerequisites, first use, troubleshooting, link)
  and a docs page under a new **Plugins** nav section (phylax and keryx gain entries; the epistole
  page keeps its `/epistole/` URL, which Google holds as the privacy link). AGENTS.md is the single
  runbook; the docs page embeds it if Zensical snippets work, else links it.
- Citation: README "Cite" section (BibTeX + `CITATION.cff`); every plugin.json `homepage` points at
  its docs page; tag and release the next version with `CITATION.cff` and marketplace in step.
  Zenodo mints a concept DOI from the GitHub release once AJ enables the repo there; the DOI then goes
  into `CITATION.cff` `identifiers` and a README badge.
- keryx (its own repo, own PR): `keryx doctor` (uv, `powershell.exe`, Ollama reachable, model pulled,
  audio dir on a Windows drive), AGENTS.md, and a cite pointer to techne.

**Scope.** The five plugins here plus keryx; README, docs nav and getting-started; doctor tests that
drive each missing-tool path with a stripped PATH; a packaging test that every plugin has a README and
docs page, and every setup skill an AGENTS.md; routing evals for each new setup skill.

**Out of scope.** Installers that need sudo, a JOSS paper (possible later), new skill features.

**Definition of done.** On this machine each doctor reports all required checks ok; under
`env -i PATH=/usr/bin:/bin` each names what is missing and its fix; no traceback remains on a missing
tool; every plugin has README + docs page; nav lists all six plugins; `make validate` green; the
release is tagged (with a DOI if Zenodo is on); keryx doctor merged. epistole's day-8 token check
(2026-10-19) stays open from #123.

**After that:** #96, backing the commit guards with Git 2.54 config-based `commit-msg` and
`pre-commit` hooks set through `CLAUDE_ENV_FILE`, so commits the Bash parser cannot see are
still checked. Blocked on Git 2.54 being available to test against.

## Skill collection state

Shipped plugins and skills by catalog dimension (the directory listing of `plugins/*/skills/` is the source of truth):

| Plugin | Dimension | Skills |
| --- | --- | --- |
| `techne` | **Audit** | `audit`, `ci-audit` |
| `techne` | **Drift** | `docsync`, `docs-site`, `research-grounded`, `sisters` |
| `techne` | **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| `techne` | **Review** | `catchup`, `elenchus` |
| `techne` | **Observation** | `theoros` |
| `graphe` | **Document build** | `latex`, `pdf`, `paper`, `paper-review`, `slides` |
| `dokimasia` | **Bibliography** | `check` |
| `epistole` | **Mail** | MCP server, setup |
| `phylax` | **Hooks** | git guards (a mod, `hooks/register.ts`), `restart_on_update` (command hooks) |

When picking up the next session, replace the "In flight" block above
with a full session plan (Why / Decisions / Scope / Out of scope /
Definition of done) following the same template every other sister
uses.
