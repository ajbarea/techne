---
name: seele
description: Convene SEELE, a blind panel of models, when a decision should not rest on one model's opinion, such as a title, a name, a wording, a design choice, or a review of a paper or proposal. Every seat (Claude models always; agy, Copilot or a local model when their CLIs exist) answers the same brief alone, the pooled answers are ranked blind with authors hidden and a different order for each judge, and a chair that holds no seat rules. The report shows the vote table, the pick, the strongest objection to it and every dissent; a chair that disagrees with the vote is shown beside it, never silently outvoted. Use when asked to "ask SEELE", "convene SEELE" (also typed "SELEE"), "convene the council", "put it to a panel", "get more than one model's opinion", "have the models vote", "which title wins", or for a panel review of a draft. Not for code review (use elenchus) or for a question a test or a document can answer.
disable-model-invocation: false
allowed-tools: Bash Read Write Grep Glob Agent
---

# SEELE

`<plugin-root>` is the plugin's root directory, two levels above the directory holding this SKILL.md.

One model's opinion is one sample. Ask it again, or ask it with the options in another order, and the answer can change. SEELE puts the decision to a panel instead: every seat answers the same brief alone, the pooled answers are ranked blind, and a chair that holds no seat reads everything and rules. What comes back is the answer that survived the disagreement, with the disagreement attached.

Each seat is a dark monolith with a number and a voice. A seat that answered reads `SOUND ONLY`. A seat that did not reads `NO SIGNAL`, with the reason beside it.

## Your role: the clerk

You carry paper. You do not judge.

- You write the brief, seat the panel, hand each seat its page, and relay the report.
- You never vote, never edit a candidate, and never tell a seat or the chair who wrote what.
- A seat's prompt is two lines and nothing else. Any hint you add (the topic, your own view, "the user likes B") is a thumb on the scale.
- Never run a seat or the chair as a fork. A fork inherits this conversation, which is the opposite of blind.

`seele.py` does the mechanical work: the shared page, the blind ballots, the count, the chair's anonymous docket, the report. Every command below prints what to do next.

## When to convene, and when not

Convene for a judgment call where a wrong pick costs more than a few model calls: a paper or talk title, a product or project name, the wording of a claim, a choice between designs, a review of a draft before it goes out.

Do not convene for a question with a checkable answer (run the test, read the docs), for code review (`/techne:elenchus` reproduces and traces; a panel only reads), or for a choice the user can undo in a minute. Each seat is called twice and the chair once.

Seats have no tools. They judge from the brief alone, so any fact the decision turns on has to be in the brief. Do the research first, then convene.

## 1. Frame the brief

The brief is the one page every seat reads, so it has to stand alone. A seat cannot see this conversation, the repo, or the user's files. Write it to a new file in a scratch folder (`mktemp -d`).

Put in:

- The question, in one sentence.
- What the answer is for and who will read it.
- Hard limits: length, venue rules, words that must or must not appear.
- The material a seat needs to answer: the abstract, the function's signature, the paragraph in question. Paste it in. For a long document, attach it instead (step 3).
- What a good answer does, stated as criteria.

Leave out:

- **Any candidate answer**, the user's or yours. Round 1 is blind so that the seats cannot anchor on a list. When the user already has candidates, hold them back; they join the pool unnamed in step 4.
- Who favours what, your own opinion, and any earlier verdict. A judge shown a prior score moves toward it.
- Secrets. Never put a token, a password or a private key in a brief.

For a review, name the outcomes the seats choose between (for a paper: accept, minor revision, major revision, reject) and the criteria the venue uses.

## 2. Seat the panel

```bash
python3 "<plugin-root>/skills/seele/scripts/seele.py" seats
```

This prints the lineup this machine can fill. Claude seats (Opus and Sonnet) always sit. agy and GitHub Copilot sit when their CLIs are on PATH, and Haiku joins when the panel would otherwise have two seats. A panel drawn from more than one model family is worth more: models from one family tend to make the same mistakes, and the report says so when every seat is Claude.

The line `leaves this machine's Claude session` names the seats that send the brief to another vendor. Tell the user which seats will sit before you open the run. Add `--claude-only` when the brief holds anything the user has not cleared to leave: unpublished text, private or team code, personal data. When you cannot ask and you are unsure, use `--claude-only` and say so beside the report.

For a different lineup, pass `--seat` once per seat to `open`. The spec forms (`claude:MODEL`, `agy`, `copilot`, `ollama:MODEL`, `cmd:NAME=COMMAND`, and the `fleet:` lanes) and how each CLI is locked down are in [references/lanes.md](references/lanes.md).

## 3. Round 1: blind proposals

```bash
python3 "<plugin-root>/skills/seele/scripts/seele.py" open --brief <brief-file> --topic "<short title>"
```

Add `--mode review` for a review, `--attach <file>` for each text file the seats must read (convert a PDF to text first), and `--claude-only` or your `--seat` list from step 2.

`open` prints the run folder and one line per seat:

```text
run: <run>
round 1:
  SEELE 02  subagent model=opus  paper=<path>  answer=<path>
  SEELE 04  agy  run by `ask`
  then: seele.py ask --run <run> --round 1
```

Do both of these at once:

- **Seats marked `run by ask`:** run the `then:` command in the background. It asks every CLI seat in parallel and prints `SOUND ONLY` or `NO SIGNAL: <reason>` for each.

  ```bash
  python3 "<plugin-root>/skills/seele/scripts/seele.py" ask --run <run> --round 1
  ```

