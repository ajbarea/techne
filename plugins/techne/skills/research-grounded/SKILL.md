---
name: research-grounded
description: Audit a repo's decisions — technology choices, data release and privacy, study design, access-rule readings, public-claim wording — in IMPL.md / ROADMAP.md and its decision records for missing `# research(YYYY-MM):` provenance, then web-search to ground them. Use when you want choices verified against current best practice or the governing source before they harden into code or a release, rather than resting on training-cutoff recall. Catches committed decisions stated as fact but never checked — the class of miss that becomes revertable work.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit WebSearch WebFetch Agent
---

# Research-grounded

`<plugin-root>` is the plugin's root directory, two levels above the directory holding this SKILL.md.

Catch decisions that were made without checking current best practice — *before* they become code or a release. A doc that says "we'll use X" or "we'll publish Y" with no provenance is a bet on training-cutoff recall; the convention `# research(YYYY-MM): <tradeoff> <source>` records that the bet was checked against reality. This skill finds the bets that weren't.

## Repo context

`/techne:research-grounded` audits docs in the CWD repo by default, or a path you name (which may live in another repo). Read that repo's skill-context:

```bash
bash "<plugin-root>/_shared/skill_context.sh" <target-doc>   # no path arg → CWD repo
```

It isn't required, but its `## repo` section helps you tell a genuine technology choice from incidental prose. An optional `## research_grounded` block names the repo's decision records, audited in addition to `IMPL.md` and `ROADMAP.md`:

```yaml
decision_docs:
  - docs/research-log.md
  - docs/adr/
```

Entries are files, directories, or globs (research logs, registered or pre-registered decisions, ADRs, design specs). `IMPL.md` + `ROADMAP.md` are always in scope; unset, they are the whole scope.

## What needs provenance

A **committed design decision** — a choice with real alternatives, where picking wrong is expensive to undo:

