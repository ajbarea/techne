#!/bin/bash
set -euo pipefail
git init -q . && git config user.email t@t && git config user.name t
mkdir -p src docs .claude
cat > .claude/skill-context.md <<'MD'
## scan_scope
pattern_sources:
  - "docs/style-glossary.md"
MD
cat > docs/style-glossary.md <<'MD'
# Words our reviewers reject

- "seamlessly", "robust", "battle-tested", "production-ready": hype with no measurement behind it.
- "Now we ...", "Here we ...": narration of what the next line does.
MD
cat > src/app.py <<'PY'
# A battle-tested, production-ready loader that seamlessly reads the file.
def load(path):
    with open(path) as f:
        return f.read()
PY
git add -A && git commit -qm init
