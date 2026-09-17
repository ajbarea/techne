#!/bin/bash
# Guard: every remote GitHub Actions `uses:` ref in .github/workflows/ and in the
# .github-template/ starter workflows must be pinned to a full 40-char commit SHA. Mutable tags let anyone with write access
# repoint a tag at a malicious commit (tj-actions/changed-files, 2025-03, ~23k
# repos). The trailing `# vX.Y.Z` comment is kept for readability and bumped by
# Dependabot. Local (`./…`) and `docker://…` refs are exempt. Dependabot never
# reads .github-template/, so each starter must also match the live workflow of
# the same name exactly, or its pins would rot unseen.
# See docs/conventions.md "Pinning GitHub Actions to commit SHAs".

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOWS="$ROOT/.github/workflows"
TEMPLATES="$ROOT/.github-template/workflows"

[[ -d "$WORKFLOWS" ]] || { printf 'OK: no .github/workflows/ to check\n'; exit 0; }

violations=0
shopt -s nullglob
for f in "$WORKFLOWS"/*.yml "$WORKFLOWS"/*.yaml "$TEMPLATES"/*.yml "$TEMPLATES"/*.yaml; do
    lineno=0
    while IFS= read -r line; do
        lineno=$((lineno + 1))
        if [[ "$line" =~ uses:[[:space:]]*([A-Za-z0-9_.-]+/[^@[:space:]]+)@([^[:space:]#]+) ]]; then
            ref="${BASH_REMATCH[1]}"
            rev="${BASH_REMATCH[2]}"
            case "$ref" in ./* | docker://*) continue ;; esac
            if ! [[ "$rev" =~ ^[0-9a-f]{40}$ ]]; then
                printf 'FAIL: %s:%d: %s@%s is not pinned to a full commit SHA\n' \
                    "${f#"$ROOT"/}" "$lineno" "$ref" "$rev" >&2
                violations=$((violations + 1))
            fi
        fi
    done <"$f"
done

if [[ "$violations" -gt 0 ]]; then
    printf 'GitHub Actions must be SHA-pinned (run `pinact run`; see docs/conventions.md).\n' >&2
    exit 1
fi

uses_refs() { grep -oE 'uses:[[:space:]]*[^[:space:]#]+' "$1" | sed -E 's/uses:[[:space:]]*//' | sort -u; }

for t in "$TEMPLATES"/*.yml "$TEMPLATES"/*.yaml; do
    live="$WORKFLOWS/$(basename "$t")"
    [[ -f "$live" ]] || continue
    if ! drift="$(diff <(uses_refs "$live") <(uses_refs "$t"))"; then
        printf 'FAIL: %s pins differ from %s (< live, > template):\n%s\n' \
            "${t#"$ROOT"/}" "${live#"$ROOT"/}" "$drift" >&2
        violations=$((violations + 1))
    fi
done

if [[ "$violations" -gt 0 ]]; then
    printf 'Copy the live pins into the starter workflow.\n' >&2
    exit 1
fi

printf 'OK: all GitHub Actions are SHA-pinned, and starter workflows match the live pins\n'
