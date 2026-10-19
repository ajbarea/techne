---
type: llm
---

The response must report these five entries of docs/research-log.md as lacking research provenance: the bare SHA-256 release, the 99th-percentile latency drop, the crawler reading of robots.txt, the forum-post redistribution licence reading, and the "state of the art and anonymous" README wording.

It must NOT report the 5-minute exclusion rule (it carries a no-source-found research tag), the survey free-text consent entry (it cites the IRB protocol section in the entry), the Holm correction entry (it cites Holm 1979 in the entry), or the "412 outputs" counts entry (descriptive prose).

Naming one of those four as already grounded, skipped, or as context for another finding is not reporting it as a gap.

PASS only if all five are reported and none of the four is listed as a gap. FAIL otherwise.
