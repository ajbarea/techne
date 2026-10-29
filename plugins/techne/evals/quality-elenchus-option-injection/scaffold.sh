#!/bin/bash
set -euo pipefail
git init -q -b main . && git config user.email t@t && git config user.name t
cat > hosts.py <<'EOF_FILE'
HOSTS = []
EOF_FILE
git add -A && git commit -qm base
git checkout -q -b feature
cat > hosts.py <<'EOF_FILE'
import subprocess
import sys

HOSTS = []


def ssh_config(host: str) -> str:
    """The effective ssh settings for HOST, as `ssh -G` prints them."""
    return subprocess.run(["ssh", "-G", host], capture_output=True, text=True, check=True).stdout


if __name__ == "__main__":
    print(ssh_config(sys.argv[1]))
EOF_FILE
git add -A && git commit -qm "probe a host's ssh config"
