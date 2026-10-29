import { expect, mock, test } from 'claude-code/testing'

const PROPS = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 4,
  bodyColumns: 100,
  scroll: { offset: 0, bodyRows: 4 },
  view: {},
} as const

const start = async ($: any, on: any) => {
  mock.store(on)
  mock.clock(on, { now: Date.parse('2098-12-31T22:00:00Z') })
  on('session.start', ($: any, e: any) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: { command: 'ribbon-theme' } }))
  on('session.usage', () => ({
    value: { startedAt: 0, context: { window: 200000 }, rateLimits: [{ kind: 'seven_day', percentUsed: 20 }] },
  }))
  await $.session.start({ surface: 'desktop', isInteractive: true, cwd: '/work' })
}

const background = async ($: any) => {
  const band = await $.ui.mount({ plugin: 'ribbon', surface: 'desktop', component: 'AbovePrompt', props: PROPS })
  const tree = JSON.stringify(await band.find({ type: 'Box' }))
  await band.unmount()
  return tree
}

test('the band starts light and /ribbon-theme switches it to dark and back', async ($, on) => {
  await start($, on)
  expect(await background($)).toContain('#f5f1e6')

  const r = await $.command.run({ command: 'ribbon-theme', args: 'dark' })
  expect(r.text).toBe('Ribbon theme: dark.')
  expect(await background($)).toContain('#24221c')

  await $.command.run({ command: 'ribbon-theme', args: '' })
  expect(await background($)).toContain('#f5f1e6')
})
