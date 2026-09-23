---
type: llm
---

PASS if the response proposes deleting or rewriting the "Seamlessly and robustly loads the configuration (April 2026 best practice)" comment AND proposes deleting at least one of the narration comments ("Now we open the file", "Return the result") AND does not propose deleting the comment explaining why the handle outlives the call (atexit / context manager).
FAIL if it leaves the "Seamlessly and robustly" comment alone, or proposes removing the atexit / context-manager comment.
