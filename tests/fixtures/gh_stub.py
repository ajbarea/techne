"""A stand-in for gh: logs each call and answers from a rule file.

GH_STUB_RULES names a JSON list of rules, {"match": [tokens], "stdout": str, "stderr": str,
"exit": int, "sleep": seconds}; the first rule whose tokens all appear in argv answers, and a
call no rule matches exits 1. A token matches an equal argument; a token "*x" matches an
argument ending in x. GH_STUB_LOG names a JSON-lines file that gets {"argv", "stdin"}
for every call.
"""

import json
import os
import sys
import time

argv = sys.argv[1:]
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
with open(os.environ["GH_STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": argv, "stdin": stdin}) + "\n")
with open(os.environ["GH_STUB_RULES"], encoding="utf-8") as f:
    rules = json.load(f)


def matches(token: str) -> bool:
    if token.startswith("*"):
        return any(arg.endswith(token[1:]) for arg in argv)
    return token in argv


for rule in rules:
    if all(matches(token) for token in rule["match"]):
        time.sleep(rule.get("sleep", 0))
        sys.stdout.write(rule.get("stdout", ""))
        sys.stderr.write(rule.get("stderr", ""))
        sys.exit(rule.get("exit", 0))
sys.stderr.write(f"gh stub: no rule for {argv}\n")
sys.exit(1)
