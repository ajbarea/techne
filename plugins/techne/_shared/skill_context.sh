#!/usr/bin/env bash
# Print .claude/skill-context.md from the repo that owns TARGET, headed by the repo root.
# Usage: skill_context.sh [--base[=REF]] [target]
# TARGET is a file or directory, and need not exist yet: it resolves from its
# nearest existing parent. A bare word (PR number, branch, effort level) has
# none, so it resolves to the current directory's repo.
# --base prints the file as committed on REF instead of the working tree's, so a
# change under review cannot edit the hints that judge it. Without =REF it is the
# remote's default branch (origin/HEAD), else origin/main. Nothing else stands in:
# a missing ref or file is said, never filled from the branch under review.
set -u

base_mode=0
base_ref=""
case "${1:-}" in
  --base) base_mode=1; shift ;;
  --base=*) base_mode=1; base_ref=${1#--base=}; shift ;;
esac

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

if [ "$base_mode" -eq 1 ]; then
  g() { env -u GIT_DIR -u GIT_WORK_TREE git -C "$root" "$@"; }
  if [ -z "$base_ref" ]; then
    base_ref=$(g symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null) || base_ref=origin/main
  fi
  if ! g rev-parse -q --verify "${base_ref}^{commit}" >/dev/null 2>&1; then
    printf '(base %s not found in %s: fetch it, or pass --base=<the base ref>)\n' "$base_ref" "$root"
    exit 0
  fi
  if ! g cat-file -e "${base_ref}:.claude/skill-context.md" 2>/dev/null; then
    printf '(no .claude/skill-context.md on base %s in %s)\n' "$base_ref" "$root"
    exit 0
  fi
  printf '<!-- skill-context: %s (base %s) -->\n' "$root" "$base_ref"
  g show "${base_ref}:.claude/skill-context.md"
  exit 0
fi

if [ -f "$ctx" ]; then
  printf '<!-- skill-context: %s -->\n' "$root"
  cat -- "$ctx"
else
  printf '(no .claude/skill-context.md in %s)\n' "$root"
fi
