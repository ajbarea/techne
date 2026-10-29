#!/bin/bash
set -euo pipefail
git init -q -b main . && git config user.email t@t && git config user.name t
cat > stats.py <<'EOF_FILE'
import sys


def read(path):
    return [float(x) for x in open(path).read().split()]
EOF_FILE
git add -A && git commit -qm base
git checkout -q -b feature
cat > stats.py <<'EOF_FILE'
import sys


def read(path):
    return [float(x) for x in open(path).read().split()]


def mean_latency(values):
    return sum(values) / len(values)


if __name__ == "__main__":
    print(f"mean latency: {mean_latency(read(sys.argv[1])):.1f} ms")
EOF_FILE
git add -A && git commit -qm "report the mean latency"
