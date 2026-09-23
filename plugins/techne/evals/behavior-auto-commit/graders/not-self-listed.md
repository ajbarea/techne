---
type: regex
pattern: '^Files:.*COMMITS\.md'
flags: m
match: not_contains
target: { source: file, path: COMMITS.md }
---
