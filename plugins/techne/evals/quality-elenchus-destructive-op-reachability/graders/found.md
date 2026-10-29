---
type: llm
---

PASS if the review reports, as Blocking or Should-fix, that `rm -rf "$dest"` can delete the plugin's own source (or the user's data) because the destination can be or contain the source folder, e.g. `bash install.sh .`, `bash install.sh ..`, a destination that holds `plugin/`, or an empty `$1`, and asks for a refusal of those inputs before the rm. FAIL if it does not name this destructive path.
