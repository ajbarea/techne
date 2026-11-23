#!/usr/bin/env bash
# Print .claude/skill-context.md from the repo that owns TARGET, headed by the repo root.
# Usage: skill_context.sh [--base[=REF] | --base-sha[=REF]] [target]
# TARGET is a file or directory, and need not exist yet: it resolves from its
# nearest existing parent. A bare word (PR number, branch, effort level) has
# none, so it resolves to the current directory's repo.
# --base prints the file as committed on the base branch instead of the working
# tree's, so a change under review cannot edit the hints that judge it. The base is
# REF, else the remote's default branch (refs/remotes/origin/HEAD), else
# refs/remotes/origin/main. A short REF prefers refs/remotes/REF, and a name that
# also names a local branch or a tag is refused, since either can be the branch under
# review wearing the base's name. Nothing else stands in: a missing or ambiguous ref,
# or a missing file, is said, never filled from the branch under review.
# --base-sha prints only "<full ref> <commit>" for that base, or a reason on stderr
# and exit 1 (elenchus's own_checks.py resolves its base through it).
set -u

base_mode=0
base_ref=""
case "${1:-}" in
  --base) base_mode=1; shift ;;
  --base=*) base_mode=1; base_ref=${1#--base=}; shift ;;
  --base-sha) base_mode=2; shift ;;
  --base-sha=*) base_mode=2; base_ref=${1#--base-sha=}; shift ;;
esac
for a in "$@"; do
  case "$a" in
    --base*) printf '(%s must come before the target; nothing read)\n' "$a"; exit 0 ;;
  esac
done

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

if [ "$base_mode" -ne 0 ]; then
  g() { env -u GIT_DIR -u GIT_WORK_TREE git -C "$root" "$@"; }
  has() { g show-ref --verify -q "$1"; }
  why=""
  if [ -z "$base_ref" ]; then
    full=$(g symbolic-ref -q refs/remotes/origin/HEAD 2>/dev/null) || full=refs/remotes/origin/main
  elif [[ $base_ref == refs/* || $base_ref == FETCH_HEAD || $base_ref =~ ^[0-9a-f]{7,40}$ ]]; then
    full=$base_ref
  else
    full=""
    for kind in remotes heads tags; do
      has "refs/$kind/$base_ref" || continue
      if [ -n "$full" ]; then
        why="base $base_ref is ambiguous ($full and refs/$kind/$base_ref): pass --base=$full"
        break
      fi
      full="refs/$kind/$base_ref"
    done
    [ -n "$full" ] || full=$base_ref
  fi
  sha=""
  [ -n "$why" ] || sha=$(g rev-parse -q --verify "${full}^{commit}" 2>/dev/null) \
    || why="base $full not found in $root: git fetch it, or pass --base=<the base ref>"
  # A single-branch clone of the branch under review points origin/HEAD at that branch:
  # a base that is the reviewed commit, or a remote branch of the same name, is no base.
  # (A branch made from origin/main tracks origin/main; that base is fine.)
  if [ -z "$why" ]; then
    branch=$(g symbolic-ref -q --short HEAD 2>/dev/null) || branch=""
    if [ "$sha" = "$(g rev-parse -q --verify HEAD 2>/dev/null)" ] \
      || { [ -n "$branch" ] && [[ $full == refs/remotes/*/"$branch" ]]; }; then
      why="base $full is the branch under review: pass --base=<the branch it merges into>"
    fi
  fi
  if [ -n "$why" ]; then
    [ "$base_mode" -eq 2 ] && { printf '%s\n' "$why" >&2; exit 1; }
    printf '(%s)\n' "$why"
    exit 0
  fi
  if [ "$base_mode" -eq 2 ]; then
    printf '%s %s\n' "$full" "$sha"
    exit 0
  fi
  if ! g cat-file -e "${sha}:.claude/skill-context.md" 2>/dev/null; then
    printf '(no .claude/skill-context.md on base %s %.12s in %s)\n' "$full" "$sha" "$root"
    exit 0
  fi
  printf '<!-- skill-context: %s (base %s %.12s) -->\n' "$root" "$full" "$sha"
  g show "${sha}:.claude/skill-context.md"
  exit 0
fi

if [ -f "$ctx" ]; then
  printf '<!-- skill-context: %s -->\n' "$root"
  cat -- "$ctx"
else
  printf '(no .claude/skill-context.md in %s)\n' "$root"
fi
