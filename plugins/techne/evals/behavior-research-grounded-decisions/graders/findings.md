---
type: llm
---

PASS if the response reports the SHA-256 data-release decision in docs/research-log.md as lacking research provenance, AND does not report the 5-minute exclusion rule (it carries a no-source-found research tag), AND does not report the "412 outputs" counts entry (descriptive prose).
FAIL if it misses the hash decision, reports the tagged exclusion rule, or reports the counts entry.
