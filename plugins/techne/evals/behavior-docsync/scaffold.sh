#!/bin/bash
set -euo pipefail
git init -q . && git config user.email t@t && git config user.name t
mkdir -p app
printf 'test:\n\tpytest\n\nlint:\n\truff check .\n' > Makefile
cat > app/__main__.py <<'PY'
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--quiet", action="store_true")
args = parser.parse_args()
if not args.quiet:
    print("app ran")
PY
cat > test_app.py <<'PY'
import subprocess
import sys


def test_quiet_silences_output():
    out = subprocess.run([sys.executable, "-m", "app", "--quiet"], capture_output=True, text=True)
    assert out.stdout == ""
PY
printf '[project]\nname = "app"\nversion = "0.1.0"\n\n[dependency-groups]\ndev = ["pytest", "ruff"]\n' > pyproject.toml
cat > README.md <<'MD'
# app

Build it with `make build`, then run the suite with `make test`.

Run it with `python -m app --verbose` for detailed output, or `--quiet` to silence it.
MD
git add -A && git commit -qm init
