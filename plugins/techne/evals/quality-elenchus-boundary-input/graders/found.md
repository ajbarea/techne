---
type: llm
---

PASS if the review reports, as Blocking or Should-fix, that an empty input file (zero values) makes `mean_latency` divide by zero (ZeroDivisionError), reachable from the CLI, and asks for the empty case to be handled with a test. FAIL otherwise.
