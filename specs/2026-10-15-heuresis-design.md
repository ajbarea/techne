# heuresis: design

*Status: approved design, 2026-10-15. Implementation plan not yet written.*

heuresis (Greek εὕρεσις, "discovery, invention") is a techne plugin that takes an idea written in
plain text, searches for prior work, and files the idea with a verdict grounded in what it found.
It knows AJ's research, bibliography, repos and plugins, and it keeps every idea, so each new one
is judged against everything already captured.

## Goal and success criteria

AJ has ideas for apps, tools, research and improvements to existing work, and no single place to
put them. heuresis gives him one inbox and an honest first opinion on each idea.

It succeeds when:

1. Capture takes one tap on the phone or one command in the terminal, and never waits on triage.
2. Every verdict names the closest existing work it found, with a working link and a quoted passage
   that supports each "differs because" claim.
3. Triage says "not novel" when the prior art is there. The headline metric is recall of known
   prior art on a gold set (see Evaluation).
4. Every idea is tied to AJ's own work: the project it belongs to, the bib entries and related-work
   notes it touches, and earlier ideas like it.
5. A deferred idea comes back when something related lands, without AJ having to remember it.
6. The ideas already scattered across markdown and text files, screenshots, Google Docs and Apple
   Notes end up in the same store, so heuresis replaces those places instead of adding one.
7. Capture costs no tokens. Terminal and imported ideas are triaged by a queue that works within
   AJ's usage limits and resumes after each five-hour reset, so a busy week never loses an idea.

Out of scope: multiple users, a hosted web app, numeric scores (ICE, RICE, novelty out of 5), and
running arbitrary Claude jobs from the queue (heuresis jobs only).

## Decisions and the research behind them

