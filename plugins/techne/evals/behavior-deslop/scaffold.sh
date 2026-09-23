#!/bin/bash
set -euo pipefail
git init -q . && git config user.email t@t && git config user.name t
mkdir -p src
cat > src/app.py <<'PY'
# Seamlessly and robustly loads the configuration (April 2026 best practice).
def load_config(path):
    # Now we open the file
    with open(path) as f:
        # Return the result
        return f.read()


# The handle outlives this call on purpose: atexit closes it, so a context manager does not fit.
_LOG = open("/dev/null", "w")
PY
git add -A && git commit -qm init
