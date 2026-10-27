---
type: llm
---

PASS if the response reports ALL of: (1) the description names only the usage-limit bar and so omits the fleet wall the code ships (`gauge wall`); (2) the `electron` topic is stale, since the app is built with Tauri (Cargo.toml) and not Electron; (3) a fix given as a `gh repo edit` command (or its exact flags) whose new description covers both the bar and the wall. It must not report the `## The bar` or `## The wall` sections as wrong.
FAIL if it misses any of the three, or reports a correct README section as drift.
