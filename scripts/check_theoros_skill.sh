#!/bin/bash
# Structural validation for the techne:theoros skill.
# Exits non-zero with a specific message on the first failure.

set -euo pipefail

SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/plugins/techne/skills/theoros/SKILL.md"

# 1. File exists.
[[ -f "$SKILL" ]] || { printf 'FAIL: %s not found\n' "$SKILL" >&2; exit 1; }

# 2. Frontmatter present and complete.
head -1 "$SKILL" | grep -q '^---$' || { printf 'FAIL: missing opening frontmatter fence\n' >&2; exit 1; }
for field in 'name:' 'description:' 'disable-model-invocation:' 'allowed-tools:'; do
    head -20 "$SKILL" | grep -q "^${field}" || { printf "FAIL: frontmatter missing field: %s\n" "$field" >&2; exit 1; }
done

# 3. Description mentions key trigger words.
desc_line="$(awk '/^description:/{print; exit}' "$SKILL")"
for phrase in 'theoros' 'tmux' 'REPL' 'spectate'; do
    echo "$desc_line" | grep -qi "$phrase" || { printf "FAIL: description should mention '%s'\n" "$phrase" >&2; exit 1; }
done

# 4. Required body sections present.
for heading in '## Repo context' '## Required YAML fields' '## Lifecycle' '## Driving the REPL' '## Discipline rules' '## Scaffolding theoros into a new repo'; do
    grep -qF "$heading" "$SKILL" || { printf "FAIL: required section missing: %s\n" "$heading" >&2; exit 1; }
done

# 5. README mentions the theoros skill bullet.
README="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/README.md"
grep -qF '`techne:theoros`' "$README" || { printf 'FAIL: techne README missing theoros bullet\n' >&2; exit 1; }
grep -qiF 'tmux attach' "$README" || { printf 'FAIL: techne README bullet should mention tmux attach\n' >&2; exit 1; }

printf 'OK: techne:theoros SKILL.md passes structural checks\n'
