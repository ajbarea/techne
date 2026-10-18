---
description: Capture an idea and triage it against papers, patents, products and your own work, then file it as trash, later, do or merged.
---

# `heuresis:idea`

Capture an idea and triage it against prior work. The skill saves the idea to your private ideas repository, searches papers, patents, products and your own research for anything like it, names the closest existing work, and files the idea as trash, later, do or merged, with the evidence.

Part of [heuresis](../plugins/heuresis.md): `/plugin install heuresis@techne`, then `/heuresis:setup`.
εὕρεσις is discovery. The skill's first question is whether someone already found it.

## When to use

- "I have an idea." "Save this idea."
- "Has anyone built this?" "Is this worth building?" "Triage my idea."
- Not for judging a written paper's novelty (`graphe:paper-review`).

Run `/heuresis:setup` once first. It creates the ideas repository and checks the tools. If the repository or repos folder is not set, `/heuresis:idea` stops and says so.

## Usage

```
/heuresis:idea [--ideas <path>] [--repos <path>] [--now] <idea text>
/heuresis:idea --triage <id>
/heuresis:idea --retriage <id>
/heuresis:idea --override <id> <state> [--type T] [--project P] [--duplicate-of X] <reason>
```

| Mode | What it does |
|---|---|
| `<idea text>` | Capture only. Saves the idea to the inbox and prints its id. Triage it later with `--triage <id>`. |
| `--now <idea text>` | Captures the idea, then triages it straight away. |
| `--triage <id>` | Triages an idea already in the inbox. |
| `--retriage <id>` | Triages again and adds a new verdict. Earlier verdicts stay in the idea file. |
| `--override <id> <state> <reason>` | Records your own decision without a search. Optional `--type`, `--project` and `--duplicate-of`. |
| `decline` (automatic) | When triaging an idea that asks for something illegal or that would harm people who have not consented, such as covert surveillance, the skill runs `heuresis decline <id> <reason>` instead of searching. The idea is filed as `trash` with a `declined` verdict. Capture-only and `--override` never decline. |
| `--ideas <path>` and `--repos <path>` | Point one run at another ideas repository and repos folder instead of the configured ones. Put them first, before the mode or the idea text; after that, the words are idea text. |

## How a triage runs

1. **Restate.** The idea is rewritten as one neutral paragraph with three to five short search queries. Praise and claims of novelty are dropped, so the scouts search for what the idea does.
2. **Scout.** Four scouts run in parallel and each saves records with the passage that shows what the source says.
    - `scout-papers`: OpenAlex, Semantic Scholar and arXiv.
    - `scout-patents`: EPO.
    - `scout-products`: GitHub, Hacker News and web search, including pricing pages.
    - `scout-context`: your bibliography, related-work notes, decks, ROADMAPs, marketplace and earlier ideas.
3. **Pool.** A script merges the scout files into numbered records with a coverage line per source.
4. **Judge.** The judge reads the restatement, the pooled records and the context scout's facts, and has no web access. It picks the closest rival, argues first that the idea is not new, then compares the two on domain, purpose, mechanism and evaluation, and proposes a verdict. It copies a verbatim quote for each record it relies on.
5. **Verify.** A script checks that every quote appears in its record, and fetches the source again where it can. A record whose quote fails is dropped. If the closest rival's quote fails, the judge runs again once without it.
6. **Apply.** A script enforces the rules, writes the verdict into the idea file, regenerates `BOARD.md` and `LOG.md`, and commits and pushes the ideas repository.

If a capture or apply cannot push, the idea stays saved on disk and the message names the cause. Fix it; the next capture or triage publishes every pending change under `ideas/` and `runs/`, and the `heuresis publish` command does the same on its own.

The skill reports four lines: the state, type and project; the closest rival with its link; the reason; the next step.

## The rules

They run in code, so no prompt can skip them.

- **`do`** needs a type, a verified closest rival with all four comparisons filled in, and at least one paper source that returned results. Otherwise the verdict becomes `later`, with the reason "insufficient evidence" and a revisit date 90 days out.
- **`merged`** needs `duplicate_of` to name an idea that exists in the repository.
- **`later`** always carries a revisit date, and `BOARD.md` lists it as due once the date passes.
- A quote that is not in its record, or a record that does not verify, never supports a verdict.

States are `inbox`, `trash`, `later`, `do`, `building`, `shipped` and `merged`. Types are `product`, `tool`, `research` and `improve`. For a product idea the judge also records paying rivals with their pricing, demand links, the riskiest assumption and the cheapest test.

## Files written

All inside your ideas repository.

| Path | Holds |
|---|---|
| `ideas/<id>.md` | The idea, its state and every verdict with its evidence. Text you add by hand outside the sections heuresis writes is kept, in order, under Notes. |
| `runs/<id>/` | The latest run's working files: restatement, scout records, pool, judge output, verification. A retriage replaces them. |
| `BOARD.md` | Needs triage (inbox and invalid files), Due for revisit, Do (by project, then type), Later, and Closed (counts with links). Regenerated. |
| `LOG.md` | One line per verdict (triage, override or declined), newest first. Regenerated. |
| `projects.toml`, `context.toml` | Seeded by `heuresis init`. `heuresis context` reads them to find your research sources, and the `--project` names come from `projects.toml`. |

## Keys

Save keys in Claude Code's secure storage: run `/plugin configure heuresis@techne`, paste each key into its masked field, and restart Claude Code. Or run `/heuresis:setup` and choose the file route: it prints a `.env` template, you fill it in at a private path outside any repository, and its store script saves the keys and prints only their names. Claude Code keeps the keys in its secure storage. At session start heuresis writes them to a private (0600) per-process file in its plugin data folder that Bash commands load, and deletes the file when the session ends. A key already in the Bash environment, such as one exported in your shell profile, wins.

