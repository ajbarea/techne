---
type: llm
---

PASS if the review reports, as Blocking or Should-fix, that `load_url_path` lacks the outside-configs/ guard that `load_local` has, so a URL such as `file:///../secrets.txt` or `%2e%2e/` reads a file outside configs/, and asks for the same guard (ideally one shared helper) with a test. FAIL if it does not name the missing guard on the new path.
