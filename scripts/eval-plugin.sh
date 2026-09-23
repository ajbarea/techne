#!/bin/bash
# Assemble the eval-only plugin that `make evals` routes against: techne's real skills plus
# stand-ins for the general document and catch-up skills that share a session with them.
# An eval case can load one plugin set, not techne *and* a second plugin, so both go in one.
# Output is generated and gitignored; the path is fixed, never taken from an argument.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/plugins/techne"
out="$root/eval-fixtures/with-rivals"

rm -rf "$out"
mkdir -p "$out/.claude-plugin" "$out/skills"
cp -r "$root/skills/." "$out/skills/"
cp -r "$root/_shared" "$out/_shared"
cp -r "$root/eval-fixtures/rival-skills/skills/." "$out/skills/"
printf '{\n  "name": "techne",\n  "version": "0.0.0-eval",\n  "description": "techne plus rival stand-ins, for routing evals only"\n}\n' \
    > "$out/.claude-plugin/plugin.json"
printf 'eval plugin: %s (%s skills)\n' "$out" "$(find "$out/skills" -name SKILL.md | wc -l)"