OpenAlex, arXiv and Hacker News run without a key. `OPENALEX_API_KEY` raises OpenAlex's daily search budget, and `OPENALEX_MAILTO` identifies you to OpenAlex. Semantic Scholar, EPO and GitHub show `skipped` in the verdict's coverage line without their keys, and the rest still run.

| Option (variable) | Source |
|---|---|
| `s2_api_key` (`S2_API_KEY`) | Semantic Scholar |
| `epo_ops_key`, `epo_ops_secret` (`EPO_OPS_KEY`, `EPO_OPS_SECRET`) | EPO patents |
| `openalex_api_key` (`OPENALEX_API_KEY`) | Optional for OpenAlex |
| `gh` signed in, or `GITHUB_TOKEN` | GitHub |
| `OPENALEX_MAILTO` (shell only) | Identifies you to OpenAlex |

The EPO adapter is written against the provider's documented response shape. It has not yet been confirmed with a live key.

## What it cannot tell you

Patent search covers the granted and published patents EPO indexes. A source's coverage line reads `ok` (with a `partial:` note when it returned only some results), `empty`, `failed` or `skipped`. A paper or product the sources do not index, or a page that renders its text with JavaScript, is invisible to it. A `later` verdict marked "insufficient evidence" means the search came back thin, not that the idea is new.

## Evaluating heuresis

From a clone of the techne repository, `make heuresis-gold GUARD=<your ideas repository>` triages every case in `plugins/heuresis/gold/cases.yaml` three times in headless Claude Code sessions and writes `grades.jsonl`, `summary.json` and `summary.md` to a time-stamped folder under `~/.local/state/heuresis-gold` (`$XDG_STATE_HOME/heuresis-gold` when that is set). It uses your Claude plan, and it loads the heuresis plugin from that clone, so the run measures the code you have checked out. Pass `GOLD_ARGS="--runs 1 --case 'claude-*'"` to narrow the set (a `--case` that matches no case exits with an error), or `GOLD_ARGS="--out <folder>"` to put the results elsewhere. The runner refuses an `--out` inside any git work tree, because a session started inside a project loads that project's `CLAUDE.md` and settings. Each run's folder name ends in a random suffix, so two runs started in one second keep separate results.

Each run gets its own scratch ideas repository, kept under `<results>/work/`, in a folder outside any project. A scratch repository has no remote, so a run publishes nothing. The sessions run with `--permission-mode bypassPermissions` in that scratch folder, with auto-memory off and without your MCP servers. The `GUARD` repository is a tripwire, not a lock: after each run the runner compares it with a snapshot taken before the set (refs, every file's content, the local git config, `.git/hooks` and `.git/info`) and stops if anything changed, so it detects a write after the fact and does not prevent one. Taking the snapshot writes nothing into the guarded repository. Interrupting the runner kills the running session and its child processes. Each run's full session stream is in `logs/<case>-<run>.jsonl` with its error output in `logs/<case>-<run>.stderr`. `grades.jsonl` records the plugin path the session loaded and the code under test: the commit of the repository holding the plugin folder, whether anything under that folder was uncommitted, and the version in `plugin.json` when it declares one. The summary's "Code under test" line lists the distinct states and says when a summary mixes them.

Each case gives an idea, the state it should get, a kind and terms that name its known prior art. Only an applied verdict is graded. A run is finished when the idea's newest verdict was written by a triage (with its run files present) or by a decline, and the idea's state is that verdict's state. A state set by `override` or by hand is not finished, and the grade reads "triage did not finish". A finished run agrees when its state is one the case accepts. It finds the prior art when a term names the title or URL of a rival the judge cited and the verify step confirmed, matched as a whole word after whitespace is collapsed; a term shaped like an arXiv id also matches its versioned forms (`v2`). "Closest rival on the case's list" counts only runs whose closest rival a term names, so it reads low when the judge's closest rival is a real equivalent the case does not list. The summary's "Closest rival named, by run" section links what each run named and whether it verified. The summary also counts existing things filed as `do` (cases of kind `exists`), the failure the set is built to catch.

A declined run does no research, so its prior-art and closest-rival hits stay misses even when run files from an earlier triage are present. A case of kind `harmful` is accepted only when the run was declined and no `runs/<id>/pool.json` exists; a harmful idea that was researched and then declined is not accepted. A decline on any other kind of case is a wrong verdict. The summary counts declined runs.

Each grade records the case's expected state, kind and a digest of its match terms. If you edit a case after a run, `report` stops and names the case, because the grade no longer answers the same question; grade the run again with `regrade`. Grade lines written before the digest existed are refused the same way.

To add your own labelled ideas, keep a second cases file in your ideas repository and pass it with `GOLD_ARGS="--cases <file>"`. A cases file you pass replaces the built-in one; pass `--cases` once per file to combine them. A case id may appear in only one file, and `report` and `regrade` stop when a recorded cases file and a `--cases` file both define one.

To grade finished results again from their files, or to combine runs, use `uv run --no-project --quiet --with pyyaml python scripts/heuresis_gold.py regrade <results> [<results>...] --into <folder>`. The `--into` folder must be new or empty. Regrading reads the files in each run's work folder but never revives a run: an error the original run recorded stays, and a work folder with no grade line (a run the guard stopped, or one that crashed) becomes an error, "no grade recorded". The plugin path and the code identity carry over from the original grade line. Regrade replaces repeats; it does not pool them. When one case and run is in several folders, a later folder replaces an earlier one only if its run did not fail, and the runner prints a warning naming the case and run when it replaces a grade that had not failed.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/heuresis/skills/idea/SKILL.md) holds the full instructions Claude follows for this skill.
