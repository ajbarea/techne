#!/bin/bash
# Guard: every remote GitHub Actions `uses:` ref in .github/workflows/ must be
# pinned to a full 40-char commit SHA. Mutable tags let anyone with write access
# repoint a tag at a malicious commit (tj-actions/changed-files, 2025-03, ~23k
# repos). The trailing `# vX.Y.Z` comment is kept for readability and bumped by
# Dependabot. Local (`./…`) and `docker://…` refs are exempt.
# See docs/conventions.md "Pinning GitHub Actions to commit SHAs".

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOWS="$ROOT/.github/workflows"

[[ -d "$WORKFLOWS" ]] || { printf 'OK: no .github/workflows/ to check\n'; exit 0; }

violations=0
shopt -s nullglob
for f in "$WORKFLOWS"/*.yml "$WORKFLOWS"/*.yaml; do
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

printf 'OK: all GitHub Actions in .github/workflows/ are SHA-pinned\n'
