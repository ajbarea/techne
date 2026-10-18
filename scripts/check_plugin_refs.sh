#!/usr/bin/env bash
# Every ${CLAUDE_PLUGIN_ROOT}/<path>, <plugin-root>/<path> and <skill-dir>/<path> a plugin
# names must exist inside that plugin: a plugin installs alone, so a file that lives only in a
# sibling plugin is missing at runtime. Skill bodies use the <skill-dir> and <plugin-root>
# placeholders, which the agent resolves from the definition line under the skill's title;
# ${CLAUDE_SKILL_DIR} and ${CLAUDE_PLUGIN_ROOT} are substituted by Claude Code alone and reach
# other CLIs' shells as empty variables.
set -euo pipefail

cd "${PLUGINS_ROOT:-$(dirname "${BASH_SOURCE[0]}")/..}"
status=0

# Claude Code substitutes these variables only in SKILL.md, agent and command bodies; in any
# other Markdown file the model Reads they stay literal and the command breaks.
while IFS= read -r file; do
	case "$file" in
	*/skills/*/SKILL.md | */agents/*.md | */commands/*.md) continue ;;
	esac
	var=$(grep -ohE '\$\{?CLAUDE_(PLUGIN_ROOT|PLUGIN_DATA|SKILL_DIR)\b\}?' "$file" | head -1) || true
	if [ -n "$var" ]; then
		echo "FAIL: $file uses $var, which Claude Code substitutes only in SKILL.md, agent and command bodies"
		status=1
	fi
done < <(grep -rlE '\$\{?CLAUDE_(PLUGIN_ROOT|PLUGIN_DATA|SKILL_DIR)\b' plugins --include='*.md' \
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
# The plugins the docs say run in other agent CLIs. Elsewhere a skill that reads plugin options
# or the plugin data directory runs on Claude Code alone for now, so its variables stay.
PORTABLE=" techne graphe dokimasia "
skill_defs=("\`<skill-dir>\` is the directory holding this SKILL.md."
	"\`<skill-dir>\` is the directory holding this SKILL.md, and \`<plugin-root>\` is the plugin's root directory, two levels above it.")
root_defs=("\`<plugin-root>\` is the plugin's root directory, two levels above the directory holding this SKILL.md."
	"\`<skill-dir>\` is the directory holding this SKILL.md, and \`<plugin-root>\` is the plugin's root directory, two levels above it.")
claude_var='\$\{?CLAUDE_(PLUGIN_ROOT|SKILL_DIR)\b\}?'

# The placeholders are defined relative to a SKILL.md; in any other file they mean nothing.
while IFS= read -r file; do
	[ -n "$file" ] || continue
	echo "FAIL: $file uses <skill-dir> or <plugin-root>, which only a SKILL.md defines"
	status=1
done < <(grep -rlE '<(skill-dir|plugin-root)>' plugins --include='*.md' --exclude-dir=eval-fixtures \
	| grep -v '/skills/[^/]*/SKILL\.md$' || true)

while IFS= read -r skill; do
	[ -n "$skill" ] || continue
	dir=$(dirname "$skill")
	plugin=$(dirname "$(dirname "$dir")")
	name=$(basename "$plugin")
	exempt=0
	grep -qE '\$\{?(user_config\.|CLAUDE_PLUGIN_DATA\b)' "$skill" && exempt=1
	if [ "$exempt" -eq 1 ] && [[ $PORTABLE == *" $name "* ]]; then
		echo "FAIL: $skill reads plugin options or plugin data, which $name must not need: the docs say it runs in other agent CLIs"
		status=1
	fi
	if [ "$exempt" -eq 0 ]; then
		var=$(grep -ohE "$claude_var" "$skill" | head -1) || true
		if [ -n "$var" ]; then
			echo "FAIL: $skill uses $var, which only Claude Code substitutes; write <plugin-root> or <skill-dir>"
			status=1
		fi
	fi
	for placeholder in skill-dir plugin-root; do
		first_use=$(grep -nE "<$placeholder>" "$skill" | grep -vE "^[0-9]+:\`<(skill-dir|plugin-root)>\` is the " \
			| head -1 | cut -d: -f1) || true
		[ -n "$first_use" ] || continue
		if [ "$placeholder" = skill-dir ]; then
			def_line=$(grep -nxF -e "${skill_defs[0]}" -e "${skill_defs[1]}" "$skill" | head -1 | cut -d: -f1) || true
			base=$dir
		else
			def_line=$(grep -nxF -e "${root_defs[0]}" -e "${root_defs[1]}" "$skill" | head -1 | cut -d: -f1) || true
			base=$plugin
		fi
		if [ -z "$def_line" ]; then
			echo "FAIL: $skill uses <$placeholder> without defining it"
			status=1
		elif [ "$def_line" -gt "$first_use" ]; then
			echo "FAIL: $skill uses <$placeholder> on line $first_use, before its definition on line $def_line"
			status=1
		fi
		refs=$(grep -oE "<$placeholder>/[A-Za-z0-9_./-]+" "$skill" | sort -u) || true
		while IFS= read -r ref; do
			[ -n "$ref" ] || continue
			rel="${ref#"<$placeholder>/"}"
			rel=$(printf '%s' "$rel" | sed 's/\.*$//')
			if [[ /$rel/ == */../* ]]; then
				echo "FAIL: $skill names <$placeholder>/$rel, which climbs out of the path it names"
				status=1
			elif [ -n "$rel" ] && [ ! -e "$base/$rel" ]; then
				echo "FAIL: $skill names <$placeholder>/$rel, which $plugin does not ship"
				status=1
			fi
		done <<<"$refs"
	done
done < <(find plugins -path '*/eval-fixtures' -prune -o -path '*/skills/*/SKILL.md' -print | sort)

[ "$status" -eq 0 ] && echo "OK: every plugin path resolves inside its plugin"
exit "$status"
