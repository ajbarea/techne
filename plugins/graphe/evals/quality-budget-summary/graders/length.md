---
type: regex
target: { source: file, path: summary.md }
pattern: '(?:\S+\s+){160}'
match: not_contains
---
