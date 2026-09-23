#!/bin/bash
# Print a 12-character fingerprint of the working tree for COMMITS.md's staleness header.
#
# Covers tracked edits, index state, and the contents of untracked files, because a new
# file added after planning must make the plan stale. COMMITS.md itself is excluded: the
# skill writes it after fingerprinting, and counting it would make every plan look stale.
# Pathspecs are anchored at the repo root, so the result is the same from any subdirectory.

set -euo pipefail

scope=(-- ':/' ':(exclude,top)COMMITS.md')
{
    git diff HEAD --binary "${scope[@]}"
    git status --porcelain=v1 -uall "${scope[@]}"
    git ls-files -z --others --exclude-standard "${scope[@]}" | xargs -0 -r git hash-object --
} | git hash-object --stdin | cut -c1-12