- **Library / framework / tool** — "MapLibre + PMTiles", "Playwright over Cypress", "switched from JWT to server sessions".
- **Pattern / technique** — "event delegation over per-node listeners", "stale-while-revalidate", "container queries for card internals".
- **Architecture / protocol** — "A2A `Message.metadata` instead of text tags", "OPFS for tile storage".
- **Version / API-surface bets stated as fact** — "ElevenLabs v3 supports SSML break tags" (the miss that cost 5 revertable PRs: a capability asserted, never verified against the target's docs).
- **Data release / privacy / anonymisation** — "publish a bare SHA-256 of model outputs in place of the text" (the hash of public text is a dictionary lookup and protects nothing; [EDPB Guidelines 01/2025](https://www.edpb.europa.eu/system/files/2025-01/edpb_guidelines_202501_pseudonymisation_en.pdf) (footnote 23, paras 88-90) prefer keyed one-way functions, so a keyed HMAC replaced it).
- **Study / method design** — sampling frame, thresholds, exclusion rules, statistical procedure: "drop runs under 30 samples", "Bonferroni over Holm".
- **Governance / access-rule readings** — licences, robots.txt / ToS, permissions: "the API terms allow redistribution", "robots.txt does not cover the REST endpoint".
- **Wording of public claims** — what a README, paper, or release note asserts: "anonymised", "state of the art", "no personal data". `/techne:docsync` checks a claim against the code and `/graphe:paper-review` checks a contribution against prior work; this skill checks that the choice of what to assert has a source.

Each of these, when committed in a decision doc, should carry an adjacent `# research(YYYY-MM): <one-line tradeoff> <source>`. Negative-space decisions ("we did **not** do X because…") need provenance too. When the search finds no source, the tag says so: `# research(YYYY-MM): no source found - <what was searched>`. An untagged decision is a gap; a no-source tag is an answer.

> research(2026-10): MADR records each decision with considered options and a justified outcome, and states it fits any decision, not only architecture (https://adr.github.io/madr/). OSF's preregistration guidance has researchers anticipate deviations and justify each update to a registration (https://help.osf.io/article/145-preregistration). Both support recording the alternatives and the reason beside the decision, which is what the tag does.

## Ignore

- **Descriptive implementation prose.** "reads the metrics object instead of re-reading constants", "returns a structured fallback instead of a retry loop" — uses decision words but picks no technology or pattern. Not research-worthy.
- **Hypotheticals & aspirations.** "what if we used sessions instead of JWT", "we plan to", "coming soon" — not yet a commitment (mirrors how `/techne:docsync` waves through roadmap language).
- **Already grounded.** A decision with a `research(...)` tag on the same bullet or within a few lines — even a terse one.
- **Bugfixes, renames, mechanical changes** — no alternative space to research.
- **Settled house conventions** — the fleet's own recorded standards (SHA-pinning, squash-merge). Don't re-flag every mention.
- **Descriptive prose in decision docs.** A log entry reporting a result or a count picks nothing among alternatives.

## Workflow

1. **Scope.** The **decision docs** are `IMPL.md` + `ROADMAP.md` plus every `decision_docs` entry in the `## research_grounded` block that `skill_context.sh` printed. Accept a named file or directory (e.g. `planning/`) instead. Append-only logs (research logs, registered-decision files) grow without bound: audit the entries added since the last audit (`git log -S'research(' -1`, or the last audit commit) or the latest 30, and say which window and how many entries; audit older entries only when named. For multiple files, fan out — one `Explore` subagent per file (see [Fan-out](#fan-out-pattern)).

2. **Find candidate decisions — three grep passes, then read the design sections.** The greps seed candidates; judgment decides which are research-worthy per the lists above.

   **Pass A — decision verbs** (catches "Library … over …" and "Pattern over pattern" phrasing):

   ```bash
   grep -rnEi 'chose|switched|adopted|replaced|opted for|we use|picked|migrated|over [A-Za-z.-]+ \(|instead of' <decision docs>
   ```

   **Pass B — capability & best-practice-as-fact** (catches the costliest class — "Version / API-surface bets stated as fact" — which carries *no* decision verb, so Pass A is blind to it):

   ```bash
   grep -rnEi 'supports?|exposes?|provides?|enables?|natively|built-in|out of the box|standard|canonical|idiomatic|recommended|modern|best practice' <decision docs>
   ```

   Pass B surfaces "RealtimeTTS *exposes* word-timing for Kokoro", "*Standard* FastAPI 2026 setup", "the 2026 *modern* … *standard* is X" — claims a verb-grep never sees.

   **Pass C — non-technology decisions** (data release, privacy, study design, access rules, claim wording; no technology name and no decision verb, so A and B are blind to it):

   ```bash
   grep -rnEi 'hash|anonymi|pseudonym|redact|publish|release|withhold|consent|licen|robots|permission|threshold|exclude|registered|state of the art|first|novel|guarantee|proves|anonymous' <decision docs>
   ```

   Pass C surfaces "publish the SHA-256 of each output", "exclude sessions under 5 min", "robots.txt allows the crawl". Judge per hit; most are descriptive (`first`, `release` and `publish` especially).

   **No grep is sufficient — also read the doc's design / architecture sections directly.** All three passes are noisy *and* leaky: a bet phrased as a bare proper-noun list ("Postgres + SQLModel + asyncpg", "MapLibre + PMTiles", "on `Message.metadata`") trips no keyword at all. The real signal is **proper-noun library / protocol / API names**; `.claude/skill-context.md`'s `## repo` section tells you which tokens are this repo's technology choices. Classify per-hit, not per-match — most Pass A `instead of`, Pass B `supports`/`standard`, and Pass C `release`/`publish` hits are descriptive prose.

   > research(2026-05): off-the-shelf prose linters (proselint / write-good / Vale) flag *style* weasel-words ("very", "quite"), **not** capability-claims-missing-provenance — so this seed is bespoke by necessity, not a reinvented wheel.

3. **Check provenance.** For each genuine decision, look for a `research(YYYY-MM):` (or `# research:`) tag on the same bullet or within a few lines. Present → grounded, skip (a `no source found` tag counts). An in-record citation also counts: a link, a DOI, or a named document with its section ("EDPB 01/2025 para 88"), beside the decision or in its entry. Absent → gap.

4. **Report gaps.** One entry per un-grounded decision:

   ```
   ROADMAP.md:88
     decision: "embed offline maps with MapLibre + PMTiles"
     gap:      no research provenance — grounded in 2026 offline-map options, or recall?
     action:   web-search current PMTiles/MapLibre tradeoffs → add `# research(2026-05): <tradeoff> <source>`
   ```

   Decision-doc example:

   ```
   docs/research-log.md:41
     decision: "publish a bare SHA-256 of each model output in place of the text"
     gap:      no provenance — is a plain hash of public text anonymisation, or recall?
     action:   web-search pseudonymisation guidance → add `# research(2026-10): <finding> <source>`, or `no source found`
   ```

5. **Ground or flag (on confirmation).**
   - **Ground it** (the point of the skill — close the loop, don't just flag): web-search the decision's current best practice, then add `# research(YYYY-MM): <tradeoff> <source>` capturing what you actually found, or `no source found - <query>` when the search came up empty.
   - **Flag only:** if grounding needs the user's domain context a quick search can't supply, leave a one-line note to ground it *before* it hardens into code.
   - **Never invent a citation.** A `research()` tag with a fabricated or unread source is worse than no tag.

## Fan-out pattern

For a directory (e.g. `planning/`), spawn one `Explore` subagent per file; each returns a gap report for its file. Consolidate, present grouped by file, then ask `ground all / ground selected / skip?`.

## Don't touch

- Docs the user didn't name or imply and `decision_docs` doesn't list; git history / changelogs (historical, not live bets).
- `research()` tags that already exist — don't reword a grounded decision unprompted.
- Decisions already shipped as code with no alternative left to research — audit the plan, not the past.

## Why this skill is quiet

Output is the gap report and, on confirmation, the web-searched `research()` tags. No narration of the scan — just `decision → gap → action`. Sibling of `/techne:docsync` (claims vs code); this is decisions vs evidence.
