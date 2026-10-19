#!/bin/bash
set -euo pipefail
git init -q . && git config user.email t@t && git config user.name t
mkdir -p .claude docs
cat > .claude/skill-context.md <<'MD'
## repo

- name: study
- language: Markdown

## research_grounded

```yaml
decision_docs:
  - docs/research-log.md
```
MD
printf '# Roadmap\n\nShip the report in the spring.\n' > ROADMAP.md
cat > docs/research-log.md <<'MD'
# Research log

## 2026-10-19 data release

Decision: publish a bare SHA-256 of each model output in place of the text, so the release carries no raw text.

## 2026-10-19 sampling

Decision: exclude sessions shorter than 5 minutes.
# research(2026-10): short sessions are mostly bot traffic; no source found - searched session-length filters in usage-log studies.

## 2026-10-19 counts

The run produced 412 outputs and wrote them to results/.
MD
git add -A && git commit -qm init
