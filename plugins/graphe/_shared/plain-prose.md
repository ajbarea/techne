# Plain prose

Canonical cross-skill rubric for documents people read: papers, proposals,
reports, slides and their scripts. Loaded before drafting by `/graphe:latex`,
`/graphe:pdf`, `/graphe:paper` and `/graphe:slides`, and checked by
`/graphe:paper-review`. Update this file, not the skills.

Write the plain version the first time. A draft that needs a separate
"concise pass" was written in the wrong register.

The test for every sentence: does a reader learn something from it that no
other sentence tells them? If not, cut it.

## Sentences

- **One claim per sentence.** Split a sentence that carries two.
- **Plain verbs.** "describes" not "characterises", "use" not "leverage" or
  "utilize", "helps" not "facilitates".
- **Lead with the fact.** No throat-clearing ("It is worth noting that", "It
  should be emphasized").
- **No closing aphorisms.** A line that restates the paragraph as a maxim adds
  nothing the paragraph did not say.
- **No commentary on your own text** ("the paper's least comfortable
  observation", "the interesting shape of the result", "the honest framing").
  State the observation.
- **Name the count, not a quality.** "Stopped the attack 2 of 5 times", not
  "resisted the attack more often".
- **No em-dashes.** Use a comma, a colon, parentheses, or two sentences.
  Hyphens in compounds and en-dashes in ranges stay.

| Before | After |
| --- | --- |
| That inference holds only if the checker fails loudly whenever it cannot do its job, which is a property it has to be given rather than one it has by construction. | That is safe only if the checker fails loudly whenever it cannot do its job, and a checker behaves that way only if it was built to. |
| The correction was applied everywhere except where the cache was covering, which is to say everywhere it was needed. A cache asserts that an old answer is still valid, and changing the question invalidates it silently. | The fix applied everywhere except where the cache covered, which was exactly where it was needed. |
| The middle group yields to the obvious discipline. | The middle group yields to a simple practice. |
| At equal parameter count, the more expressive encoding resisted the attack more often than the deeper trainable block. | At 28 parameters, more encoding layers stopped the attack 2 of 5 times; more trainable layers, 0 of 5. |

## Claims

Style was the smaller half of what went wrong. Check each of these against the
source, not against the draft.

- **Every number traces to its source**: the code, the data file, the run log.
  A parameter count must count what the code counts.
- **A description of a method matches the code that runs it.** "Repeated r
  times, alternating with l layers" and "each followed by l layers" give
  different parameter counts.
- **A summary of a cited paper matches its full text**, not its abstract or
  your memory of it. Qualifiers get lost first ("under an underparameterized
  attacker", "a weak privacy breach").
- **"Consistent with X" only when the setups match.** Otherwise say which way
  the result points and how the setup differs.
- **Promise only what the time allows.** A proposal separates what the report
  will answer from extensions, in order, and states the scope limit.

## Structure

- A manuscript for a venue has the sections that venue expects. An IEEE or ACM
  paper without Related Work or References is incomplete however clean the
  prose is.
- Every section earns its place. A deliverables line the prompt requires stays;
  a biography nobody asked for goes.

## Length

The sentence rules cannot see a document that says each thing three times.

- **Set the budget before drafting**, from the prompt, the venue, or, for a
  revision, the original. Declare it on one comment line of the source:
  `% budget: 4 pages` in LaTeX, `<!-- budget: 1200 words -->` in markdown,
  or both limits joined by a comma (`none` when the venue's limit excludes the
  references). A document with no limit declares
  `budget: none`. The latex and pdf gates block a PDF over it and ask for one
  when none is declared.
- **Say each result once.** Other sections point to it. Only the abstract and
  the conclusion restate the main result.
- **A revision cuts as much as it adds.** A point a reviewer says "would help",
  or asks for "briefly", gets a sentence, not a section.
- **A correction edits the sentence it corrects.** A review finding that needs
  a caveat changes the existing sentence instead of adding one.
- **Evidence stays in the repo.** Logs, run tables and diffs stay in the
  evidence files; the document states the claim and names its source.
- **A response letter** opens with a summary of changes, one line each. Each
  answer gives the change and where it is in one to three sentences, with
  reasons only where nothing changed. A point several reviewers raise is
  answered once; the other answers point to it.
- **Every review of a document also lists cuts**: the sentences that repeat
  another or that nothing requires. A reviewer that only asks for caveats
  grows the document every round, so a reviewer's brief includes this section.

## Mechanical patterns

Read by `_shared/prose_check.py`, which the latex and pdf gates run, together
with the *Modern LLM tells* section of `_shared/hate-words.md` (reported as
`llm-tell`). Vocabulary belongs in that glossary; this block holds the
document-level patterns. Each line is `name | regex`, matched
case-insensitively. Hits are `REVIEW` findings: a
candidate for the eye, never a verdict. The em-dash pattern skips, case-sensitively,
the ones IEEEtran sets after "Abstract" and "Index Terms". In markdown, `---`
between words counts too, since Typst's smart punctuation sets it as one. A pattern belongs here only when a hit
is almost always a line to rewrite.

```prose-patterns
em-dash | (?-i:(?<!Abstract)(?<!Index Terms))\u2014
throat-clearing | \b(it is|it's) (worth noting|important to note|worth mentioning)\b|\bit should be (noted|emphasi[sz]ed)\b
self-commentary | \b(least|most) comfortable observation\b|\bthe (honest|interesting) (framing|shape)\b|\bthe direction of the error is\b
ornate-verb | \b(leverag|utiliz|utilis|facilitat)(e|es|ed|ing)\b
filler | \bin order to\b|\bthe fact that\b|\bserves to\b|\bplays? an? (key|crucial|vital|pivotal) role\b
stacked-hedge | \b(may|might|could) potentially\b
```

Sentences longer than 40 words are reported too, as `long-sentence`.
