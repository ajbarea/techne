#!/usr/bin/env python3
"""Stand-in for `claude -p` in runner tests. Behaviour comes from FAKE_CLAUDE_MODE."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

mode = os.environ.get("FAKE_CLAUDE_MODE", "trash")
prompt = sys.argv[sys.argv.index("-p") + 1]
ideas = Path(next(iter(re.findall(r"--ideas (\S+)", prompt))))
idea_id = next(iter(re.findall(r"--triage (\S+)", prompt)))
plugins = [{"name": "heuresis", "path": "/plugins/heuresis"}]
if mode == "no-plugin":
    plugins = []
if mode == "two-plugins":
    plugins = [
        {"name": "heuresis", "path": "/plugins/other"},
        {"name": "heuresis", "path": os.environ["FAKE_PLUGIN_DIR"]},
    ]
if "FAKE_CLAUDE_RECORD" in os.environ:
    Path(os.environ["FAKE_CLAUDE_RECORD"]).write_text(
        json.dumps(
            {
                "argv": sys.argv[1:],
                "cwd": os.getcwd(),
                "auto_memory": os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY"),
            }
        )
    )
print(json.dumps({"type": "system", "subtype": "init", "plugins": plugins}), flush=True)
if mode == "sleep":
    # A child that inherits the output pipes and outlives its parent, as a tool subprocess would.
    child = subprocess.Popen(["sleep", "30"])
    Path(os.environ["FAKE_CLAUDE_PIDFILE"]).write_text(str(child.pid))
    time.sleep(30)
if mode == "guard":
    guard = Path(os.environ["FAKE_CLAUDE_GUARD"])
    (guard / "ideas" / "stray.md").write_text("written by mistake")
if mode in ("guard-modified", "guard-untracked"):
    # Same-length rewrite of a file that was already dirty, so `git status` does not change.
    target = Path(os.environ["FAKE_CLAUDE_GUARD"]) / (
        "tracked.md" if mode == "guard-modified" else "untracked.md"
    )
    target.write_text("B" * len(target.read_text()))
if mode in ("trash", "guard", "two-plugins"):
    sys.path.insert(0, os.environ["HEURESIS_SRC"])
    from heuresis import cli, store
    from heuresis.model import FACETS

    path = store.idea_path(ideas, idea_id)
    idea = store.load(path)
    idea.state = "trash"
    idea.sections["Closest work"] = "**Closest:** [dokimasia](https://x) (github)"
    store.save(ideas, idea)
    run = ideas / "runs" / idea_id
    run.mkdir(parents=True, exist_ok=True)
    # The shapes the CLI writes, so a grade sees a verified rival named "dokimasia".
    record = {
        "ref": "r1",
        "title": "dokimasia: bibliography checks",
        "url": "https://github.com/ajbarea/techne",
        "source": "github",
        "kind": "repo",
        "evidence_url": "https://api.example/r1",
    }
    quote = "verifies bibliography entries"
    for name, data in {
        "restate": {"restated": "x", "queries": ["q"]},
        "pool": {"records": [record], "coverage": [], "queries": {}},
        "judge": {
            "closest": {"ref": "r1", "quote": quote, "differs": dict.fromkeys(FACETS, "")},
            "others": [],
        },
        "verify": {
            "r1": {
                "ok": True,
                "reason": "",
                "quote": quote,
                **{k: record[k] for k in cli.BOUND},
            }
        },
    }.items():
        (run / f"{name}.json").write_text(json.dumps(data))
if mode == "crash":
    print("fatal: session diagnostics", file=sys.stderr)
    sys.exit(3)
print(
    json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "total_cost_usd": 0.25,
            "duration_ms": 1000,
            "num_turns": 4,
        }
    ),
    flush=True,
)
