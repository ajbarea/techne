<!-- budget: 422 words -->
# Lessons for papers

Read with `plain-prose.md` and `paper-quality.md`, which hold the sentence-level and genre rules; these are the lessons those files do not carry.

## Reference to beat

- The target venue's accepted papers, recorded in the paper's `conventions.md` (`paper-quality.md`, "Learn the genre from accepted papers"). A repo may name its own best accepted paper in `.claude/skill-context.md`, under `## paper-review`, as `exemplar:`.
- Before calling a draft done, compare it to that reference on title, abstract moves, and how the claim is stated, and say where the new draft falls short.

### explain-every-equation: Every equation has a plain-words meaning

- **Rule:** Give every equation, formula and statistical rule its meaning in plain words where it first appears, and before a talk or an advisor reads it, a sheet of each symbol, why it is there, and a small worked number.
- **Why:** An author must be able to explain every line of their own paper aloud.
- **Since:** 2026-11-05
- **Check:** guidance: whether a sentence explains an equation cannot be computed.

### budget-before-drafting: A length budget before the first sentence

- **Rule:** Declare the budget in the source before drafting; a venue's limit is hard, a self-set budget is a target that may be raised with a one-line reason.
- **Why:** Review rounds only add, so drafts grow past what anyone will read.
- **Since:** 2026-10-20
- **Check:** gate: plugins/graphe/_shared/length_budget.py#def markdown_words, test: test_markdown_words_skip_table_bars_bullets_code_and_comments

### candidate-is-not-a-decision: A candidate reads differently from a decision

- **Rule:** Mark scaffolding as scaffolding, and never take a limit, deadline or structure from a venue a file merely names until you have checked it was chosen.
- **Why:** A scaffolded venue line was read back as settled and produced a page budget against a limit that did not apply.
- **Since:** 2026-08-15
- **Check:** guidance: a file cannot state whether a line is a plan.

### reword-do-not-transcribe: Reword a correction, do not paste it

- **Rule:** Fix the claim in as few words as the sentence needs; the author's explanation is context, and every edit is re-read in its paragraph.
- **Why:** A pasted explanation adds length and can land where it reads as someone else's work.
- **Since:** 2026-11-05
- **Check:** guidance: this is a judgment on each edit.


## Retired
