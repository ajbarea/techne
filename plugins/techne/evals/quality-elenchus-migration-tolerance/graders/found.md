---
type: llm
---

PASS if the review reports, as Blocking or Should-fix, that `load` now reads `data["model"]`, so a session file saved by the previous release (which has no `model` key) raises KeyError on reopen, and asks for a default like its siblings' `.get(...)` plus a test loading an old file. FAIL otherwise.
