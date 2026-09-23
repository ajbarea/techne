---
type: regex
pattern: 'techne:auto-commit[\s\S]*tree-hash:\s+[0-9a-f]{12}'
target: { source: file, path: COMMITS.md }
---
