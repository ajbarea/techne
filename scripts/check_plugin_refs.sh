#!/usr/bin/env bash
# Every ${CLAUDE_PLUGIN_ROOT}/<path>, <plugin-root>/<path> and <skill-dir>/<path> a plugin
# names must exist inside that plugin: a plugin installs alone, so a file that lives only in a
# sibling plugin is missing at runtime. Skill bodies use the <skill-dir> and <plugin-root>
# placeholders, which every agent CLI resolves; ${CLAUDE_SKILL_DIR} and ${CLAUDE_PLUGIN_ROOT}
# are substituted by Claude Code alone and reach other CLIs' shells as empty variables.
set -euo pipefail

cd "${PLUGINS_ROOT:-$(dirname "${BASH_SOURCE[0]}")/..}"
status=0

# Claude Code substitutes these variables only in SKILL.md, agent and command bodies; in any
# other Markdown file the model Reads they stay literal and the command breaks.
while IFS= read -r file; do
	case "$file" in
	*/skills/*/SKILL.md | */agents/*.md | */commands/*.md) continue ;;
	esac
	var=$(grep -ohE '\$\{CLAUDE_(PLUGIN_ROOT|PLUGIN_DATA|SKILL_DIR)\}' "$file" | head -1)
	if [ -n "$var" ]; then
		echo "FAIL: $file uses $var, which Claude Code substitutes only in SKILL.md, agent and command bodies"
		status=1
	fi
done < <(grep -rlE '\$\{CLAUDE_(PLUGIN_ROOT|PLUGIN_DATA|SKILL_DIR)\}' plugins --include='*.md' \
	--exclude-dir=eval-fixtures || true)

for plugin in plugins/*/; do
	plugin="${plugin%/}"
	refs=$(grep -rhoE '\$\{CLAUDE_PLUGIN_ROOT\}/[A-Za-z0-9_./-]+' "$plugin" \
		--include='*.md' --include='*.json' --include='*.sh' --include='*.py' \
		--exclude-dir=eval-fixtures | sort -u) || true
	while IFS= read -r ref; do
		[ -n "$ref" ] || continue
		rel="${ref#'${CLAUDE_PLUGIN_ROOT}/'}"
		rel="${rel%.}"
		if [ ! -e "$plugin/$rel" ]; then
			echo "FAIL: $plugin names \${CLAUDE_PLUGIN_ROOT}/$rel, which it does not ship"
			status=1
		fi
	done <<<"$refs"
done
# A skill that reads plugin options or the plugin data directory runs on Claude Code alone
# for now, so its variables stay.
skill_def='`<skill-dir>` is the directory holding this SKILL.md'
root_def='`<plugin-root>` is the plugin'"'"'s root directory'
while IFS= read -r skill; do
	[ -n "$skill" ] || continue
	dir=$(dirname "$skill")
	plugin=$(dirname "$(dirname "$dir")")
	if ! grep -qE '\$\{(user_config\.|CLAUDE_PLUGIN_DATA\})' "$skill"; then
		var=$(grep -ohE '\$\{CLAUDE_(PLUGIN_ROOT|SKILL_DIR)\}' "$skill" | head -1) || true
		if [ -n "$var" ]; then
			echo "FAIL: $skill uses $var, which only Claude Code substitutes; write <plugin-root> or <skill-dir>"
			status=1
		fi
	fi
	for pair in "skill-dir|$dir|$skill_def" "plugin-root|$plugin|$root_def"; do
		IFS='|' read -r name base def <<<"$pair"
		refs=$(grep -oE "<$name>(/[A-Za-z0-9_./-]+)?" "$skill" | sort -u) || true
		[ -n "$refs" ] || continue
		if ! grep -qF -- "$def" "$skill"; then
			echo "FAIL: $skill uses <$name> without defining it"
			status=1
		fi
		while IFS= read -r ref; do
			rel="${ref#"<$name>"}"
			rel="${rel#/}"
			rel="${rel%.}"
			if [ -n "$rel" ] && [ ! -e "$base/$rel" ]; then
				echo "FAIL: $skill names <$name>/$rel, which $plugin does not ship"
				status=1
			fi
		done <<<"$refs"
	done
done < <(find plugins -path '*/eval-fixtures' -prune -o -path '*/skills/*/SKILL.md' -print | sort)

[ "$status" -eq 0 ] && echo "OK: every plugin path resolves inside its plugin"
exit "$status"
