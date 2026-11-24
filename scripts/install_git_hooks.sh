#!/bin/bash
# Install techne's git hooks (scripts/git-hooks/*) into this clone's hooks folder, which every
# worktree shares. A hook file that is not techne's (a symlink included) is left alone, and so
# is a core.hooksPath set to another folder: each prints why and how to wire the hook in.
set -euo pipefail

if ! root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    printf 'SKIP: not in a git repo, so no hooks to install\n' >&2
    exit 0
fi
src="$root/scripts/git-hooks"
dest="$(git rev-parse --path-format=absolute --git-path hooks)"
common="$(git rev-parse --path-format=absolute --git-common-dir)"
if [[ "$dest" != "$common/hooks" ]]; then
    printf 'SKIP: core.hooksPath is %s; call %s/<hook> "$@" from the hooks there\n' "$dest" "$src" >&2
    exit 0
fi
mkdir -p "$dest"
for hook in "$src"/*; do
    name="$(basename "$hook")"
    target="$dest/$name"
    if [[ -L "$target" ]] || { [[ -e "$target" ]] && ! grep -q 'techne pre-push hook (#396)' "$target"; }; then
        printf 'SKIP: %s exists and is not techne'"'"'s; call %s "$@" from it\n' "$target" "$hook" >&2
        continue
    fi
    cp "$hook" "$target.tmp.$$"
    chmod +x "$target.tmp.$$"
    mv -f "$target.tmp.$$" "$target"
    printf 'installed %s\n' "$target"
done
