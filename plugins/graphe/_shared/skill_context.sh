#!/usr/bin/env bash
# Print .claude/skill-context.md from the repo that owns TARGET, headed by the repo root.
# Usage: skill_context.sh [target]
# TARGET is a file or directory, and need not exist yet: it resolves from its
# nearest existing parent. A bare word (PR number, branch, effort level) has
# none, so it resolves to the current directory's repo.
set -u

arg="${1:-.}"
target=$arg
while [ ! -e "$target" ]; do target=$(dirname -- "$target"); done
[ -d "$target" ] || target=$(dirname -- "$target")
# Walking a path argument all the way back to . means none of it exists: a typo or
# an unexpanded ~. Say so rather than silently reading the current repo.
if [ "$target" = . ] && [ "$arg" != . ] && [[ $arg == */* ]]; then
  printf "(target %s not found; showing the current directory's repo)\n" "$arg"
fi
# Inside a .git directory there is no work tree; resolve from its parent.
case "/$target/" in
  */.git/*) t="/$target/"; t=${t%%/.git/*}; t=${t#/}; target=${t:-.} ;;
esac

# A git hook exports GIT_DIR and GIT_WORK_TREE, which would override -C.
root=$(env -u GIT_DIR -u GIT_WORK_TREE git -C "$target" rev-parse --show-toplevel 2>/dev/null) \
  || root=$(CDPATH='' cd -P -- "$target" >/dev/null && pwd) \
  || root=$target
ctx="$root/.claude/skill-context.md"

if [ -f "$ctx" ]; then
  printf '<!-- skill-context: %s -->\n' "$root"
  cat -- "$ctx"
else
  printf '(no .claude/skill-context.md in %s)\n' "$root"
fi
