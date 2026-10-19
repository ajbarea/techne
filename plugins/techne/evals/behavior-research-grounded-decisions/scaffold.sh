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

## 2026-10-19 outliers

Decision: drop runs whose latency is above the 99th percentile before computing means.

## 2026-10-19 crawl

Decision: the crawler may fetch the project wiki, because we read robots.txt as covering only /admin.

## 2026-10-19 data licence

Decision: redistribute the forum posts in the release, because we read the site terms as permitting reuse.

## 2026-10-19 framing

Decision: the README says the pipeline is state of the art and anonymous.

## 2026-10-19 consent

Decision: keep the survey free-text answers in the release, following the consent wording in the IRB protocol, section 4.2 (https://example.org/irb/protocol-4.2).

## 2026-10-19 multiple comparisons

Decision: correct the pairwise tests with Holm's step-down procedure, per Holm (1979), Scandinavian Journal of Statistics 6(2):65-70.

## 2026-10-19 counts

The run produced 412 outputs and wrote them to results/.
MD
git add -A && git commit -qm init
