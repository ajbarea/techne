---
type: llm
---

The reply is a CI report as JSON for a run whose Windows `cargo test` step failed.
PASS if ALL hold: `verdict` is "failure"; `failing_step` names the `cargo test` step of the windows-latest job, its root cause names the test `a_maximized_then_minimized_window_is_placed_normal_without_the_focus` (or its assertion "a window has the foreground"), and its location is split.rs line 1073 (either slash); `logging.names_the_cause` is true, or false with notes that say there is no `::error` annotation on the file; the runner's Ubuntu 26 notice, if listed, is not FIX.
FAIL if the verdict is not "failure", the location is missing or names a workflow file, the report says it fixed or edited anything, or the reply is not JSON.
