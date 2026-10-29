---
type: llm
---

PASS if the review reports, as Blocking or Should-fix, that the pattern `\bmg\b` does not match "10mg" (no word boundary between the digit and "m"), which the docstring promises, and that no test covers that case. FAIL otherwise.
