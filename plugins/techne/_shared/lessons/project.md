<!-- budget: 339 words -->
# Lessons for projects and app UI

Read with `common.md` before building or restyling a project's user-facing surface.

## Reference to beat

- [klepsydra](https://github.com/ajbarea/klepsydra), for a live wall that reads at a glance.
- Before calling the work done, open the reference and the new work side by side and name one way the new one is better and one way it is worse.

### look-at-the-gui: A dashboard shows what files hide

- **Rule:** When a tool has a web UI, open it at 1920 wide alongside reading its config.
- **Why:** A dashboard flagged benchmarks as dominated by system calls, which the config and code never said.
- **Since:** 2026-11-04
- **Check:** guidance: a person reads the page.

### performance-first: Performance before security when they trade off, above a security floor

- **Rule:** Check data structures and repeated work in any code you touch, and fix what you find; security stays a floor.
- **Why:** Tools that run on every call make every slowdown felt everywhere.
- **Since:** 2026-11-03
- **Check:** guidance: `tests/test_hook_latency.py` covers the hooks; a general rule cannot be gated.

### yagni: Flag speculative work

- **Rule:** Before building, name the current caller; with none, flag it as speculative and defer it.
- **Why:** Presumptive infrastructure took over a release cycle and had no user.
- **Since:** 2026-05-16
- **Check:** guidance: whether a caller will exist cannot be computed.

### harness-first: Built-ins before scripts

- **Rule:** Check the harness's built-ins and changelog before building a mechanism, and say what gap the new one fills.
- **Why:** A home-grown copy goes stale and misses improvements.
- **Since:** 2026-10-25
- **Check:** guidance: whether a built-in covers a need is a judgment.

## Retired
