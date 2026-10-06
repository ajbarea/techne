import { describe, expect, test } from 'claude-code/testing'
import type { On, ProcessRunInit, ProcessRunResult } from 'claude-code'

const ATTRIBUTION = { block_attribution_trailers: true }
const COMMITS_MD = { block_commits_md: true }
const WARN_ONLY = { warn_main_checkout_commit: true }
const CWD = '/work/repo'

const DENY = JSON.stringify({
  hookSpecificOutput: {
    hookEventName: 'PreToolUse',
    permissionDecision: 'deny',
    permissionDecisionReason: 'phylax: this commit message carries an attribution line.',
  },
})
const WARNING = JSON.stringify({
  systemMessage: 'phylax: committing in the main checkout',
  hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: 'phylax: committing in the main checkout' },
})

type Guard = Partial<ProcessRunResult> | Error

// Stands in for the engine: the session's directory, python3 running git_guards.py, and Bash.
function engine(on: On, guard: Guard) {
  const runs: { argv: readonly string[]; init?: ProcessRunInit }[] = []
  const bash: string[] = []
  // Every write of the stamp, and what it held when Bash ran (where the fallback reads it).
  const stamps: (string | undefined)[] = []
  let stamp: string | undefined
  const stampAtRun: (string | undefined)[] = []
  on('session.cwd', () => ({ value: CWD }))
  on('env.set', ($, e) => {
    if (e.name === 'PHYLAX_GUARD_CHECKED') {
      stamps.push(e.value)
      stamp = e.value
    }
    return { value: undefined }
  })
  on('process.run', ($, e) => {
    runs.push(e)
    // A deny rejects the caller's $.process.run, as a python3 that cannot start does.
    if (guard instanceof Error) return { deny: guard.message }
    return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false, ...guard } }
  })
  on('tool.call', { tool: 'Bash' }, ($, e) => {
    bash.push(e.command)
    stampAtRun.push(stamp)
    return { result: { stdout: 'ran', stderr: '', interrupted: false }, text: 'ran' }
  })
  return { runs, bash, stamps, stampAtRun }
}

describe('attribution text', () => {
  test('commit and PR attribution are blanked at the source', { options: ATTRIBUTION }, async ($, on) => {
    on('attribution.text', ($, e) => ({ text: e.text }))
    expect((await $.attribution.text({ kind: 'commit', text: 'Co-Authored-By: Claude' })).text).toBe('')
    expect((await $.attribution.text({ kind: 'pr', text: 'Generated with Claude Code' })).text).toBe('')
    expect((await $.attribution.text({ kind: 'remedy', text: 'kept' })).text).toBe('kept')
  })

  test('the option off leaves attribution to the settings', { options: COMMITS_MD }, async ($, on) => {
    on('attribution.text', ($, e) => ({ text: e.text }))
    expect((await $.attribution.text({ kind: 'commit', text: 'trailer' })).text).toBe('trailer')
  })
})

