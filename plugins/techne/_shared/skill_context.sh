#!/usr/bin/env bash
# Print .claude/skill-context.md from the repo that owns TARGET, headed by its path.
# Usage: skill_context.sh [target]
# TARGET is a file or directory. Anything that is not an existing path (a PR
# number, a branch, an effort level) resolves to the current directory's repo.
set -u

target="${1:-.}"
[ -e "$target" ] || target=.
[ -d "$target" ] || target=$(dirname -- "$target")

# A git hook exports GIT_DIR and GIT_WORK_TREE, which would override -C.
root=$(env -u GIT_DIR -u GIT_WORK_TREE git -C "$target" rev-parse --show-toplevel 2>/dev/null) \
  || root=$(cd -- "$target" && pwd)
ctx="$root/.claude/skill-context.md"

if [ -f "$ctx" ]; then
  printf '<!-- skill-context: %s -->\n' "$ctx"
  cat -- "$ctx"
else
  printf '(no .claude/skill-context.md in %s)\n' "$root"
fi
