#!/usr/bin/env bash
# Print .claude/skill-context.md from the repo that owns TARGET, headed by the repo root.
# Usage: skill_context.sh [--base=BASE [--head=HEAD] [--file=PATH] | --base-sha=BASE [--head=HEAD]] [target]
# TARGET is a file or directory, and need not exist yet: it resolves from its
# nearest existing parent. A bare word (PR number, branch, effort level) has
# none, so it resolves to the current directory's repo.
# --base prints the file as committed on BASE instead of the working tree's, so a
# change under review cannot edit the hints that judge it (--file names another path
# to read from the base the same way). BASE and HEAD are full commit ids, nothing
# else: the default branch's commit from the host and the reviewed commit (see
# elenchus's SKILL.md). A ref name is
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
read_path=.claude/skill-context.md
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base_mode=-1 ;;
    --base-sha) base_mode=-3 ;;
    --base=*) base_mode=1; base_ref=${1#--base=} ;;
    --base-sha=*) base_mode=2; base_ref=${1#--base-sha=} ;;
    --head=*) head_ref=${1#--head=}; head_given=1; [ "$base_mode" -ne 0 ] || base_mode=-2 ;;
    --file=*) read_path=${1#--file=}; [ "$base_mode" -ne 0 ] || base_mode=-4 ;;
    *) break ;;
  esac
  shift
done
for a in "$@"; do
  case "$a" in
    --base* | --head* | --file*) printf '(%s must come before the target; nothing read)\n' "$a"; exit 0 ;;
  esac
done
case "$base_mode" in
  -1) printf '(--base needs a full commit id: --base=<base id>; nothing read)\n'; exit 0 ;;
  -3) printf -- '--base-sha needs a full commit id: --base-sha=<base id>\n' >&2; exit 1 ;;
  -2) printf '(--head works only with --base; nothing read)\n'; exit 0 ;;
  -4) printf '(--file works only with --base; nothing read)\n'; exit 0 ;;
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
  # Strip what git says points it at another repository, keeping injected config
  # (GIT_CONFIG*: a container's safe.directory), as _shared/git_env.py does.
  strip=()
  while IFS= read -r v; do
    case "$v" in "" | GIT_CONFIG | GIT_CONFIG_PARAMETERS | GIT_CONFIG_COUNT) ;; *) strip+=(-u "$v") ;; esac
  done < <(env -u GIT_DIR -u GIT_WORK_TREE git rev-parse --local-env-vars 2>/dev/null)
  # A replacement object would let a local ref swap the base's content under its own id,
  # and a graft would bend the history the ancestry checks read, so every read runs with
  # both off. ${strip[@]+...}: bash 3.2 (macOS) treats an empty array as unset under set -u.
  g() {
    env -u GIT_DIR -u GIT_WORK_TREE ${strip[@]+"${strip[@]}"} GIT_NO_REPLACE_OBJECTS=1 \
      GIT_GRAFT_FILE=/nonexistent-elenchus-graft git -C "$root" "$@"
  }
  why="" r_sha=""
  err=$(g rev-parse --git-dir 2>&1 >/dev/null) || why="$root is not a git repository git can read (${err%%$'\n'*})"
  hexlen=40
  [ -n "$why" ] || [ "$(g rev-parse --show-object-format 2>/dev/null)" != sha256 ] || hexlen=64
  # commit ID: set r_sha when ID is a full id of a commit in this repo, else why.
  commit() {
    r_sha=""
    if ! [[ $1 =~ ^[0-9a-f]+$ && ${#1} -eq $hexlen ]]; then
      why="'$1' is not a full commit id: the base is the default branch's (gh api repos/{owner}/{repo}/commits/HEAD --jq .sha), the head the PR's headRefOid"
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
    if [ "$head_given" -eq 1 ]; then
      why="base ${sha:0:12} holds the commit under review ${head:0:12}: the base is the default branch's commit, the head the PR's headRefOid"
    else
      why="base ${sha:0:12} holds this checkout's HEAD ${head:0:12}: check out the change, or pass --head=<headRefOid>"
    fi
  elif [ -z "$why" ] && ! g merge-base "$sha" "$head" >/dev/null 2>&1; then
    # A shallow clone can hide that the base already holds the head: unproven is refused.
    why="base ${sha:0:12} and head ${head:0:12} share no history here: git fetch --unshallow, then run it again"
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
  case "$read_path" in
    /* | *..* | *:* | -*) printf '(--file=%s: give a plain path inside the repo; nothing read)\n' "$read_path"; exit 0 ;;
  esac
  if [ "$(g cat-file -t "${sha}:${read_path}" 2>/dev/null)" = tree ]; then
    printf '(%s is a folder on base %s, not a file; nothing read)\n' "$read_path" "$sha"
    exit 0
  fi
  if [ -z "$(g ls-tree --name-only "$sha" -- "$read_path" 2>/dev/null)" ]; then
    printf '(no %s on base %s in %s)\n' "$read_path" "$sha" "$root"
    exit 0
  fi
  if [ "$read_path" = .claude/skill-context.md ]; then
    printf '<!-- skill-context: %s (base %s) -->\n' "$root" "$sha"
  else
    printf '<!-- %s at base %s in %s -->\n' "$read_path" "$sha" "$root"
  fi
  g show "${sha}:${read_path}" 2>/dev/null \
    || printf '(%s is on base %s but could not be read: git fetch origin %s)\n' "$read_path" "$sha" "$sha"
  exit 0
fi

if [ -f "$ctx" ]; then
  printf '<!-- skill-context: %s -->\n' "$root"
  cat -- "$ctx"
else
  printf '(no .claude/skill-context.md in %s)\n' "$root"
fi
