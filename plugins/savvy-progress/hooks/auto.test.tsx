import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

// Local change: helpers started with no reported plan raise the band by themselves.
const BAND = { component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 100 } as never } as const

async function session($: Engine, on: On) {
  mock.clock(on, { now: Date.parse('2026-10-10T02:00:00Z') })
  mock.env(on, { LANG: 'en_US.UTF-8' })
  on('settings.read', async () => ({ value: {} }) as never)
  on('session.start', async () => ({ cwd: '/repo' }) as never)
  on('tool.call', async () => ({ result: {} }) as never)
  on('turn.complete', async (_: unknown, e: { answer: string }) => ({ text: e.answer }) as never)
  let n = 0
  on('agent.spawn', async () => ({ model: 'claude-haiku-5-5', agentId: `a${++n}` }) as never)
  // Stands for whatever draws beneath the band (ribbon, or the engine).
  on('ui.render', (($: Engine, e: never) => {
    const { Text } = ($ as any).ui.resolve(e)
    return <Text>beneath</Text>
  }) as never)
  await $.session.start({ source: 'startup', cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
}

const spawn = ($: Engine, description: string) =>
  $.agent.spawn({ prompt: 'do it', description, subagentType: 'general-purpose' } as never)

const finish = ($: Engine, agentId: string) =>
  $.turn.complete({ answer: 'ok', durationMs: 1, isAborted: false, reason: 'answer', turnId: `t-${agentId}`, agentId } as never)

async function label($: Engine): Promise<string | null> {
  const ui = await $.ui.mount({ plugin: 'savvy-progress', surface: 'terminal', ...BAND })
  const title = await ui.findAll({ type: 'Text', text: /^Helpers at work$/ })
  const texts = await ui.findAll({ type: 'Text', text: /^(Tasks \d+\/\d+|done|finished)$/i })
  await ui.unmount()
  return title.length === 0 ? null : (texts[0]?.text ?? '')
}

test('plain helpers raise the band, one task each, and it reads done when they finish', async ($, on) => {
  await session($, on)
  expect(await label($)).toBeNull()

  await spawn($, 'Write emails')
  await spawn($, 'Write ads')
  expect(await label($)).toBe('Tasks 0/2')

  await finish($, 'a1')
  expect(await label($)).toBe('Tasks 1/2')

  await finish($, 'a2')
  expect((await label($))?.toLowerCase()).toMatch(/done|finished/)
})

test('a reported plan replaces the automatic band and is not overwritten by helpers', async ($, on) => {
  await session($, on)
  await spawn($, 'Write emails')
  await $.tool.call({ tool: 'mcp__savvy-progress__progress', title: 'Ship it', total: 4, done: 1, phase: 'delegate' } as never)
  await spawn($, 'Write ads')

  const ui = await $.ui.mount({ plugin: 'savvy-progress', surface: 'terminal', ...BAND })
  expect((await ui.findAll({ type: 'Text', text: /^Ship it$/ })).length).toBe(1)
  expect((await ui.findAll({ type: 'Text', text: /^Tasks 1\/4$/ })).length).toBe(1)
  await ui.unmount()
})
