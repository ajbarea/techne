#!/bin/bash
set -euo pipefail
git init -q . && git config user.email t@t && git config user.name t
mkdir -p src
printf '# Tool\n\nTeh tool does things.\n' > README.md
printf 'def add(a, b):\n    return a + b\n' > src/calc.py
git add -A && git commit -qm "feat(calc): add"
printf '# Tool\n\nThe tool does things.\n' > README.md
printf 'def mul(a, b):\n    return a * b\n' > src/mul.py
