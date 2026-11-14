# Seats and lanes

A seat is one model on the panel. A lane is how its page reaches it. Claude seats are subagents of the session; every other seat is a CLI that `ask` runs. SEELE needs only Claude Code: the other lanes are used when they exist and skipped when they do not.

## Seat specs

Pass `--seat` once per seat to `open`. Without any `--seat`, `open` uses the lineup that `seats` prints. A panel holds 2 to 11 seats; with the chair that makes twelve monoliths at most.

| Spec | The seat | Run by |
|---|---|---|
| `claude:MODEL` | A Claude model: `opus`, `sonnet`, `haiku`, `fable` | The session, as a `techne:seele-seat` subagent |
| `agy` or `agy:MODEL` | Google's agy CLI, on its default model or the one named | `ask` |
| `copilot` | GitHub Copilot's CLI, which picks its own model | `ask` |
| `ollama:MODEL` | A local model through Ollama | `ask` |
| `cmd:NAME=COMMAND` | Any command that reads the page on stdin and prints its answer | `ask` |
| `fleet:agy`, `fleet:copilot` | The same two CLIs through a `fleet delegate` wrapper (see below) | `ask` |

Seat numbers follow the order of the `--seat` flags, starting at SEELE 02. SEELE 01 is the chair.

Two seats on the same model are allowed and count as two ballots. They are one family, and usually close to one opinion, so prefer different models.

## The default lineup

`seats` builds it from what is on PATH:

1. `claude:opus` and `claude:sonnet`, always.
2. `agy` and `copilot`, each when its CLI is found.
3. `claude:haiku`, when the list would otherwise have two seats.

Some setups put a quota-managing wrapper, `fleet delegate`, in front of agy and Copilot. When one is on PATH, the lineup uses `fleet:agy` and `fleet:copilot` in place of the direct forms. `seats` reads the wrapper's help text first, because unrelated tools are also named `fleet`.

Ollama is never seated by default, because a local model's quality varies too much to assume. Name it to seat it: `--seat ollama:qwen3`. Local inference is heavy; run it where the machine can take it.

`--claude-only` leaves out every CLI seat, so the brief stays inside the Claude session.

## How each CLI lane is locked

A seat has one job: read a page, print an answer. Each lane runs with the least it needs.

- **Every CLI lane** runs in a new temporary folder that is empty (for the `fleet:` lanes, an empty git repository) and is removed afterwards, in its own process group, with a timeout (`ask --timeout`, 600 seconds by default) and without the session's `GIT_*` variables. On a timeout, `ask` stops every process in that group and nothing else. Output is written to a file and read back up to 256 KiB.
- **agy** runs as `agy -p <page> --settings <file> --sandbox`. The settings file denies writes, commands, URL access and MCP tools, turns off access outside the empty folder, and trusts only that folder.
- **Copilot** runs as `copilot -p <page>` with the tool list cut to file viewing and search, writes and the shell denied, the built-in MCP servers off, and no questions to the user.
- **Ollama** runs as `ollama run MODEL` with the page on stdin.
- **A `cmd:` seat** runs your command as written, split into arguments without a shell, with the page on stdin. Locking it down is up to the command you give.
- **The `fleet:` lanes** hand the page to `fleet delegate --kind draft` with an empty git repository as the workspace, so the wrapper has nothing to snapshot but the page. The wrapper's stamp line is removed from the answer, and the model it reports is shown in the seat table.

Checked against agy 1.5.8 and GitHub Copilot CLI 1.0.109 and 1.0.112. A CLI that changes its flags fails loudly: the seat reads `NO SIGNAL` with the CLI's own error beside it.

## A seat for any other CLI

`cmd:` covers every model that has a command-line client. The command must read the page on stdin and print only its answer. Two examples, neither run by this repo's tests:

```text
--seat "cmd:codex=codex exec --sandbox read-only --skip-git-repo-check --ephemeral -"
--seat "cmd:gpt=llm -m gpt-5"
```

The name before `=` is what the report calls the seat and its model family, so name it after the model's maker when two `cmd:` seats share one.

## What leaves the machine

A Claude seat sends the brief where the session already sends everything. Every other seat except Ollama sends the brief and, in round 2, the candidates to that CLI's vendor under the user's account there. `seats` lists those seats on its `leaves this machine's Claude session` line. A lane never receives the repo, the conversation, the other seats' identities or `run.json`.

## Limits

| Limit | Value | Why |
|---|---|---|
| Page size, agy and Copilot | 120,000 bytes | The page travels as one command-line argument |
| Page size, `fleet:` lanes | 65,536 bytes | The wrapper's task-file limit |
| Page size, Ollama and `cmd:` | none from SEELE | The page travels on stdin |
| Answer size | 256 KiB read | A runaway seat cannot fill memory |
| Candidate length | 2,000 characters | Every candidate goes on every ballot, so one long proposal could push a ballot past a lane's page limit. A longer proposal is left out and `pool` says so |
| Proposals per seat | 2, or 5 in review mode (`--proposals`, 1 to 8) | More candidates make ranking less reliable |

A page over a lane's limit is refused before the CLI starts, and the seat reads `NO SIGNAL` with the two sizes. Shorten the brief or a candidate.

## When a seat reads NO SIGNAL

| Reason shown | What happened | What to do |
|---|---|---|
| `no answer` | A Claude seat wrote no file | Dispatch it again with the same two-line prompt |
| `its answer has no usable PROPOSAL line` (or `RANKING`) | The seat answered in another form | Dispatch it again; a second miss means leave it out |
| `exit N: ...` | The CLI failed; its last lines follow | Fix what it names (sign-in, quota), then `ask --seat <number> --again` |
| `no answer after N s` | Timeout | Raise `--timeout`, or leave the seat out |
| `could not start ...` | The command is not on PATH | Fix the spec; open a new run |

A CLI seat that failed in round 1 sits out round 2. A seat that answered in round 1 with nothing usable still gets a ballot: a model can judge well without having proposed.
