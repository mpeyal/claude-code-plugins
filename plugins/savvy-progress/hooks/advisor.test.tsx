import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

// Local change: advisor consults, read off the main thread's requests, show as a row in the panel.
const PANE = {
  plugin: 'savvy-progress',
  component: 'Pane',
  requestId: 'savvy-agents',
  props: { title: 'Agents', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
} as const

const T0 = Date.parse('2026-10-10T02:00:00Z')

async function session($: Engine, on: On) {
  // One request whose response consulted the advisor twice: 12 s, then 27 s.
  on('turn.step', async function* (_: unknown, e: { turnId: string; index: number }) {
    return {
      turnId: e.turnId,
      index: e.index,
      answer: '',
      toolUses: [],
      serverToolUses: [
        { id: 'adv1', name: 'advisor', input: {}, startedAt: T0, endedAt: T0 + 12_000 },
        { id: 'adv2', name: 'advisor', input: {}, startedAt: T0 + 20_000, endedAt: T0 + 47_000 },
        { id: 'ws1', name: 'web_search', input: {}, startedAt: T0, endedAt: T0 + 1_000 },
      ],
      stopReason: 'end_turn',
      usage: { model: 'claude-opus-5-5', input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 },
    }
  } as never)
  mock.clock(on, { now: T0 })
  mock.env(on, { LANG: 'en_US.UTF-8' })
  on('settings.read', async () => ({ value: { advisorModel: 'opus' } }) as never)
  on('session.start', async () => ({ cwd: '/repo' }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true } }) as never)
  await $.session.start({ source: 'startup', cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
}

const ROW = 'Advisor · Opus · 2 consults · last 0:27 · total 0:39'

test('no advisor row before any consult', async ($, on) => {
  await session($, on)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
  expect((await ui.findAll({ type: 'Text', text: /^Advisor/ })).length).toBe(0)
  await ui.unmount()
})

test('a main-thread request that consulted the advisor shows its row on every surface', async ($, on) => {
  await session($, on)
  for await (const _ of $.turn.step({ turnId: 't1', index: 0, model: 'claude-opus-5-5', messageCount: 2 } as never)) {
  }
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface } as never)
    expect((await ui.findAll({ type: 'Text', text: ROW })).length).toBe(1)
    await ui.unmount()
  }
})
