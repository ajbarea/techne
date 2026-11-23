#!/usr/bin/env bash
# Print .claude/skill-context.md from the repo that owns TARGET, headed by the repo root.
# Usage: skill_context.sh [--base[=BASE] | --base-sha[=BASE]] [--head=HEAD] [target]
# TARGET is a file or directory, and need not exist yet: it resolves from its
# nearest existing parent. A bare word (PR number, branch, effort level) has
# none, so it resolves to the current directory's repo.
# --base prints the file as committed on the base instead of the working tree's, so
# a change under review cannot edit the hints that judge it. BASE is a full commit id
# (a PR's baseRefOid), a full ref (refs/remotes/origin/main), or a short name found as
# exactly one of refs/remotes/NAME, refs/heads/NAME, refs/tags/NAME; anything else
# (an expression, FETCH_HEAD, a short id) is refused. No BASE: the remote's default
# branch (refs/remotes/origin/HEAD, else refs/remotes/origin/main). HEAD (default:
# the checkout's HEAD; a PR's headRefOid) is the commit under review: a base that
# is HEAD or contains it is refused, since it is the change itself. Nothing stands
# in for a refused or missing base or file.
# --base-sha prints only "<base> <base commit> <head commit>", or a reason on
# stderr and exit 1 (elenchus's own_checks.py resolves through it).
set -u

base_mode=0
base_ref=""
head_ref=""
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base_mode=1 ;;
    --base=*) base_mode=1; base_ref=${1#--base=} ;;
    --base-sha) base_mode=2 ;;
    --base-sha=*) base_mode=2; base_ref=${1#--base-sha=} ;;
    --head=*) head_ref=${1#--head=} ;;
    *) break ;;
  esac
  shift
done
for a in "$@"; do
  case "$a" in
    --base* | --head*) printf '(%s must come before the target; nothing read)\n' "$a"; exit 0 ;;
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
  # resolve NAME: set r_full and r_sha, or why when NAME is not exactly one commit id or
  # ref. It runs in this shell (never in $(...)), so why reaches the caller.
  resolve() {
    local name=$1 full="" kind hash
    r_full="" r_sha=""
    if [[ $name =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]]; then
      hash=$(g rev-parse -q --verify --end-of-options "${name}^{commit}" 2>/dev/null) \
        || { why="$name is not a commit in $root: git fetch it"; return; }
      r_full=$name r_sha=$hash
      return
    fi
    if [[ $name == refs/* ]]; then
      full=$name
    else
      for kind in remotes heads tags; do
        g show-ref --verify -q "refs/$kind/$name" || continue
        [ -z "$full" ] || { why="$name is ambiguous ($full and refs/$kind/$name): pass the full name"; return; }
        full="refs/$kind/$name"
      done
      [ -n "$full" ] || { why="$name is not a ref in $root: git fetch it, or pass a full commit id"; return; }
    fi
    hash=$(g show-ref --verify --hash "$full" 2>/dev/null) \
      || { why="$full not found in $root: git fetch +refs/heads/<branch>:$full, or pass a full commit id"; return; }
    hash=$(g rev-parse -q --verify "${hash}^{commit}" 2>/dev/null) \
      || { why="$full is not a commit"; return; }
    r_full=$full r_sha=$hash
  }
  why=""
  if [ -z "$base_ref" ]; then
    base_ref=$(g symbolic-ref -q refs/remotes/origin/HEAD 2>/dev/null) || base_ref=refs/remotes/origin/main
  fi
  resolve "$base_ref"
  full=$r_full sha=$r_sha head=""
  if [ -z "$why" ]; then
    if [ -n "$head_ref" ]; then
      resolve "$head_ref"
      head=$r_sha
    else
      head=$(g rev-parse -q --verify HEAD 2>/dev/null) || why="no HEAD in $root: pass --head=<the reviewed commit>"
    fi
  fi
  # The base must not hold the change: a single-branch clone of the PR points origin/HEAD
  # at it, and a checkout standing on the base reviews nothing.
  if [ -z "$why" ] && g merge-base --is-ancestor "$head" "$sha" 2>/dev/null; then
    why="base $full holds the commit under review ${head:0:12}: pass --base=<baseRefOid> --head=<headRefOid>"
  fi
  if [ -n "$why" ]; then
    [ "$base_mode" -eq 2 ] && { printf '%s\n' "$why" >&2; exit 1; }
    printf '(%s)\n' "$why"
    exit 0
  fi
  if [ "$base_mode" -eq 2 ]; then
    printf '%s %s %s\n' "$full" "$sha" "$head"
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
