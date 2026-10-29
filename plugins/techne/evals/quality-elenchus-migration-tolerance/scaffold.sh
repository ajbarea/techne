#!/bin/bash
set -euo pipefail
git init -q -b main . && git config user.email t@t && git config user.name t
cat > session.py <<'EOF_FILE'
import json


def load(path):
    data = json.load(open(path))
    return {
        "id": data["id"],
        "title": data.get("title", "untitled"),
        "messages": data.get("messages", []),
    }


def save(path, session):
    json.dump(session, open(path, "w"))
EOF_FILE
git add -A && git commit -qm base
git checkout -q -b feature
cat > session.py <<'EOF_FILE'
import json


def load(path):
    data = json.load(open(path))
    return {
        "id": data["id"],
        "title": data.get("title", "untitled"),
        "messages": data.get("messages", []),
        "model": data["model"],
    }


def save(path, session):
    json.dump(session, open(path, "w"))
EOF_FILE
git add -A && git commit -qm "sessions remember the chosen model"
