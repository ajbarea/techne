---
type: regex
target: { source: file, path: summary.md }
pattern: '(?:\S+\s+){150}\S'
match: not_contains
---
