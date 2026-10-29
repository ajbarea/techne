---
type: llm
---

PASS if the review reports, as Blocking or Should-fix, that a host value starting with `-` (for example `-oProxyCommand=...`) is read by ssh as an option, which can run a command, and asks for `--` before the host or a refusal of a leading dash, with a test. FAIL otherwise.
