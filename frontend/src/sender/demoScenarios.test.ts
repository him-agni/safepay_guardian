/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DEMO_SCENARIOS, isDemoMode } from './demoScenarios'

const root = resolve(import.meta.dirname, '../../..')
const json = JSON.parse(readFileSync(resolve(root, 'demo/scenarios.json'), 'utf-8')) as {
  scenarios: { id: string; payee: string; amount: string; note: string; message: string; screenshot?: string }[]
}

describe('demo scenarios', () => {
  it('match demo/scenarios.json exactly, because the stored AI replies only match identical text', () => {
    expect(DEMO_SCENARIOS.map((s) => s.id)).toEqual(json.scenarios.map((s) => s.id))
    for (const sc of json.scenarios) {
      const mine = DEMO_SCENARIOS.find((s) => s.id === sc.id)!
      expect(mine.payee_name).toBe(sc.payee)
      expect(mine.amount).toBe(sc.amount)
      expect(mine.note).toBe(sc.note)
      expect(mine.message_text).toBe(sc.message)
      expect(Boolean(mine.screenshot)).toBe(Boolean(sc.screenshot))
    }
  })

  it('serve the very same screenshot bytes as the backend demo uses (its stored reading is keyed by the image)', () => {
    const served = readFileSync(resolve(root, 'frontend/public/demo/bank-fraud-team-text.png'))
    const original = readFileSync(resolve(root, 'demo/screenshots/bank-fraud-team-text.png'))
    expect(served.equals(original)).toBe(true)
  })
})

describe('isDemoMode', () => {
  it('is on when the backend replays stored AI answers', () => {
    expect(isDemoMode({ ai: { provider: 'replay' } }, '')).toBe(true)
  })

  it('is on with ?demo, for recording against the real services', () => {
    expect(isDemoMode({ ai: { provider: 'gemini' } }, '?demo=1')).toBe(true)
    expect(isDemoMode(null, '?demo')).toBe(true)
  })

  it('is off for a normal run', () => {
    expect(isDemoMode({ ai: { provider: 'gemini' } }, '')).toBe(false)
    expect(isDemoMode(null, '')).toBe(false)
  })
})
