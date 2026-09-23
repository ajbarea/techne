---
type: regex
pattern: '^(feat|fix|docs|chore|refactor)\([^)]+\): '
flags: m
match: "count:2"
target: { source: file, path: COMMITS.md }
---