| Decision | Chosen | Passed over | Source |
|---|---|---|---|
| Form | techne plugin + private git repo of markdown | MCP server + vector DB; hosted web app | Plain markdown in git is readable, editable and diffable; add an index only when retrieval fails at scale (Karpathy "LLM wiki" pattern, [write-up](https://www.mindstudio.ai/blog/karpathy-llm-wiki-pattern-knowledge-base-without-rag)). A hosted app cannot read local repos. |
| Phone triage | `anthropics/claude-code-action` on `issues: opened` | Claude Code routines | Routines and cloud sessions do not load plugins, and their GitHub triggers cover pull requests and releases only ([routines](https://code.claude.com/docs/en/routines), [settings in cloud sessions](https://code.claude.com/docs/en/settings)). The Action takes `plugin_marketplaces` and `plugins` ([github-actions](https://code.claude.com/docs/en/github-actions)). |
| Phone capture | iOS Shortcut posting to the GitHub Issues API | GitHub issue form alone; email or chat bots | One or two taps, works with dictation and the share sheet. The issue form stays as a fallback. |
| Verdict grounding | Compare only against retrieved records, facet by facet, closest rival named | Ask the model whether the idea is novel | Ungrounded LLM novelty judgments are near chance and almost never say "not novel" ([RINoBench](https://arxiv.org/html/2603.10303)). Removing retrieval and facet reranking dropped "not novel" accuracy from 89.7% to 5-14% ([2506.22026](https://arxiv.org/html/2506.22026v1)). |
| Link checking | A script resolves every link and checks every quote | A second LLM pass | Up to 39% hallucinated evidence in LLM novelty assessment ([NovGauge](https://arxiv.org/html/2609.11234v1)). Anthropic's research system uses a separate citation step ([multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)). |
| Patents | Lens.org, EPO Open Patent Services, Google Patents BigQuery as fallback | PatentsView | PatentsView search and APIs paused 2026-03-20 during the move to the USPTO Open Data Portal ([USPTO notice](https://www.uspto.gov/subscription-center/2026/patentsview-migrating-uspto-open-data-portal-march-20)). |
| Papers | OpenAlex (free key), Semantic Scholar (with key), arXiv | Keyless Semantic Scholar | OpenAlex: 30 req/s with a free key, semantic search 1 req/s ([OpenAlex limits](https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication)). Keyless S2 returns 429. |
| Products | GitHub search, Hacker News (Algolia), web search | Product Hunt API | Product Hunt's API "must not be used for commercial purposes" without permission ([PH API docs](https://api.producthunt.com/v2/docs)), and Product is a verdict type. |
| Classification | `state` (lifecycle) + `type` (kind), two fields | One six-bin field | The six bins mixed verbs (trash, later, build) with kinds (product, research); one idea can be both a product and something to build. Linear's triage (accept, duplicate, decline, snooze) and GTD Someday/Maybe both treat the decision separately from the item ([Linear triage](https://linear.app/docs/triage)). |
| Triage timing | Phone: immediately, in the Action. Terminal and imports: a local queue paced by AJ's usage windows | Triage every capture at once | AJ's tokens are the scarce resource. Claude Code continues after a usage reset only in interactive sessions, never in `claude -p` ([summary](https://aicatchup.com/news/claude-code-desktop-auto-continue)), so unattended work needs its own pacing. |
| Usage signal | klepsydra's per-session files (five-hour and weekly `used_percentage`, `resets_at`, reconciled per account) | Polling with a probe request every 5 minutes ([claude-code-auto-resume](https://github.com/PHSM22/claude-code-auto-resume)) | klepsydra already publishes the figures from the status line at no cost; a probe is the fallback when they are stale. |
| Apple Notes backfill | A JXA script run on AJ's MacBook (`osascript`), exporting every note's folder, dates and body; reruns export only notes modified since the last run | privacy.apple.com data copy; iCloud for Windows; per-note export on iPhone | Notes is scriptable on macOS and existing exporters use that route ([apple-notes-exporter](https://cdn.jsdelivr.net/npm/apple-notes-exporter@1.0.3/README.md)); it keeps folders and dates and can rerun. iCloud for Windows exposes Notes only on icloud.com, which has no export, and iPhone exports one note at a time ([Apple](https://support.apple.com/guide/iphone/export-or-print-notes-iphdf551cfa2/ios)). The privacy.apple.com copy stays as a fallback. |
| Google Docs backfill | Drive API export as Markdown, through epistole's existing Google OAuth client with a read-only Drive scope | A second OAuth client; Google Takeout | One sign-in per Google account, already set up for both of AJ's inboxes. |
| Bulk digestion | Haiku splits imported sources into ideas; full triage only through the queue | Full triage on every imported fragment | Thousands of fragments at full triage cost would consume weeks of quota. |
| Product evidence | A checklist of named rivals, pricing pages, demand links, riskiest assumption | ICE/RICE scores | Scores hide guesswork in a number that looks objective; the riskiest assumption comes from opportunity solution trees. |

## Architecture

```
 phone (iOS Shortcut / issue form)          terminal
            |                                   |
   GitHub issue, label "idea"          /heuresis:idea <text>
            |                                   |
   claude-code-action (issues: opened)          |
            \_______________ triage ___________/
                               |
        +-----------+----------+-----------+-------------+
        |           |          |           |             |
   scout-web   scout-papers scout-patents scout-context   (Sonnet, parallel)
        \___________|__________|___________/
                    |
                  judge (Opus)  ->  verify.py (links + quotes)
                    |
         ideas/<id>.md written, BOARD.md + LOG.md regenerated, pushed
         (phone path: verdict commented on the issue, issue closed)
```

### Repositories

- **Plugin:** `techne/plugins/heuresis/`, listed in `techne/.claude-plugin/marketplace.json`.
- **Store:** a new private repo `ajbarea/ideas`. Its `main` is a data store written by the plugin
  and the Action, so it is not branch-protected.

### Plugin layout

```
plugins/heuresis/
  .claude-plugin/plugin.json
  README.md  AGENTS.md
  skills/
    idea/SKILL.md          capture + triage one idea; --retriage <id>; --override <id> <state> <reason>
    review/SKILL.md        weekly pass: resurfacing, duplicates, lint
    import/SKILL.md        backfill from folders, screenshots, Google Docs, Apple Notes export
    queue/SKILL.md         show, reorder, pin, pause the job queue; run it now
    setup/SKILL.md         check keys, tokens, ideas clone, Action secrets (per-plugin setup convention)
  agents/
    scout-web.md           products, GitHub, HN, general web
    scout-papers.md        OpenAlex, Semantic Scholar, arXiv
    scout-patents.md       Lens, EPO OPS, BigQuery fallback
    scout-context.md       AJ's own sources + earlier ideas
    digest.md              Haiku: split an imported source into candidate ideas, dedupe, propose project
    judge.md               verdict (Opus)
  heuresis/                Python package (uv): sources/, importers/, store.py, board.py,
                           verify.py, queue.py, budget.py, cli.py
  systemd/                 heuresis-queue.service + .timer (WSL user units)
  pyproject.toml  uv.lock
  evals/                   plugin eval suites (fires-idea, never-triage-without-retrieval, ...)
  tests/
```

heuresis is the first techne plugin with an `agents/` directory. Plugin agents can pin `model`,
`tools`, `effort` and `maxTurns`, and they ignore `hooks`, `mcpServers` and `permissionMode`
([sub-agents](https://code.claude.com/docs/en/sub-agents)). Scouts pin `model: sonnet` with a tool
allowlist (`WebSearch, WebFetch, Read, Grep, Bash` for the source CLI) and a `maxTurns` cap; the
judge pins `model: opus` and gets no web tools, so it can only use what the scouts retrieved.

No bundled MCP server and no hooks: the repo writes and board generation are plain CLI calls.

## Shared retrieval with graphe:paper-review

`graphe:paper-review` already runs the OpenNovelty pipeline over OpenAlex with a citation-verify
step (`graphe/skills/paper-review/references/retrieval.md`, `citation-verify.md`). heuresis needs
the same paper retrieval and the same verification. That logic moves into one place, used by both
skills. The implementation plan decides the mechanism (a plugin dependency, or one canonical copy
plus a parity check like the shared docs-site files) after confirming what the current plugin
system supports.

## Data model

One file per idea: `ideas/YYYY-MM-DD-<slug>.md`.

```yaml
id: 2026-10-15-idea-triage-tool
title: Idea triage tool with prior-art search
captured: 2026-10-15T14:02:00-04:00
captured_via: terminal | phone | form | import
state: inbox | trash | later | do | building | shipped | merged
type: product | tool | research | improve
project: techne            # from projects.toml, or "new:<name>" pending AJ's confirmation
duplicate_of: null         # set when state is merged
revisit: 2027-01-15        # later only
revisit_on: [keyword:federated agents, project:sphragis]
related: [idea:2026-09-30-..., bib:li2025fedagents, repo:ariadne]
```

Body sections, in order:

1. **Idea**: AJ's text, verbatim. Never edited.
2. **Restated**: a neutral one-paragraph restatement, the only text the judge sees of the idea.
3. **Closest work**: the single closest rival, then up to ten more, each with link, quoted passage,
   and how it differs on domain, purpose, mechanism and evaluation.
4. **Fit with your work**: project, bib keys, related-work notes, repos, earlier ideas. Facts only.
5. **Product evidence** (type product only): named paying rivals with pricing links, demand links,
   riskiest assumption, the cheapest test (waitlist, pre-sale). Unknowns left blank.
6. **Verdict log**: dated entries, newest first. Each has state, type, project, reason, next step,
   retrieval coverage per source, and whether it came from triage or an AJ override.

Mapping from the six bins AJ named: Trash = `trash`; Later = `later`; Improve, Build, Product,
Research = `do` with the matching `type` (`improve`, `tool`, `product`, `research`).

Repo-level files:

- `projects.toml`: one entry per project. Seeded from the linked repos in `~/.claude/techne.toml`,
  the techne plugins, and the paper dirs in `papers/`. Triage may propose `new:<name>`; AJ confirms
  with `/heuresis:idea --override`.
- `context.toml`: where AJ's own sources live, as repo + path pairs so both the local machine and
  the Action can resolve them (`papers:references.bib`, `papers:related-work/intake.md`,
  `talks:<talk>/`, each repo's `ROADMAP.md` and `README.md`, the techne `marketplace.json`).
  Never copies.
- `BOARD.md` and `LOG.md`: generated from the idea files on every write, never edited by hand.
  Because they are generated, a push race on them is resolved by rebasing and regenerating.

`BOARD.md` order: **Needs triage** (inbox, failed runs), **Due for revisit**, **Do** grouped by
project then type, **Later**, then counts of trash and merged with links. One line per idea:
id, one-sentence gist, type, project.

## Triage pipeline

1. **Capture.** Terminal: write the idea file with `state: inbox`, commit, and enqueue a triage job;
   `/heuresis:idea --now <text>` triages in the session instead. Phone: the issue is the capture;
   the Action writes the file first, then triages at once.
2. **Restate.** Strip enthusiasm and framing; produce the neutral restatement and 3-5 query
   rewrites (broad and short first, then narrow, following Anthropic's research-system guidance).
3. **Scout, in parallel.** Each scout runs every query rewrite against its sources and returns
   records as structured JSON: title, URL, source, date, quoted passage, plus a coverage line
   (queries run, hits, sources that failed or were skipped). scout-context also greps earlier
   idea files and BOARD.md for duplicates.
4. **Pool and rank.** Merge records, drop duplicates, rerank by facet similarity, keep the top ten.
5. **Judge.** The judge gets the restatement, the ranked records and scout-context's facts. It names
   the closest rival, argues the idea is not new, then decides. Rules:
   - `do` requires at least one retrieved record per facet compared and a verified closest rival.
     With thin retrieval, the verdict is `later` with "insufficient evidence" and a revisit date.
   - A near-identical earlier idea gives `merged` with `duplicate_of`; the new wording is appended
     to the original's Idea section.
   - Patent coverage is reported as partial in every verdict.
6. **Verify.** `verify.py` fetches every link, checks the status, and checks each quoted passage
   appears in the fetched text after whitespace and case normalization. Records that fail are
   dropped and listed under the verdict as "dropped: unverifiable". If dropping changes the closest
   rival, the judge reruns once on the verified set.
7. **Write.** Update the idea file, regenerate BOARD.md and LOG.md, commit, pull with rebase,
   regenerate if needed, push. Phone path: comment the verdict summary on the issue and close it;
   GitHub's push notification tells AJ it is done.

`--retriage <id>` reruns steps 2-7 and adds a new verdict entry, keeping the old ones.
`--override <id> <state> [type] <reason>` records AJ's decision as a verdict entry marked
`override`; overrides are the labels for evaluation.

## Import

`/heuresis:import <source>` runs in three layers so bulk work stays cheap.

1. **Collect (no model calls).** Each importer writes one file per source document to
   `sources/<importer>/` with its origin path, date and a content hash, and skips hashes already
   seen, so reruns are safe.
   - `folder <path>`: `.md` and `.txt` files, recursively.
   - `screenshots <path>`: local OCR (PaddleOCR, which detects text regions before reading them and
     handles mixed screenshot layouts, [guide](https://bestllmfor.com/guides/paddleocr-guide/)).
     Images where OCR finds little text are listed for AJ, not sent to a model.
   - `gdocs [--folder <id>]`: Google Docs exported as Markdown through the Drive API, using
     epistole's OAuth client with `drive.readonly` added.
   - `apple-notes <dir>`: the folder written by `scripts/export-apple-notes.js`, which AJ runs on
     the MacBook (`osascript -l JavaScript`, Automation permission for Notes) into a synced or
     copied folder. Note bodies arrive as HTML and are converted to Markdown.
2. **Digest (Haiku).** The `digest` agent splits each source into candidate ideas, drops ones
   that duplicate an existing idea, proposes a project and type, and writes them as `inbox` ideas
   with `captured_via: import` and a link back to the source file. Each source becomes one queued
   digest job.
3. **Triage (queue).** Imported ideas enter the queue at the lowest priority unless AJ pins them.

## Queue

`queue.py` keeps one job per line in `queue.jsonl` in the ideas repo: job id, kind (`triage`,
`digest`, `retriage`, `review`), target, priority, attempts, state (`queued`, `running`,
`deferred`, `done`, `failed`). Jobs are heuresis jobs only: they read, search and write idea
files, so they are safe to run unattended.

**Order:** pinned jobs, then phone ideas whose Action run failed, then ideas in projects with
recent commits, then revisit-due ideas, then oldest first.

**Runner.** A systemd user timer in WSL starts `heuresis queue run` every 10 minutes. Each run:

1. Reads the newest five-hour and weekly figures for AJ's account from klepsydra's files
   (`accounts/<account>/<session>.json`, later `resets_at` wins, highest reading within a window
   wins). If the newest file is older than 15 minutes, it sends one minimal `claude -p` request to
   confirm the window is usable, as claude-code-auto-resume does.
2. Decides how much it may spend:
   - five-hour usage under the reserve (default **50%**, AJ's choice): run jobs;
   - within 30 minutes of `resets_at` (default): the cap rises to 90%, because quota unused at the
     reset is lost;
   - weekly usage over the weekly cap (default 80%, so the last fifth of the week stays with AJ):
     run nothing until the weekly reset.
3. Runs the top job with `claude -p` and the heuresis plugin, rereading the figures between jobs,
   and stops when the cap is reached.

**Checkpoints.** Every triage step writes its output into the idea file (restatement, each
scout's records, the verdict), so a job cut off by a limit restarts from the last finished step.
A job that hits a limit goes to `deferred` until `resets_at` and does not use up an attempt;
after 3 failures for other reasons it goes to `failed` and shows under **Needs triage**.

**Lock.** One runner at a time (a file lock), and the runner skips an idea whose file changed
since it was queued, so it never fights a `/heuresis:idea --now` in a live session.

`/heuresis:queue` shows the queue, the current budget reading, and lets AJ pin, reorder, pause or
run it now.

## Resurfacing and review

- On every triage, scout-context compares the new idea against `later` ideas by project and by
  `revisit_on` keywords. A match adds a line under the later idea's verdict log and lists it in
  BOARD.md's **Due for revisit**.
- `/heuresis:review` (run weekly, by AJ or a scheduled local session) lists ideas whose `revisit`
  date passed, proposes merges between likely duplicates, and lints: missing fields, stale
  `new:` projects, ideas in `inbox` for more than a week, broken links.

## Phone path

- **Shortcut:** "New idea" on the iPhone home screen and share sheet. It takes dictated or typed
  text (or shared text and URLs), then POSTs to `https://api.github.com/repos/ajbarea/ideas/issues`
  with label `idea`, using a fine-grained token limited to Issues: write on `ajbarea/ideas`. The
  spec ships the Shortcut's steps; AJ builds it once on the phone. Shortcuts is built into iOS and
  its Get Contents of URL action sends POST requests with a JSON body
  ([Apple guide](https://support.apple.com/guide/shortcuts/request-your-first-api-apd58d46713f/ios)),
  so the phone path needs no Apple Developer Program membership, App Store listing or TestFlight.
- **Action:** `.github/workflows/triage.yml` in `ajbarea/ideas`, on `issues: [opened]` filtered to
  the `idea` label, with a per-issue concurrency group and a job timeout. It checks out `ideas` and
  the repos named in `context.toml` (read-only token in secrets), loads the techne marketplace and
  the heuresis plugin, and runs `/heuresis:idea --from-issue <n>` with `--max-turns` set.
  Auth uses `CLAUDE_CODE_OAUTH_TOKEN` so runs draw on AJ's subscription.
- **Sweep:** the same workflow on a weekly `schedule` triages any open `idea` issue the event missed.
- **Fallback:** a GitHub issue form with one text field, for when the Shortcut is unavailable.

## Error handling

- A usage limit mid-job defers the job to the reset; it never counts as a failure.
- Stale or missing klepsydra files fall back to a probe; if the probe fails, the runner waits for
  the next timer tick.
- Capture never depends on triage. A failed triage leaves the idea in `inbox`, records the error in
  the verdict log, and shows it under **Needs triage**.
- A source that fails, rate-limits or has no key is skipped and named in the coverage line; the
  run continues. A run where every paper source failed cannot return `do`.
- Every source sits behind one interface (`search(query) -> list[Record]`, `name`, `available()`),
  so adding or removing a source touches one module.
- A push conflict is resolved by rebase plus regeneration of the generated files; idea files are
  per-idea, so two captures never edit the same file.
- The Action refuses issues not opened by AJ (the action rejects non-write actors by default).

## Testing and evaluation

- **Unit tests** (pytest): front-matter schema, BOARD.md and LOG.md generation, resurfacing match,
  merge, each source adapter against recorded fixtures, `verify.py` on pages with and without the
  quoted passage, rebase-and-regenerate, queue ordering, budget decisions on fixture klepsydra
  files (under reserve, near reset, over weekly cap, stale), resume from each checkpoint, importer
  hash dedupe.
- **Plugin evals** (`evals/`, the techne convention): `fires-idea`, `never-verdict-without-retrieval`,
  `never-do-on-thin-evidence`, `merges-duplicate`.
- **Gold set:** at least 20 ideas with known answers, including ideas that already exist as
  products or papers (the "not novel" cases models miss), ideas from AJ's own repos, and ideas AJ
  has dropped. Each runs 3 times; report prior-art recall and verdict agreement with AJ, run to run
  spread included. Grading: deterministic checks (links resolve, quotes present, schema valid) plus
  one rubric-based LLM judge calibrated against AJ's labels.
- **Ongoing:** every `--override` is a new label; the review skill reports agreement since the
  last review.

## Build order

Each phase gets its own implementation plan.

1. **Store and terminal triage:** `ajbarea/ideas` repo, schema, board and log generation, the
   scout and judge agents, source adapters, `verify.py`, `/heuresis:idea --now` end to end in the
   terminal, shared retrieval with paper-review, unit tests and evals.
2. **Evaluation:** gold set and the harness above, run before trusting verdicts.
3. **Queue:** `queue.jsonl`, checkpoints, budget reading from klepsydra, systemd timer,
   `/heuresis:queue`.
4. **Phone path:** Action workflow, secrets, iOS Shortcut, issue form, weekly sweep.
5. **Import:** importers, the digest agent, then the backfill itself.
6. **Review:** `/heuresis:review`, resurfacing, merges, lint.

## To verify during planning

- Lens.org API terms and limits for an individual non-commercial user; Lens moved to a new
  non-profit on 2026-06-01.
- EPO OPS free-tier limits from its own terms page.
- Whether `claude-code-action` can load a marketplace from a git URL, and the token it needs.
- OpenAlex semantic-search parameter name and the free key's daily budget.
- Hacker News Algolia API limits.
- The mechanism for sharing retrieval code across plugins.
- That reading note bodies through JXA works on AJ's macOS version (no source tests it on Tahoe;
  an OS upgrade can reset the Automation permission).
- What `claude -p` returns when it hits a usage limit, and whether its output carries the
  five-hour figures, which would remove the need for the probe.
- That WSL systemd user timers run while AJ is logged out of the WSL shell.
- That Get Contents of URL accepts custom headers (`Authorization`, `Accept`) on current iOS.
