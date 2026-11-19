#!/bin/sh
# Sourced by the Bash and run_command hooks (hooks.json) when python3 cannot check the call:
# it is not on PATH, or it exited with a code git_guards.py never gives (not 0 or 2: a stub
# python3, a crash before the guard's own handler, a kill), named in $phylax_rc. Sourced, it
# runs in the hook's own shell and its exit ends the hook.
#
# It refuses (exit 2) a command a guard that is on might refuse: one that names `git` or `gh`
# as a word while a blocking git guard is on, or holds a shape word while a shape guard is on.
# Any other command runs (exit 0), and the warning guard alone never refuses.
#
# Only the commands' text is checked, never the folder or transcript path beside it. A JSON
# string is a regular language, so the grep below finds every "command" (Claude Code) or
# "CommandLine" (Antigravity) value exactly; the key names hold none of the words. When it
# finds none (or grep is missing), the whole input is checked. A `\u` escape may spell any
# letter, so it refuses. A python3 that read the input before it failed leaves none: then
# every call is refused while a refusing guard is on.

p=$(cat)
c=$(printf '%s\n' "$p" | grep -o -E '"(command|CommandLine)"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"' 2>/dev/null)
[ -n "$c" ] || c=$p
if [ -n "${phylax_rc:-}" ]; then
	why="python3 failed (exit $phylax_rc)"
else
	why="python3 is not on PATH"
fi

refuse() {
	echo "phylax: $why, so the $1 cannot check this command; it was not run. Fix python3, or turn off the phylax option $2 in /config, or run /phylax:setup." >&2
	exit 2
}

# Appends the option name $2 to $names when its value $1 is "true".
add() {
	if [ "$1" = true ]; then names="${names:+$names, }$2"; fi
}

names=
add "${CLAUDE_PLUGIN_OPTION_BLOCK_BACKGROUND_LOOPS:-}" block_background_loops
add "${CLAUDE_PLUGIN_OPTION_BLOCK_PKILL_FULL:-}" block_pkill_full
if [ -n "$names" ]; then
	case "$c" in
	"" | *pkill* | *pgrep* | *while* | *until* | *"(("* | *\\u*) refuse "shape guards" "$names" ;;
	esac
fi
names=
add "${CLAUDE_PLUGIN_OPTION_BLOCK_ATTRIBUTION_TRAILERS:-}" block_attribution_trailers
add "${CLAUDE_PLUGIN_OPTION_BLOCK_COMMITS_MD:-}" block_commits_md
add "${CLAUDE_PLUGIN_OPTION_BLOCK_SECRETS:-}" block_secrets
add "${CLAUDE_PLUGIN_OPTION_BLOCK_LONG_BODIES:-}" block_long_bodies
if [ -n "$names" ]; then
	# git or gh as a word, close to git_guards.py's \b(git|gh)\b on the decoded command: JSON
	# writes a newline, tab or return before it as \n, \t or \r, so those count as a break.
	# A \f or \b escape does not, which only matters where bash would not split the word either.
	w='[!A-Za-z0-9_]'
	case " $c " in
	"  " | *${w}git${w}* | *${w}gh${w}* | *\\[ntr]git${w}* | *\\[ntr]gh${w}* | *\\u*)
		refuse "git guards" "$names"
		;;
	esac
fi
exit 0
