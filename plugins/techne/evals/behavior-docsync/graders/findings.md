---
type: llm
---

PASS if the response reports BOTH that `make build` has no matching Makefile target AND that `--verbose` is not a real flag of `python -m app`, and does not claim that `make test` or `--quiet` is wrong.
FAIL if it misses either real drift, or reports `make test` or `--quiet` as drift.
