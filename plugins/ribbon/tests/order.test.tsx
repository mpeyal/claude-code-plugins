import { expect, mock, test } from 'claude-code/testing'

const PROPS = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 6,
  bodyColumns: 100,
  scroll: { offset: 0, bodyRows: 6 },
  view: {},
} as const

test("another mod's band sits above the usage band", async ($, on) => {
  mock.store(on)
  mock.clock(on, { now: Date.parse('2098-12-31T22:00:00Z') })
  on('session.start', ($: any, e: any) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: { command: 'ribbon-theme' } }))
  on('session.usage', () => ({
    value: { startedAt: 0, context: { window: 200000 }, rateLimits: [{ kind: 'seven_day', percentUsed: 20 }] },
  }))
  // Stands for savvy-progress's band, drawn beneath ribbon in the chain.
  on('ui.render', ($: any, e: any) => {
    const { Text } = $.ui.resolve(e)
    return <Text>savvy band</Text>
  })
  await $.session.start({ surface: 'desktop', isInteractive: true, cwd: '/work' })

  const band = await $.ui.mount({ plugin: 'ribbon', surface: 'desktop', component: 'AbovePrompt', props: PROPS })
  const tree = JSON.stringify(await band.find({ type: 'Box' }))
  expect(tree.indexOf('savvy band')).toBeGreaterThan(-1)
  expect(tree.indexOf('savvy band')).toBeLessThan(tree.indexOf('USAGE'))
  await band.unmount()
})
