<!-- budget: 450 words -->
# Hook timing with hyperfine

`make bench` times each hook's whole command, as Claude Code runs it, next to `python3 -c pass`, with [hyperfine](https://github.com/sharkdp/hyperfine). The cases and their inputs are the ones in `tests/test_hook_latency.py`. `make bench-compare` then compares the result with a baseline and fails when a hook got slower.

The per-PR latency budgets in `tests/test_hook_latency.py` catch a large slowdown on every pull request. This bench catches a slow creep: the weekly `bench` workflow compares each hook with `bench/baseline-ci.json` at a tighter threshold.

## Running it

```bash
make bench                                    # writes bench/results/latest.json
make bench-compare BENCH_BASELINE=<summary>   # exit 1 when a hook regressed
```

`scripts/install_hyperfine.sh` downloads the pinned hyperfine once into `~/.cache/techne/` and checks its sha256 (Linux x86_64 and aarch64; elsewhere install hyperfine 2 yourself and set `HYPERFINE`). Run nothing else heavy while it measures. To compare a change locally, run `make bench BENCH_OUT=bench/results/main.json` on main, then `make bench` on the branch, then `make bench-compare BENCH_BASELINE=bench/results/main.json`. `TECHNE_GUARD_PYTHON` picks the python3 the hooks run on.

## What it records

For each case: the median wall time of the floor and of the hook, their ratio, the hook's spread, and, where the machine exposes hardware counters, the ratio of retired instructions. The summary also names the machine, the python3 and the commit.

## How a regression is decided

A case is judged by its ratio to the floor, so a faster or slower machine moves both sides. Both summaries must use the same python3 minor version, since a faster-starting python3 has a lower floor.

A growth of the wall-clock ratio past 1.15x fails. When both summaries have instruction counts, a growth of the instruction ratio past 1.05x fails too. Instructions alone would miss a hook that now waits on a lock, a sleep or the network, since waiting retires no instructions. GitHub's runners do not count instructions, so against `baseline-ci.json` only wall time is checked. The wall threshold comes from seven `bench` workflow runs on four CPU models (2026-11-04); the instruction threshold from repeated runs on AJ's PC (WSL2, 30 runs per case):

| Ratio | Largest run-to-run spread of any case |
|---|---|
| Instructions, AJ's PC, 4 runs on python3 3.14 and 3 on 3.12 | 1.002x |
| Wall clock, GitHub's runner, python3 3.14.10, 7 runs | 1.08x |
| Wall clock, AJ's PC, python3 3.12 | 1.09x |
| Wall clock, AJ's PC, python3 3.14 | 1.71x (one run of one case; the next largest was 1.16x) |

Wall time moves with whatever else the machine runs; instruction counts barely move. 1.05x leaves room for a different CPU or C library picking other code paths. 1.15x is about twice the runner's spread and, a test checks, below every case's per-PR budget. A busy local machine moves more: rerun a wall-only failure, or pass `--wall-threshold` to `bench/compare.py`.

## Refreshing the baseline

After a deliberate change in a hook's cost, rerun the `bench` workflow and commit the `bench-summary-<attempt>` artifact it uploads as `bench/baseline-ci.json`.