- **Seats marked `subagent`:** dispatch one Agent call per seat with `subagent_type: "techne:seele-seat"`, `model` set to the model on the line, and exactly this prompt:

  ```text
  Your paper: <paper>
  Write your answer to: <answer>
  ```

  Send the Agent calls in one message so the seats answer at the same time, unless this session's rules cap how many subagents run at once. If the `techne:seele-seat` agent type is not available, use `general-purpose` with the same model and add one line to the prompt: `Read only the first file. Write your answer to the second file with the Write tool, in the form your paper asks for. A reply in chat is not counted.`

Wait for every seat and for `ask` to finish. Do not read the answers aloud or comment on them; the next command reads them.

## 4. Pool

```bash
python3 "<plugin-root>/skills/seele/scripts/seele.py" pool --run <run>
```

When the user has candidates of their own, write them to a file, one per line, and add `--add <file>`. They enter the pool like any other candidate, and the report lists them as proposed by the user.

`pool` prints each seat's status, the candidates, and the round 2 lines. It pools two proposals as one only when their words match (case, spacing, surrounding quotes and final punctuation aside), leaves out any proposal over 2,000 characters and says so, and writes each seat a ballot: the candidates only, with no authors and no pitches, in a different order for each seat, under labels that mean nothing to any other seat.

- A seat shown `NO SIGNAL` in round 1 gets one more try. Dispatch a Claude seat again with the same prompt; for a CLI seat run `ask --run <run> --round 1 --seat <number> --again`. Then run `pool` again.
- `pool` refuses when fewer than two seats answered. One answer is not a panel: fix the lanes or tell the user.
- When every seat proposed the same thing, `pool` says to skip round 2. Go to step 7.
- **Review mode only:** read the candidate list. Where two candidates ask for the same change in different words, fold one into the other and keep the clearer wording:

  ```bash
  python3 "<plugin-root>/skills/seele/scripts/seele.py" merge --run <run> <keep> <drop>
  ```

  Merge only what is plainly the same change. The report records every merge. In decide mode do not merge: two titles that differ by a word are different candidates.

## 5. Round 2: blind ranking

Run round 2 the way you ran round 1, with the lines `pool` printed: `ask --run <run> --round 2` in the background for the CLI seats, and one Agent call per Claude seat with the ballot as its paper. Every seat votes, including one that proposed nothing. A seat whose CLI failed in round 1 sits out.

## 6. Count, then the chair

```bash
python3 "<plugin-root>/skills/seele/scripts/seele.py" tally --run <run>
```

`tally` counts the ballots, prints the leader and any flag, and writes the chair's docket: the brief, the candidates, the vote, and every ballot's reasons, with seats, models and authors removed. Its last line names the docket and the ruling file.

Dispatch the chair as one more `techne:seele-seat` Agent call with `model: "fable"` and the same two-line prompt, with the docket as its paper and the ruling file as its answer. If this account has no Fable (the Agent call rejects the model), use `model: "opus"`. The chair must be a fresh agent. You are not the chair, even when you are the strongest model in the room: you framed the brief and watched the seats answer.

- `tally` refuses when fewer than two ballots can be read. Re-ask the seats shown `NO SIGNAL`, then run it again.
- If the chair fails twice, go on without it. The report then says the vote's winner stands alone.

## 7. Report

```bash
python3 "<plugin-root>/skills/seele/scripts/seele.py" report --run <run> --chair-model <fable or opus>
```

Relay what it prints to the user as it is. It is the deliverable: the monoliths, the seat table, the pick, the vote, the strongest objection to the pick, and every dissent. The same text is saved as `report.md` in the run folder, with the logo. [references/report.md](references/report.md) explains each part.

- If `report` says the ruling names no candidate, or more than one, dispatch the chair once more and tell it the `PICK` line takes one letter alone. Then run `report` again.
- After the report you may add up to three lines of your own: what a flag means for this decision, and what the user might do next. If you disagree with the pick, say so in one line marked as the clerk's view. Never fold your view into the report.
- The panel advises and the user decides. Do not rename the file, retitle the paper or apply the change unless the user asked for that.

## Reading the result

- **The pick** is the chair's. The chair may pick a candidate that did not lead the vote, and may repair the wording on a separate line that the report marks as not voted on.
- **The vote** is the seats'. When the chair overrules it, the report says so in bold and lists the vote as the first dissent. When the chair agrees, it says that too.
- **Flags** mark a result that deserves a second look: a tie, a leader that loses head to head, a lead that depends on a candidate's own author, a panel from one model family, a candidate every seat rejected.
- **Agreement** (Kendall's W) says how alike the rankings were. Low agreement with a clear chair pick means the question is open and the chair's reasons carry the weight. Read them.

Runs are kept under `~/.local/state/seele/` (or `$XDG_STATE_HOME/seele/`). Nothing there is deleted for you.

## Why it is built this way

Each rule above answers a measured failure of model judges. [references/research.md](references/research.md) gives the source for each.

| Rule | The failure it answers |
|---|---|
| Round 1 has no candidate list | A judge shown options or scores anchors on them |
| A different order for each ballot, balanced across seats | Models favour a position in a list |
| Private labels on each ballot | Models favour certain option letters |
| Candidates without pitches or authors | Longer answers win votes; models recognise and favour their own text |
| A recount without each author's own ballot | Hiding the author does not remove self-preference |
| Seats from several model families | Same-family judges make the same mistakes |
| No debate rounds | Voting gives most of debate's gain; debate adds conformity |
| A chair with no seat, ruling from an anonymous docket | A judge that also competes favours itself |
| Both the vote and the chair's pick are shown | Neither a majority nor a single judge is reliable alone |

## Why "SEELE"

SEELE is the council in *Neon Genesis Evangelion*: a ring of black monoliths, each with a number and the words SOUND ONLY, that decides what no single voice is trusted to decide. The name is German for "soul". The skill keeps the staging and drops the secrecy: every seat is named in the report, every ballot is on the record, and a voice that disagreed is always heard.
