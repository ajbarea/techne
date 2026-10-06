import type { PluginOptions, Register } from 'claude-code'

// The guard options, as the manifest's userConfig names them.
const GUARDS = ['block_attribution_trailers', 'block_commits_md', 'warn_main_checkout_commit'] as const
// The guards that refuse a command; warn_main_checkout_commit only warns.
const BLOCKING = ['block_attribution_trailers', 'block_commits_md'] as const
// git_guards.py looks no further at a command without one of these words.
const GIT_OR_GH = /\b(git|gh)\b/
// A commit makes at most six git calls of 5 s each inside git_guards.py.
const GUARD_TIMEOUT_MS = 40_000

type Verdict = { deny?: string; warning?: string }

const isOn = (options: PluginOptions, key: string): boolean => options[key] === true

// Reads git_guards.py's PreToolUse JSON: a deny reason, or a warning for the model.
export function readVerdict(stdout: string): Verdict {
  if (stdout.trim() === '') return {}
  const out = JSON.parse(stdout) as {
    hookSpecificOutput?: { permissionDecision?: string; permissionDecisionReason?: string; additionalContext?: string }
  }
  const spec = out.hookSpecificOutput ?? {}
  if (spec.permissionDecision === 'deny') return { deny: spec.permissionDecisionReason ?? 'phylax refused this command.' }
  if (spec.additionalContext) return { warning: spec.additionalContext }
  return {}
}

export const register: Register = (on, options) => {
  // Claude Code reads the commit trailer and PR footer from here, so blanking them stops the
  // lines before Claude writes them; the Bash guard below still catches one written by hand.
  if (isOn(options, 'block_attribution_trailers')) {
    on('attribution.text', { kind: ['commit', 'pr'] }, () => ({ text: '' }))
  }

  if (!GUARDS.some(key => isOn(options, key))) return
  const blocking = BLOCKING.some(key => isOn(options, key))
  const failed = (why: string) => ({
    deny:
      `phylax: the git guard ${why}, so this command was not run. Retry it in a simpler form, ` +
      'or switch the guard off in /config.',
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    // A subagent's call goes to the hooks.json PreToolUse fallback, which gets its own cwd;
    // $.session.cwd() is the main thread's.
    if (e.agentId !== undefined || !GIT_OR_GH.test(e.command)) return next(e)
    // The fallback runs inside next(e): this tells it the call was checked here.
    await $.env.set('PHYLAX_GUARD_SESSION', await $.session.id())
    const cwd = await $.session.cwd()
    const run = await $.process.run(['python3', `${$.plugin.root}/hooks/git_guards.py`], {
      cwd,
      stdin: JSON.stringify({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: e.command }, cwd }),
      env: Object.fromEntries(GUARDS.map(key => [`CLAUDE_PLUGIN_OPTION_${key.toUpperCase()}`, String(isOn(options, key))])),
      timeoutMs: GUARD_TIMEOUT_MS,
    })
    const verdict = readVerdict(run.stdout)
    if (verdict.deny !== undefined) return { deny: verdict.deny }
    if (run.exitCode !== 0) {
      const reason = run.stderr.trim().split('\n')[0] || `exit ${run.exitCode}`
      if (blocking) return failed(`failed (${reason})`)
      $.ui.log(`phylax: the git guard failed (${reason}); the command ran unchecked.`)
    }
    const result = await next(e)
    if (verdict.warning === undefined || result.deny !== undefined) return result
    $.ui.log(verdict.warning)
    return { ...result, context: [...(result.context ?? []), verdict.warning] }
  }).catch(($, e, next) => {
    if (next.called || !blocking) return next(e)
    return failed(`failed (${next.error.message})`)
  })
}
