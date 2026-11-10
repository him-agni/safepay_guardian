import { describe, expect, it } from 'vitest'
import { dailyOutcomes, plural } from './insights'

const at = (y: number, m: number, d: number, h = 12) => new Date(y, m - 1, d, h).toISOString()

describe('daily outcomes', () => {
  const now = new Date(2026, 10, 10, 15)

  it('groups by local day from the first payment, keeping empty days', () => {
    const days = dailyOutcomes(
      [
        { at: at(2026, 11, 7), outcome: 'captured', past: true },
        { at: at(2026, 11, 10, 9), outcome: 'stopped', past: false },
        { at: at(2026, 11, 10, 10), outcome: 'open', past: false },
        { at: at(2026, 11, 10, 11), outcome: 'captured', past: false },
      ],
      30,
      now,
    )
    expect(days.map((d) => d.day)).toEqual(['2026-11-07', '2026-11-08', '2026-11-09', '2026-11-10'])
    expect(days[0]).toMatchObject({ label: 'Nov 7', captured: 1, past: 1 })
    expect(days[1]).toMatchObject({ captured: 0, stopped: 0, open: 0 })
    expect(days[3]).toMatchObject({ label: 'Nov 10', captured: 1, stopped: 1, open: 1, past: 0 })
  })

  it('ignores payments outside the window and returns nothing for no payments', () => {
    expect(dailyOutcomes([{ at: at(2026, 9, 1), outcome: 'captured', past: true }], 30, now)).toEqual([])
    expect(dailyOutcomes([], 30, now)).toEqual([])
  })

  it('words counts', () => {
    expect(plural(1, 'payment')).toBe('1 payment')
    expect(plural(3, 'payment')).toBe('3 payments')
  })
})
