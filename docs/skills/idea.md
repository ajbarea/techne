# `heuresis:idea`

Capture an idea and triage it against prior work. The skill saves the idea to your private ideas repository, searches papers, patents, products and your own research for anything like it, names the closest existing work, and files the idea as trash, later, do or merged, with the evidence.

εὕρεσις is discovery. The skill's first question is whether someone already found it.

## When to use

- "I have an idea." "Save this idea."
- "Has anyone built this?" "Is this worth building?" "Triage my idea."
- Not for judging a written paper's novelty (`graphe:paper-review`).

Run `/heuresis:setup` once first. It creates the ideas repository and checks the tools. If the repository or repos folder is not set, `/heuresis:idea` stops and says so.

## Usage

```
/heuresis:idea [--now] <idea text>
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

## How a triage runs

1. **Restate.** The idea is rewritten as one neutral paragraph with three to five short search queries. Praise and claims of novelty are dropped, so the scouts search for what the idea does.
2. **Scout.** Four scouts run in parallel and each saves records with the passage that shows what the source says.
    - `scout-papers`: OpenAlex, Semantic Scholar and arXiv.
    - `scout-patents`: Lens and EPO.
    - `scout-products`: GitHub, Hacker News and web search, including pricing pages.
    - `scout-context`: your bibliography, related-work notes, decks, ROADMAPs, marketplace and earlier ideas.
3. **Pool.** A script merges the scout files into numbered records with a coverage line per source.
4. **Judge.** The judge reads the restatement, the pooled records and the context scout's facts, and has no web access. It picks the closest rival, argues first that the idea is not new, then compares the two on domain, purpose, mechanism and evaluation, and proposes a verdict. It copies a verbatim quote for each record it relies on.
5. **Verify.** A script checks that every quote appears in its record, and fetches the source again where it can. A record whose quote fails is dropped. If the closest rival's quote fails, the judge runs again once without it.
6. **Apply.** A script enforces the rules, writes the verdict into the idea file, regenerates `BOARD.md` and `LOG.md`, and commits and pushes the ideas repository.

The skill reports four lines: the state, type and project; the closest rival with its link; the reason; the next step.

## The rules

They run in code, so no prompt can skip them.

- **`do`** needs a verified closest rival with all four comparisons filled in, and at least one paper source that returned results. Otherwise the verdict becomes `later`, with the reason "insufficient evidence" and a revisit date 90 days out.
- **`merged`** needs `duplicate_of` to name an idea that exists in the repository.
- **`later`** always carries a revisit date, and `BOARD.md` lists it as due once the date passes.
- A quote that is not in its record, or a record that does not verify, never supports a verdict.

States are `inbox`, `trash`, `later`, `do`, `building`, `shipped` and `merged`. Types are `product`, `tool`, `research` and `improve`. For a product idea the judge also records paying rivals with their pricing, demand links, the riskiest assumption and the cheapest test.

## Files written

All inside your ideas repository.

| Path | Holds |
|---|---|
| `ideas/<id>.md` | The idea, its state and every verdict with its evidence. |
| `runs/<id>/` | The latest run's working files: restatement, scout records, pool, judge output, verification. A retriage replaces them. |
| `BOARD.md` | Needs triage (inbox and invalid files), Due for revisit, Do (by project, then type), Later, and Closed (counts with links). Regenerated. |
| `LOG.md` | One line per verdict, triage or override, newest first. Regenerated. |

## Keys

Keys come from environment variables. Set them in the shell profile Claude Code starts from and restart Claude Code. Never put a key in a plugin option.

OpenAlex, arXiv and Hacker News run without a key. `OPENALEX_API_KEY` raises OpenAlex's daily search budget, and `OPENALEX_MAILTO` identifies you to OpenAlex. Semantic Scholar, Lens, EPO and GitHub show `skipped` in the verdict's coverage line without their keys, and the rest still run.

| Variable | Source |
|---|---|
| `S2_API_KEY` | Semantic Scholar |
| `LENS_API_TOKEN` | Lens patents |
| `EPO_OPS_KEY`, `EPO_OPS_SECRET` | EPO patents |
| `gh` signed in, or `GITHUB_TOKEN` | GitHub |
| `OPENALEX_API_KEY`, `OPENALEX_MAILTO` | Optional for OpenAlex |

The Lens and EPO adapters are written against the providers' documented response shapes. They have not yet been confirmed with live keys.

## What it cannot tell you

Patent search covers the granted and published patents these two sources index. A paper or product the sources do not index, or a page that renders its text with JavaScript, is invisible to it. A `later` verdict marked "insufficient evidence" means the search came back thin, not that the idea is new.
