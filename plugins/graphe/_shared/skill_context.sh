#!/usr/bin/env bash
# Print .claude/skill-context.md from the repo that owns TARGET, headed by the repo root.
# Usage: skill_context.sh [--base=BASE [--head=HEAD] | --base-sha=BASE [--head=HEAD]] [target]
# TARGET is a file or directory, and need not exist yet: it resolves from its
# nearest existing parent. A bare word (PR number, branch, effort level) has
# none, so it resolves to the current directory's repo.
# --base prints the file as committed on BASE instead of the working tree's, so a
# change under review cannot edit the hints that judge it. BASE and HEAD are full
# commit ids, nothing else: a PR's baseRefOid and headRefOid, or before a PR the
# default branch's commit from the host (see elenchus's SKILL.md). A ref name is
# refused, since a local ref can be the change wearing the base's name. HEAD
# defaults to the checkout's HEAD. A base that is HEAD or contains it is refused.
# Nothing stands in for a refused or missing base or file.
# --base-sha prints only "<base commit> <head commit>", or a reason on stderr and
# exit 1 (elenchus's own_checks.py resolves through it).
set -u

base_mode=0
base_ref=""
head_ref=""
head_given=0
while [ $# -gt 0 ]; do
  case "$1" in
    --base | --base-sha) base_mode=-1 ;;
    --base=*) base_mode=1; base_ref=${1#--base=} ;;
    --base-sha=*) base_mode=2; base_ref=${1#--base-sha=} ;;
    --head=*) head_ref=${1#--head=}; head_given=1; [ "$base_mode" -ne 0 ] || base_mode=-2 ;;
    *) break ;;
  esac
  shift
done
for a in "$@"; do
  case "$a" in
    --base* | --head*) printf '(%s must come before the target; nothing read)\n' "$a"; exit 0 ;;
  esac
done
case "$base_mode" in
  -1) printf '(--base needs a full commit id: --base=<baseRefOid>; nothing read)\n'; exit 0 ;;
  -2) printf '(--head works only with --base; nothing read)\n'; exit 0 ;;
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

if [ "$base_mode" -ne 0 ]; then
  # Strip every variable git says points it at another repository, not only GIT_DIR.
  strip=()
  while IFS= read -r v; do strip+=(-u "$v"); done < <(env -u GIT_DIR -u GIT_WORK_TREE git rev-parse --local-env-vars 2>/dev/null)
  # ${strip[@]+...}: bash 3.2 (macOS) treats an empty array as unset under set -u.
  g() { env -u GIT_DIR -u GIT_WORK_TREE ${strip[@]+"${strip[@]}"} git -C "$root" "$@"; }
  why="" r_sha=""
  g rev-parse --git-dir >/dev/null 2>&1 || why="$root is not in a git repository"
  hexlen=40
  [ -n "$why" ] || [ "$(g rev-parse --show-object-format 2>/dev/null)" != sha256 ] || hexlen=64
  # commit ID: set r_sha when ID is a full id of a commit in this repo, else why.
  commit() {
    r_sha=""
    if ! [[ $1 =~ ^[0-9a-f]+$ && ${#1} -eq $hexlen ]]; then
      why="'$1' is not a full commit id: pass a PR's baseRefOid and headRefOid (gh pr view <N> --json baseRefOid,headRefOid)"
      return
    fi
    r_sha=$(g rev-parse -q --verify --end-of-options "${1}^{commit}" 2>/dev/null)
    if [ "$r_sha" != "$1" ]; then
      r_sha=""
      why="$1 is not a commit in $root: git fetch origin $1"
    fi
  }
  [ -n "$why" ] || commit "$base_ref"
  sha=$r_sha head=""
  if [ -z "$why" ]; then
    if [ "$head_given" -eq 1 ]; then
      commit "$head_ref"
      head=$r_sha
    else
      head=$(g rev-parse -q --verify HEAD 2>/dev/null) || why="no HEAD in $root: pass --head=<headRefOid>"
    fi
  fi
  # The base must not hold the change (a base at or past the reviewed commit).
  if [ -z "$why" ] && g merge-base --is-ancestor "$head" "$sha" 2>/dev/null; then
    why="base ${sha:0:12} holds the commit under review ${head:0:12}: pass --base=<baseRefOid> --head=<headRefOid>"
  fi
  if [ -n "$why" ]; then
    [ "$base_mode" -eq 2 ] && { printf '%s\n' "$why" >&2; exit 1; }
    printf '(%s)\n' "$why"
    exit 0
  fi
  if [ "$base_mode" -eq 2 ]; then
    printf '%s %s\n' "$sha" "$head"
    exit 0
  fi
  if ! g cat-file -e "${sha}:.claude/skill-context.md" 2>/dev/null; then
    printf '(no .claude/skill-context.md on base %s in %s)\n' "$sha" "$root"
    exit 0
  fi
  printf '<!-- skill-context: %s (base %s) -->\n' "$root" "$sha"
  g show "${sha}:.claude/skill-context.md"
  exit 0
fi

if [ -f "$ctx" ]; then
  printf '<!-- skill-context: %s -->\n' "$root"
  cat -- "$ctx"
else
  printf '(no .claude/skill-context.md in %s)\n' "$root"
fi
