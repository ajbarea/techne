# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

### Landed: heuresis phase 1 (v1.4.0)

`heuresis` is the seventh plugin. `/heuresis:idea` captures an idea in the private ideas repository
and triages it: four scouts, a judge, `verify` and `apply`, with `BOARD.md` and `LOG.md`
regenerated and the repository committed and pushed. `/heuresis:setup` checks the tools and creates
the repository. The Lens and EPO adapters are built against documented response shapes and are not
yet confirmed with live keys.

### Next: heuresis phase 2, the gold set

Build a gold set of ideas with known verdicts and the harness that scores the pipeline against it,
and run it before trusting any verdict. Later phases are in ROADMAP.

### Then: commit guards on Git 2.54 hooks (#96)

Back the commit guards with Git 2.54 config-based `commit-msg` and `pre-commit` hooks set through
`CLAUDE_ENV_FILE`. Blocked on Git 2.54 being available to test against.

Open: the Zenodo concept DOI into `CITATION.cff` and a README badge once Zenodo mints it; epistole's
day-8 token check (2026-10-19) from #123.

## Skill collection state

Shipped plugins and skills by catalog dimension (the directory listing of `plugins/*/skills/` is the source of truth):

| Plugin | Dimension | Skills |
| --- | --- | --- |
| `techne` | **Audit** | `audit`, `ci-audit` |
| `techne` | **Drift** | `docsync`, `docs-site`, `research-grounded`, `sisters` |
| `techne` | **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| `techne` | **Review** | `catchup`, `elenchus` |
| `techne` | **Observation** | `theoros` |
| `techne`, `graphe`, `heuresis`, `phylax` | **Setup** | `setup` (a read-only doctor per plugin) |
| `graphe` | **Document build** | `latex`, `pdf`, `paper`, `paper-review`, `slides` |
| `dokimasia` | **Bibliography** | `check` |
| `heuresis` | **Ideas** | `idea`, `setup` |
| `epistole` | **Mail** | MCP server, setup |
| `phylax` | **Hooks** | git guards (a mod, `hooks/register.ts`), `restart_on_update` (command hooks) |

When picking up the next session, replace the "In flight" block above
with a full session plan (Why / Decisions / Scope / Out of scope /
Definition of done) following the same template every other sister
uses.
