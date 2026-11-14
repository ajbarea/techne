# The report

`report` prints the verdict and saves the same text as `report.md` in the run folder, with the logo under the title. This page explains each part and ends with a full example.

## The parts

| Part | What it tells you |
|---|---|
| The monoliths | One block per seat, SEELE 01 (the chair) first. `SOUND ONLY`: the seat was heard in the last round held. `NO SIGNAL`: it was not. |
| The panel line | How many seats voted and from how many model families. One family is weaker evidence than several. |
| The seat table | Which model held each seat, and what each did in each round. A `NO SIGNAL` cell carries the reason. This is the only place models are named; no seat and no chair saw it. |
| The pick | The chair's choice among the voted candidates, with its reasons. One of three lines follows it: the pick is also the vote's winner, the chair broke a tie, or **the chair overruled the vote**. |
| Amended by the chair | A repair to the pick's wording. The seats did not vote on it, and the report says so. Treat it as a suggestion from one model. |
| The vote | One row per candidate, best first. *Points* are Borda points. *First choice* counts ballots that ranked it first. *Rejected by* counts ballots that said it should not be used at all. *Average from other seats* is its mean points per ballot without its own author's ballot. *Proposed by* names the seats that wrote it, or the user. |
| Notes under the vote | Agreement among the seats (Kendall's W: 1 means identical rankings, 0 means none shared), every flag, and every merge the clerk made. |
| The strongest objection to the pick | The chair's own strongest objection, then what each seat that ranked the pick first said against it. A pick with no recorded objection has not been tested. |
| Dissents | The vote itself when the chair overruled it, then every seat whose first choice was not the pick or that rejected the pick, with that seat's reasons. |
| Where the seats agreed and split | The chair's reading of the ballots. |

## Flags

A flag marks a result that needs a second look. Each one is printed by `tally` and again under the vote.

| Flag | What it means |
|---|---|
| The vote tied | Points, head-to-head results and first choices could not separate the leaders. The chair's pick breaks the tie. |
| X leads on points, but Y beats every other candidate head to head | Two sound ways of counting disagree. Y is preferred by a majority in every pairing; X is ranked high more consistently. Read both candidates' objections. |
| The lead changes without each author's own ballot | The leader depends on a seat voting for its own proposal. The seats that had no stake prefer another candidate. |
| Every voting seat is from one model family | The seats share training and tend to share mistakes. Add a seat from another family when the decision matters. |
| A majority rejected every candidate | No answer survived. Rewrite the brief, or accept that the question has no good answer yet. |

## Review mode

A review report replaces "The pick" with "The chair's ruling" and adds three sections after the vote:

- **The recommendation line** counts the seats' verdicts ("Accept, 3 of 4") and names the seats on each side when they differ, then gives the chair's own.
- **Proposed changes** are the ones no seat rejected, in a table: the change, who raised it, its points, and why it helps.
- **Your call** lists changes at least one seat rejected, with that seat's reason. These are the ones to think about.
- **Declined** lists changes a majority rejected, with the reasons.

The pick in a review is the single change the chair thinks matters most.

## An example

A fixture run with made-up answers, printed by the script. Four seats proposed five titles for a conference talk. The vote tied; the chair broke the tie and repaired the wording.

````markdown
# SEELE verdict: Title for the flaky-tests talk

```text
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ SEELE 01 │ │ SEELE 02 │ │ SEELE 03 │ │ SEELE 04 │ │ SEELE 05 │
│  SOUND   │ │  SOUND   │ │  SOUND   │ │  SOUND   │ │  SOUND   │
│   ONLY   │ │   ONLY   │ │   ONLY   │ │   ONLY   │ │   ONLY   │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
```

**Panel:** 4 seats voted, from 3 model families (anthropic, copilot, google). SOUND ONLY: the seat answered. NO SIGNAL: it did not, and the table says why. No seat saw another seat's answer or knew who wrote a candidate, and neither did the chair.

| Seat | Model | Round 1 | Round 2 |
|---|---|---|---|
| SEELE 01 | fable (chair: no seat, no vote) | - | ruled |
| SEELE 02 | Claude opus | SOUND ONLY | SOUND ONLY |
| SEELE 03 | Claude sonnet | SOUND ONLY | SOUND ONLY |
| SEELE 04 | agy | SOUND ONLY | SOUND ONLY |
| SEELE 05 | Copilot (auto) | SOUND ONLY | SOUND ONLY |

## The pick

**C. Why Quarantining Flaky Tests Cost Us Eight Months**

Amended by the chair (the seats did not vote on this wording): **Quarantining Flaky Tests Hid a Shared Cache for Eight Months**

The vote tied between A and C; the chair broke the tie.

Why: The brief asks for a title that says what the reader will learn and sounds checkable. A states the cause and C states the cost; the ballots split evenly between them, and each side's objection is that its title is missing the other half. C is the one that can carry both in ten words.

## The vote

| | Candidate | Points | First choice | Rejected by | Average from other seats | Proposed by |
|---|---|---|---|---|---|---|
| A | Most of Our Flaky Tests Shared One Cache | 13 | 2 | 0 | 3.5 | SEELE 02, SEELE 05 |
| C | Why Quarantining Flaky Tests Cost Us Eight Months | 13 | 2 | 0 | 3 | SEELE 03 |
| D | Quarantine Hid the Cause of Our Flaky Tests | 10 | 0 | 0 | 2.67 | SEELE 02 |
| E | Flaky Tests Are a Shared-State Problem | 3 | 0 | 2 | 0.67 | SEELE 04 |
| B | What a Year of Flaky Tests Taught Us | 1 | 0 | 3 | 0.33 | SEELE 05 |

Points are Borda points (a first place among k candidates is worth k-1, a last place 0). "Average from other seats" leaves out the ballot of each candidate's own author.

- Agreement among the seats (Kendall's W, 0 to 1): 0.80 (the seats ranked alike).
- The vote tied between A and C on points, head to head and first choices.

## The strongest objection to the pick

- The chair: At ten words the amended title is at the limit, and it drops the 70% figure that makes the result sound measured.
- SEELE 03, which ranked it first: a reader cannot tell what the cause was.
- SEELE 05, which ranked it first: it reads as a complaint until the cause is named.

## Dissents

- **SEELE 02** (Claude opus) ranked A first: states the result; checkable. On C: concrete cost, cause missing.
- **SEELE 04** (agy) ranked A first: states the result; checkable. On C: concrete cost, cause missing.
- The chair on the dissents: SEELE 02 and SEELE 04 ranked A first because it states the finding itself.

## Where the seats agreed and split

- Agreed: Every ballot put B and E in its bottom two; three of four rejected B outright.
- Split: Two ballots lead with the cause (A) and two with the cost (C). The split turns on whether the audience is drawn more by a finding or by a mistake they may be making.
````
