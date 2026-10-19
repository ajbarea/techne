<div align="center">

<img src="docs/assets/hero.png" width="420" alt="techne Hero Image">

# techne

*A plugin marketplace for AI coding agents: skills for code repos and for documents, opt-in git guards, and a spoken Claude Code.*

[![Validate](https://github.com/ajbarea/techne/actions/workflows/validate.yml/badge.svg)](https://github.com/ajbarea/techne/actions/workflows/validate.yml)
[![Docs](https://github.com/ajbarea/techne/actions/workflows/docs.yml/badge.svg)](https://github.com/ajbarea/techne/actions/workflows/docs.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![uv](https://img.shields.io/badge/uv-package_manager-DE5FE9?style=flat-square)](https://docs.astral.sh/uv/)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-D97757?style=flat-square)](https://code.claude.com/docs)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23330765.svg)](https://doi.org/10.5281/zenodo.23330765)

</div>

---

## Plugins

| Plugin | For | Runs in |
| --- | --- | --- |
| `techne` | Work in a code repo: audits, CI review, pre-merge review, commit plans, GitHub catch-up, cross-repo drift, slop and doc drift | Claude Code, Codex, Copilot CLI, Antigravity CLI |
| `graphe` | Documents: LaTeX papers, markdown-to-PDF, talk decks, paper scaffolds and novelty review | Claude Code, Codex, Copilot CLI, Antigravity CLI |
| `dokimasia` | Bibliography verification for LaTeX projects: lint a `.bib` or hand-written reference list, verify it against arXiv and Crossref, check every cited key rendered | Claude Code, Codex, Copilot CLI, Antigravity CLI, or one standalone Python file |
| `heuresis` | Idea triage: capture an idea, search papers, patents, products and your own work for anything like it, and file it with a verdict grounded in checked records | Claude Code (needs `uv` and git; `gh` for GitHub search and the private remote) |
| `phylax` | Opt-in git and PR guards (a mod), restart onto an updated Claude Code | Claude Code |
| `epistole` | Gmail across accounts: search, read and draft in each configured account, and send a draft only after you approve it ([docs](https://ajbarea.github.io/techne/plugins/epistole/)) | Claude Code (MCP server, needs `uv`) |
| `schole` | Brightspace (D2L) course sites, read-only: new announcements and content, what is due, what came due unsubmitted ([docs](https://ajbarea.github.io/techne/plugins/schole/)) | Claude Code (needs `uv` and Chromium) |
| [`keryx`](https://github.com/ajbarea/keryx) | Speaks a short gist of each reply in a local voice (WSL2) | Claude Code |

Install only the ones you use: every enabled plugin's skill list sits in the agent's context on every turn. claude.ai and Cowork can install graphe too, but its build and check steps run shell commands (`uv`, TeX Live, Typst) that need an agent CLI on your machine.

### techne

| Skill | What it does |
| --- | --- |
| `techne:audit` | Runs the repo's `make` targets in dependency order and reconciles terminal output against `logs/dev-*.log` archives. |
| `techne:auto-commit` | Groups working-tree changes into a structured `COMMITS.md` plan for staged review before anything lands. |
| `techne:catchup` | Reads every comment, review, and state change on a repo's issues and PRs since you last participated, then reports who is blocked on whom. |
| `techne:ci-audit` | Audits GitHub Actions runs on the current branch/PR: surfaces warnings, failures, and noise; fixes what's fixable in-repo. |
| `techne:deslop` | Scans comments and docstrings for AI-generated slop and proposes tightened rewrites. |
| `techne:docs-site` | Maintains the Zensical-powered docs site: config, deploy pipeline, theming, link integrity. |
| `techne:docsync` | Verifies documentation claims (CLI commands, paths, config keys, signatures) against the actual code. |
| `techne:elenchus` | Adversarial pre-merge review: drives `/code-review`, then reproduces the load-bearing claim, traces every consumer across the whole repo, and walks a bug-class rubric for reachable destructive ops, unmirrored parallel-path guards, migration crashes, and dead-but-green features. |
| `techne:research-grounded` | Flags decisions (technology, data release, study design, access rules, claim wording) in IMPL, ROADMAP and decision records that lack `# research(YYYY-MM):` provenance, then web-searches to ground them. |
| `techne:reslop` | Rewrites docstrings grounded in the implementation rather than deleting them outright. |
| `techne:sisters` | Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. |
| `techne:theoros` | Starts an observed live dev session: Claude drives the REPL in a named `tmux` session; you spectate read-only via `tmux attach -r`. |
| `techne:setup` | Checks what the techne skills need on this machine and prints the install command for each gap. |

### graphe

| Skill | What it does |
| --- | --- |
| `graphe:latex` | Builds a LaTeX document and gates it on its log, its PDF, and the assignment it answers; a clean `latexmk` exit is not the signal. |
| `graphe:paper` | Scaffolds a new paper dir (LaTeX + results-harvest + shared bib + portfolio row) in a papers-style monorepo so it builds on day one. |
| `graphe:paper-review` | Pre-submission novelty + reviewer pass for a draft paper: grounds every novelty/claim verdict in retrieved prior work, flags related-work gaps, and surfaces lab-overlap for disclosure. |
| `graphe:pdf` | Renders markdown to print-quality PDFs through a Typst template, then verifies fonts and content against the source. |
| `graphe:slides` | Builds and gates a talk deck: an animated web deck on GitHub Pages from a starter, checked for titles, contrast, alt text, missing files and phone fit, then rendered and published. |
| `graphe:setup` | Checks the document tools (TeX Live, poppler, Chromium, uv) and prints the install command for each gap. |

### dokimasia

| Skill | What it does |
| --- | --- |
| `dokimasia:check` | Lints any `.bib` or hand-written `thebibliography` offline, resolves its arXiv ids and DOIs against arXiv and Crossref and tells a failed lookup from a wrong entry, and checks that every cited key rendered in the built document. Configured per project, standard library only. |

### heuresis

| Skill | What it does |
| --- | --- |
| `heuresis:idea` | Captures an idea in your private ideas repository, searches papers, patents, products and your own work, names the closest existing work, and files the idea as trash, later, do or merged with checked evidence. |
| `heuresis:setup` | Checks uv, git and gh, creates the ideas repository, and lists the search API keys that are set. |

### epistole

A local Gmail MCP server and skills: `epistole:catch-me-up` sweeps every account for mail since the last sweep (and runs schole's course sweep when schole is installed), and `epistole:setup` walks through creating a Google OAuth client and signing each account in. The MCP tools search, read and draft mail in every configured account, new drafts carry the account's Gmail signature, and `send_draft` always asks you first. See the [epistole page](https://ajbarea.github.io/techne/plugins/epistole/), the [epistole README](plugins/epistole/README.md) and its [privacy policy](https://ajbarea.github.io/techne/epistole/#privacy).

### schole

Skills: `schole:courses` reports a Brightspace (D2L) course site's new announcements and content, what is due, and what came due unsubmitted; `schole:setup` signs you in once in a browser window. It reads the site's API with GET requests on a fixed allowlist and never opens a content page, so nothing gets marked read. See [schole](https://ajbarea.github.io/techne/plugins/schole/).

### phylax

Three opt-in guards on `git commit`, `git add` and `gh pr`, run by a [mod](https://code.claude.com/docs/en/plugins/mods/overview) (Claude Code 2.1.288 or later; 2.1.287 runs it but breaks Bash in worktree subagents): block attribution lines, from the text Claude Code composes through to the command Claude runs; block staging `COMMITS.md`; and warn on commits in the main checkout. While a blocking guard is on, a check that fails refuses the command instead of letting it through. A fourth option, `restart_on_update`, moves an idle session onto an updated Claude Code in a new tmux window or Windows Terminal tab and keeps the conversation. Each is off until you switch it on in `/config`; `/phylax:setup` shows which are on and checks what they need. See [phylax](https://ajbarea.github.io/techne/plugins/phylax/).

## Install

### Claude Code

From inside Claude Code:

```bash
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
/plugin install graphe@techne
/plugin install dokimasia@techne
/plugin install heuresis@techne
/plugin install phylax@techne
/plugin install epistole@techne  # needs uv
/plugin install schole@techne    # needs uv and Chromium
/plugin install keryx@techne    # WSL2 on Windows only
```

Invoke a skill as `/techne:<name>`, `/graphe:<name>`, `/dokimasia:check`, `/heuresis:idea` or `/<plugin>:setup`, or describe the task and Claude picks the matching skill. Run `/skills` to confirm they loaded. On claude.ai, add `ajbarea/techne` under **Customize > Plugins > Add > Add marketplace**, then add `graphe`.

After installing, run each plugin's setup skill: `/techne:setup`, `/graphe:setup`, `/heuresis:setup`, `/phylax:setup`, `/epistole:setup`, `/schole:setup`. Each checks what the plugin needs and prints the install command for anything missing. The techne skills follow a few conventions (Makefile pattern, dev-runner archive, `.claude/skill-context.md`); [Conventions](docs/conventions.md) lists the minimum each skill needs.

### Codex, Copilot CLI and Antigravity CLI

techne, graphe and dokimasia run in these agent CLIs too. Codex and Copilot CLI read this repo's marketplace; Antigravity CLI installs one plugin from its folder URL:

```bash
codex plugin marketplace add ajbarea/techne
codex plugin add techne@techne

copilot plugin marketplace add ajbarea/techne
copilot plugin install techne@techne

agy plugin install https://github.com/ajbarea/techne/tree/main/plugins/techne
```

Swap `techne` for `graphe` or `dokimasia` to add those. Ask for a skill by name ("use the techne audit skill") or describe the task. graphe's optional OpenAlex and Semantic Scholar keys come from Claude Code's plugin settings; in other CLIs, export `OPENALEX_API_KEY` and `S2_API_KEY` in your shell instead. techne's opt-in cleanup at session start is a Claude Code hook, and several techne skills (elenchus, docs-site, deslop, reslop, docsync, research-grounded) hand part of their work to Claude Code subagents or `/code-review`; in other CLIs that step depends on what the agent offers. The other plugins rely on Claude Code's hooks, plugin settings or subagents and run there alone for now.

## Configuration

`techne:sisters` reads `~/.claude/techne.toml` at runtime (user-controlled config that lists the active sister repos to compare against).

```toml
github_user   = "your-github-username"
workspace_root = "/path/to/your/workspace"

[[sisters]]
name   = "repo-one"
status = "active"

[[sisters]]
name   = "repo-two"
status = "active"

[[sisters]]
name   = "repo-three"
status = "active"
```

Set `status = "backburner"` to skip a repo without removing it.


## How it fits together

```
~/.claude/techne.toml      ← user-controlled sister-repo registry
        │
        ▼
techne (marketplace: ajbarea/techne)
├── techne (plugin, plugins/techne)
│   ├── audit             ── verifies build targets vs. logs/
│   ├── auto-commit       ── groups diffs into COMMITS.md
│   ├── catchup           ── who is blocked on whom since you last looked
│   ├── ci-audit          ── reads gh runs, fixes warnings in-repo
│   ├── deslop            ── flags AI-slop prose
│   ├── docs-site         ── manages Zensical site + deploy
│   ├── docsync           ── doc claims ↔ implementation
│   ├── elenchus          ── adversarial pre-merge review (reproduce + trace + rubric)
│   ├── research-grounded ── flags un-grounded design decisions
│   ├── reslop            ── rewrites docstrings from code
│   ├── sisters           ── cross-repo drift across sisters
│   ├── theoros           ── observed tmux REPL session
│   └── setup             ── checks prerequisites, prints each fix
├── graphe (plugin, plugins/graphe)
│   ├── latex             ── builds LaTeX and gates the PDF on its log
│   ├── paper             ── scaffolds a new paper dir (LaTeX + harvest)
│   ├── paper-review      ── grounded novelty + reviewer pass for a draft
│   ├── pdf               ── markdown to print PDF via Typst, verified
│   ├── slides            ── talk deck gated and rendered, presenter briefed
│   └── setup             ── checks prerequisites, prints each fix
├── dokimasia (plugin, plugins/dokimasia)
│   └── check             ── lints, verifies and render-checks a .bib
├── heuresis (plugin, plugins/heuresis)
│   ├── idea              ── captures an idea, triages it against prior work
│   └── setup             ── checks prerequisites, creates the ideas repo
├── epistole (plugin, plugins/epistole)
│   ├── catch-me-up       ── sweeps every inbox since the last sweep
│   └── setup             ── guides Google OAuth client and account sign-in (plus the Gmail MCP server)
├── schole (plugin, plugins/schole)
│   ├── courses           ── new, due and past-due on a Brightspace course site
│   └── setup             ── one browser sign-in to the course site
├── phylax (plugin, plugins/phylax)
│   └── setup             ── shows the options, checks what they need
└── keryx (plugin, ajbarea/keryx)    ── spoken gist of each reply
```

Each skill is self-contained. Invoke one without pulling in the others. They share a convention of writing intermediate artifacts (plans, audit reports) to disk for human review before mutating the repo.

## Why "techne"

Greek τέχνη: craft, the practical knowledge of how to make a thing well. The plugins keep the Greek: γραφή (graphe) is writing, φύλαξ (phylax) a guard, κῆρυξ (keryx) a herald, ἐπιστολή (epistole) a letter, σχολή (schole) school, δοκιμασία (dokimasia) the scrutiny of a candidate's credentials before office, εὕρεσις (heuresis) discovery.

## Cite

If you use techne in your research, cite it with the metadata in [CITATION.cff](CITATION.cff). GitHub's **Cite this repository** button, in the repository sidebar, turns it into APA and BibTeX. The DOI resolves to the latest release on Zenodo. The citation covers every plugin listed here, keryx included.

```bibtex
@software{barea_techne,
  author  = {Barea, AJ},
  title   = {techne: a Claude Code plugin marketplace for repositories, documents, and bibliographies},
  url     = {https://github.com/ajbarea/techne},
  doi     = {10.5281/zenodo.23330765},
  license = {MIT},
  version = {1.4.0},
  year    = {2026}
}
```

## License

MIT.

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand-white.png">
  <img src="docs/assets/brand.png" alt="" height="16" />
</picture>&nbsp;&nbsp;2026 <a href="https://ajbarea.github.io/">AJ Barea</a>

</div>
