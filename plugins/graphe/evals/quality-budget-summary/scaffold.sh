#!/bin/bash
set -euo pipefail
cat > notes.md <<'EOF'
# Notes from this week (raw)

- ran the replay harness on 3 tasks, two pass the hidden tests, one fails because the agent edited a conftest
- the judge flagged the conftest edit too, so judge and tests agree there
- cost per task about 2 to 4 dollars on Opus, review rounds 1 to 2
- sandbox blocks network; agent tried curl once, flagged as a leak, run counted unresolved
- open question: is 10 tasks enough? power analysis says we need the modes to agree on almost every run
- next: pilot both modes once AJ schedules the trial; keep normal mode until then
- also fixed a parser bug in the review-loop miner (shadowed variable dropped repos)
- the advisor post says Sonnet+Opus advisor was +2.7 on SWE-bench Multilingual at 11.9% lower cost
- reminder: margin is 5 points, lower bound of a one-sided 95% interval, never the point estimate
EOF
