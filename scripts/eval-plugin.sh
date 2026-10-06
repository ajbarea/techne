#!/bin/bash
# Assemble the eval-only plugins that `make evals` routes against. Each holds every skill from
# every plugin here plus stand-ins for the general document and catch-up skills, named after
# the plugin whose cases load it, so a description that overlaps a sibling plugin's skill or a
# stand-in fails a case. An eval case can load one plugin set, so they all go in one.
# Output is generated and gitignored; the paths are fixed, never taken from an argument.

set -euo pipefail

plugins="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/plugins"

for root in "$plugins"/*/; do
    root="${root%/}"
    [ -d "$root/eval-fixtures/rival-skills" ] || continue
    name="$(basename "$root")"
    out="$root/eval-fixtures/with-rivals"

    rm -rf "$out"
    mkdir -p "$out/.claude-plugin" "$out/skills" "$out/_shared"
    for src in "$plugins"/*/; do
        for dir in skills _shared eval-fixtures/rival-skills/skills; do
            if [ -d "$src/$dir" ]; then
                case "$dir" in
                _shared) cp -r "$src/$dir/." "$out/_shared/" ;;
                *) cp -r "$src/$dir/." "$out/skills/" ;;
                esac
            fi
        done
    done
    printf '{\n  "name": "%s",\n  "version": "0.0.0-eval",\n  "description": "%s plus sibling skills and rival stand-ins, for routing evals only"\n}\n' \
        "$name" "$name" >"$out/.claude-plugin/plugin.json"
    printf 'eval plugin: %s (%s skills)\n' "$out" "$(find "$out/skills" -name SKILL.md | wc -l)"
done
