---
name: idea
description: Capture an idea and triage it against prior work. Saves the idea to the user's ideas repository, then searches papers, patents, products and the user's own research for anything like it, names the closest existing work, and files the idea as trash, later, do or merged with the evidence. Use when the user shares an idea for an app, tool, product, research direction or improvement and wants it saved or checked, such as "I have an idea", "save this idea", "has anyone built", "is this worth building", "triage my idea", or "/heuresis:idea". Not for reviewing a written paper's novelty (graphe:paper-review).
argument-hint: "[--now] <idea text> | --triage <id> | --retriage <id> | --override <id> <state> <reason>"
disable-model-invocation: false
allowed-tools: Bash Read Agent
---

# Capture and triage an idea

`IDEAS` is `${user_config.ideas_repo}` and `REPOS` is `${user_config.repos_root}`. If either is empty, stop and tell the user to run `/heuresis:setup`; do not run it yourself.

Every command below starts with:
`env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis`
(written `heuresis` below). Pass `IDEAS` and `REPOS` as absolute paths.

A failing command prints `heuresis: <message>` on stderr and exits 1 (exit 2 for a rejected argument). Report the message to the user and stop; do not retry the same command blindly. If the message says the idea was saved locally but publishing failed, tell the user the idea is safe on disk and what the publish error was. Once the user has fixed the cause, `heuresis publish --ideas IDEAS` commits and pushes every pending change under `ideas/` and `runs/`.

## Pick the mode

- `<idea text>` without `--now`: capture only. Pass the user's text unchanged on stdin through a quoted heredoc, so the shell leaves `$`, backticks and quotes alone:
```
heuresis capture --ideas IDEAS --text - <<'HEURESIS_IDEA'
<idea text>
HEURESIS_IDEA
```
  It prints the final id on stdout, which can differ from the id you expect when the date and title are already taken, so use the printed id. Say the idea is in the inbox and can be triaged with `--triage <id>`. Stop.
- `--now <idea text>`: capture, then triage the printed id.
- `--triage <id>` or `--retriage <id>`: triage an existing idea. A retriage adds a new verdict and keeps the old ones.
- `--override <id> <state> [--type T] [--project P] [--duplicate-of X] <reason>`: run `heuresis override --ideas IDEAS <id> <state> ... <reason>` and stop. This records the user's own decision.

## Triage

1. **Restate.** Read the idea file `IDEAS/ideas/<id>.md`. Write a neutral one-paragraph restatement: what it does, for whom, how. Drop praise, excitement and claims of novelty. Write 3 to 5 search queries of 3 or 4 words. Save both:
```
heuresis restate --ideas IDEAS --id <id> --json - <<'JSON'
{"restated": "...", "queries": ["...", "..."]}
JSON
```
   Restate starts a fresh run: it deletes the previous run's scout, pool, judge and verify files. It writes only `runs/<id>/restate.json`; apply copies the restatement into the idea file.
2. **Scout in parallel.** In one message, dispatch four Agent calls with `subagent_type` `heuresis:scout-papers`, `heuresis:scout-patents`, `heuresis:scout-products` and `heuresis:scout-context`. Give each `IDEAS`, `REPOS`, the id, the restatement and queries. Do not pass the user's original wording or any opinion about the idea.
3. **Pool.** `heuresis pool --ideas IDEAS --id <id> > /dev/null`. Pool numbers the records afresh and deletes any earlier judge.json and verify.json, so the judge and verify always run after it.
4. **Judge.** Dispatch `heuresis:judge` with `IDEAS`, the id and the context scout's reply.
5. **Verify.** `heuresis verify --ideas IDEAS --id <id> --repos-root REPOS`. If it fails on judge.json itself, send the message back to `heuresis:judge` once and run verify again. Exit 3 means the closest rival's quote failed: dispatch `heuresis:judge` once more, listing the failed refs as dropped, then run verify again. Do not loop a third time. Run verify again after every judge run, because apply counts a ref as verified only when `verify.json` passed that ref for the quote now in `judge.json` and the record now at that ref in `pool.json`.
6. **Apply.** `heuresis apply --ideas IDEAS --id <id>`. The rules run here: a `do` without a verified closest rival and paper results becomes `later`. If apply reports a judge.json problem, send the message back to `heuresis:judge` once, then verify and apply again. If apply says pool.json changed, run pool, judge, verify and apply again.
7. **Report** to the user in four lines: the state, type and project; the closest rival with its link; the reason; the next step. Link the idea file. If any source was skipped for a missing key, name the key once.