describe('git guard', () => {
  test('a deny from the guard refuses the command', { options: ATTRIBUTION }, async ($, on) => {
    const { runs, bash } = engine(on, { stdout: DENY })
    const out = await $.tool.call({ tool: 'Bash', command: "git commit -m 'x'" })
    expect(out.deny).toContain('attribution line')
    expect(bash).toEqual([])
    expect(runs).toHaveLength(1)
  })

  test('the guard gets the command, the cwd and every option', { options: COMMITS_MD }, async ($, on) => {
    const { runs } = engine(on, {})
    await $.tool.call({ tool: 'Bash', command: 'git add .' })
    const { argv, init } = runs[0]!
    expect(argv[0]).toBe('python3')
    expect(argv[1]).toMatch(/hooks\/git_guards\.py$/)
    expect(init?.cwd).toBe(CWD)
    expect(JSON.parse(init?.stdin ?? '{}')).toEqual({
      hook_event_name: 'PreToolUse',
      tool_name: 'Bash',
      tool_input: { command: 'git add .' },
      cwd: CWD,
    })
    expect(init?.env).toEqual({
      CLAUDE_PLUGIN_OPTION_BLOCK_ATTRIBUTION_TRAILERS: 'false',
      CLAUDE_PLUGIN_OPTION_BLOCK_COMMITS_MD: 'true',
      CLAUDE_PLUGIN_OPTION_WARN_MAIN_CHECKOUT_COMMIT: 'false',
    })
  })

  test('a command with no git or gh never starts python3', { options: ATTRIBUTION }, async ($, on) => {
    const { runs, bash } = engine(on, { stdout: DENY })
    const out = await $.tool.call({ tool: 'Bash', command: 'ls -la' })
    expect(out.deny).toBeUndefined()
    expect(runs).toEqual([])
    expect(bash).toEqual(['ls -la'])
  })

  test('a clean verdict lets the command run', { options: ATTRIBUTION }, async ($, on) => {
    const { bash } = engine(on, {})
    const out = await $.tool.call({ tool: 'Bash', command: 'time git status' })
    expect(out.deny).toBeUndefined()
    expect(bash).toEqual(['time git status'])
  })

  test('a warning runs the command and reaches the model', { options: WARN_ONLY }, async ($, on) => {
    const { bash } = engine(on, { stdout: WARNING })
    const out = await $.tool.call({ tool: 'Bash', command: 'git commit -m x' })
    expect(bash).toEqual(['git commit -m x'])
    expect(out.context).toEqual(['phylax: committing in the main checkout'])
  })

  test('a guard that fails refuses while a blocking guard is on', { options: COMMITS_MD }, async ($, on) => {
    const { bash } = engine(on, { exitCode: 1, stderr: 'phylax git guard error: boom' })
    const out = await $.tool.call({ tool: 'Bash', command: 'git add .' })
    expect(out.deny).toContain('phylax git guard error: boom')
    expect(bash).toEqual([])
  })

  test('a guard that cannot start refuses while a blocking guard is on', { options: ATTRIBUTION }, async ($, on) => {
    const { bash } = engine(on, new Error('spawn python3 ENOENT'))
    const out = await $.tool.call({ tool: 'Bash', command: 'git commit -m x' })
    expect(out.deny).toContain('spawn python3 ENOENT')
    expect(bash).toEqual([])
  })

  test('a failed guard lets the command run when only the warning is on', { options: WARN_ONLY }, async ($, on) => {
    const { bash } = engine(on, { exitCode: 1, stderr: 'boom' })
    const out = await $.tool.call({ tool: 'Bash', command: 'git commit -m x' })
    expect(out.deny).toBeUndefined()
    expect(bash).toEqual(['git commit -m x'])
  })

  test('with every guard off nothing is checked', async ($, on) => {
    const { runs, bash } = engine(on, { stdout: DENY })
    const out = await $.tool.call({ tool: 'Bash', command: "git commit -m 'x'" })
    expect(out.deny).toBeUndefined()
    expect(runs).toEqual([])
    expect(bash).toEqual(["git commit -m 'x'"])
  })

  test('a passed call is named for the fallback while it runs, then cleared', { options: ATTRIBUTION }, async ($, on) => {
    const { stamps, stampAtRun, bash } = engine(on, {})
    await $.tool.call({ tool: 'Bash', command: 'git status', tool_use_id: 'toolu_1' })
    expect(bash).toEqual(['git status'])
    expect(stampAtRun).toEqual(['toolu_1'])
    expect(stamps).toEqual(['toolu_1', undefined])
  })

  test('a refused call names nothing', { options: ATTRIBUTION }, async ($, on) => {
    const { stamps } = engine(on, { stdout: DENY })
    await $.tool.call({ tool: 'Bash', command: "git commit -m 'x'", tool_use_id: 'toolu_2' })
    expect(stamps).toEqual([])
  })

  test("a subagent's call is left to the hooks.json fallback", { options: ATTRIBUTION }, async ($, on) => {
    const { runs, stamps, bash } = engine(on, { stdout: DENY })
    // The engine stamps agentId on a subagent's call; the test stands in for it.
    const subagentCall = { tool: 'Bash', command: "git commit -m 'x'", agentId: 'agent-7' }
    const out = await $.tool.call(subagentCall as Parameters<typeof $.tool.call>[0])
    expect(out.deny).toBeUndefined()
    expect(runs).toEqual([])
    expect(stamps).toEqual([])
    expect(bash).toEqual(["git commit -m 'x'"])
  })

  test('a failed check beside a warning still refuses', { options: { ...COMMITS_MD, ...WARN_ONLY } }, async ($, on) => {
    const { bash } = engine(on, { exitCode: 2, stdout: WARNING, stderr: 'phylax git guard error: x\nphylax: could not finish' })
    const out = await $.tool.call({ tool: 'Bash', command: 'git commit -m x' })
    expect(out.deny).toContain('phylax git guard error: x')
    expect(bash).toEqual([])
  })

  test('output the mod cannot read refuses while a blocking guard is on', { options: COMMITS_MD }, async ($, on) => {
    const { bash } = engine(on, { stdout: '{"hookSpecificOutput": ' })
    const out = await $.tool.call({ tool: 'Bash', command: 'git add .' })
    expect(out.deny).toContain('phylax: the git guard failed')
    expect(bash).toEqual([])
  })
})
