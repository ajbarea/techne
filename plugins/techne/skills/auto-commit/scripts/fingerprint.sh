#!/bin/bash
# Print a 12-character fingerprint of the working tree for COMMITS.md's staleness header.
#
# Covers the staged diff, the unstaged diff, file status, and the contents of untracked
# files, because a plan must go stale when what is staged changes or a new file appears.
# COMMITS.md itself is excluded: the skill writes it after fingerprinting, and counting it
# would make every plan look stale. Pathspecs are anchored at the repo root, so the result
# is the same from any subdirectory. On any git failure it prints nothing and exits non-zero,
# so a caller never records a hash of partial input.

set -euo pipefail
shopt -s inherit_errexit  # a failing git inside $( ) must abort, not leave a partial hash

# Untracked paths print relative to the cwd, so run from the root for one answer everywhere.
root="$(git rev-parse --show-toplevel)"
cd "$root"
scope=(-- ':/' ':(exclude,top)COMMITS.md')
# Before the first commit there is no HEAD; diff against the empty tree instead.
base="$(git rev-parse -q --verify HEAD 2>/dev/null || git hash-object -t tree /dev/null)"

untracked() {
    local path
    while IFS= read -r -d '' path; do
        if [[ -d "$path" ]]; then
            # An untracked nested repository is listed as a directory; git cannot hash it.
            printf 'dir %s %s\n' "$path" "$(git -C "$path" rev-parse -q --verify HEAD 2>/dev/null || echo none)"
        else
            printf 'file %s %s\n' "$path" "$(git hash-object -- "$path")"
        fi
    done < <(git ls-files -z --others --exclude-standard "${scope[@]}")
}

input="$(
    git diff --cached --binary "$base" "${scope[@]}"
    printf '\n--- unstaged\n'
    git diff --binary "${scope[@]}"
    printf '\n--- status\n'
    git status --porcelain=v1 -uall "${scope[@]}"
    printf '\n--- untracked\n'
    untracked
)"
printf '%s' "$input" | git hash-object --stdin | cut -c1-12
