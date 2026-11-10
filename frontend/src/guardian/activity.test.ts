import { describe, expect, it } from 'vitest'
import type { Payment } from '../types'
import { compareDay, csvSafe, presetTest, toRow, totalRow, totals } from './activity'

const pay = (over: Partial<Payment>): Payment =>
  ({
    id: 'p1',
    status: 'HELD',
    amount: '500.00',
    amount_cents: 50000,
    payee: { id: 1, name: 'Officer Collins', email: null, trusted: false },
    risk_level: 'high',
    category: 'government_impersonation',
    created_at: '2026-11-09T20:00:00.000Z',
    hold_seconds_left: 100,
    decided_by: null,
    void_reason: null,
    is_seed: false,
    risk_brief: {
      summary: 'Looks like a tax scam.',
      checked_by: 'ai',
      ai_flagged: true,
      top_evidence: [
        { type: 'gift_card', evidence: 'gift cards', source: 'rule', label: 'Asks for gift cards.' },
        { type: 'impersonation', evidence: 'Officer Collins with the IRS', source: 'ai', label: 'Impersonation.' },
      ],
    },
    ...over,
  }) as Payment

describe('activity rows', () => {
  it('maps a payment to a grid row with evidence and who checked it', () => {
    const r = toRow(pay({}))
    expect(r.amount).toBe(500)
    expect(r.topEvidence).toBe('gift cards')
    expect(r.evidence).toHaveLength(2)
    expect(r.checkedBy).toBe('AI + rules')
    expect(r.category).toBe('Government impersonation')
    expect(r.waiting).toBe(true)
  })

  it('labels seeded history and payments without an assessment', () => {
    const r = toRow(pay({ is_seed: true, status: 'CAPTURED', risk_brief: null }))
    expect(r.checkedBy).toBe('Past payment')
    expect(r.decision).toBe('Past payment')
    expect(r.topEvidence).toBe('')
  })

  it('shows stored AI replies honestly', () => {
    const r = toRow(pay({ risk_brief: { ...pay({}).risk_brief!, checked_by: 'stored_reply' } }))
    expect(r.checkedBy).toBe('Stored AI reply')
  })
})

describe('preset views', () => {
  const rows = [
    toRow(pay({ id: 'held' })),
    toRow(pay({ id: 'voided', status: 'VOIDED', void_reason: 'guardian_decline' })),
    toRow(pay({ id: 'expired', status: 'EXPIRED' })),
    toRow(pay({ id: 'low', status: 'CAPTURED', risk_level: 'low', risk_brief: null })),
    toRow(pay({ id: 'failed', status: 'CAPTURE_FAILED' })),
  ]
  const ids = (preset: Parameters<typeof presetTest>[0]) => rows.filter(presetTest(preset)).map((r) => r.id)

  it('filters by what the guardian needs to see', () => {
    expect(ids('all')).toHaveLength(5)
    expect(ids('decide')).toEqual(['held', 'failed'])
    expect(ids('stopped')).toEqual(['voided', 'expired'])
    expect(ids('high')).toEqual(['held', 'voided', 'expired', 'failed'])
    expect(ids('ai')).toEqual(['held', 'voided', 'expired', 'failed'])
  })
})

describe('totals row', () => {
  const rows = [
    toRow(pay({ id: 'a', status: 'CAPTURED', amount_cents: 3500 })),
    toRow(pay({ id: 'b', status: 'VOIDED', amount_cents: 50000 })),
    toRow(pay({ id: 'c', status: 'EXPIRED', amount_cents: 9000 })),
    toRow(pay({ id: 'd', status: 'HELD', amount_cents: 30000 })),
    toRow(pay({ id: 'e', status: 'WARNED', amount_cents: 35000 })),
  ]

  it('adds up in cents, so there is no floating-point drift', () => {
    expect(totals(rows)).toEqual({
      count: 5,
      capturedCents: 3500,
      notCapturedCents: 59000,
      waitingCents: 65000,
      allCents: 127500,
    })
  })

  it('becomes a readable pinned row', () => {
    const t = totalRow(rows)
    expect(t.isTotal).toBe(true)
    expect(t.payee).toBe('5 shown')
    expect(t.status).toBe('Captured $35.00')
    expect(t.decision).toBe('Not captured $590.00')
    expect(t.decidedBy).toBe('Waiting $650.00')
  })
})

describe('date filter', () => {
  it('matches on the calendar day, ignoring the time', () => {
    const day = new Date(2026, 10, 9)
    expect(compareDay(day, new Date(2026, 10, 9, 15, 30))).toBe(0)
    expect(compareDay(day, new Date(2026, 10, 8, 23, 59))).toBe(-1)
    expect(compareDay(day, new Date(2026, 10, 10, 0, 1))).toBe(1)
  })
})

describe('CSV export', () => {
  it('stops spreadsheet formulas in scam text from running', () => {
    expect(csvSafe('=HYPERLINK("http://evil.example","Click")')).toBe('\'=HYPERLINK("http://evil.example","Click")')
    for (const bad of ['+1+1', '-2+3', '@SUM(A1)', '\t=1', '\r=1']) expect(csvSafe(bad)).toBe(`'${bad}`)
    expect(csvSafe('Officer Collins')).toBe('Officer Collins')
    expect(csvSafe('500.00')).toBe('500.00')
    expect(csvSafe('')).toBe('')
  })
})
