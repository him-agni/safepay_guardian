import { describe, expect, it } from 'vitest'
import { clearPending, loadPending, outcomeUnknown, PENDING_MAX_AGE_MS, savePending, type PendingSubmission } from './pending'

function fakeStorage() {
  const data = new Map<string, string>()
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  }
}

const pending: PendingSubmission = {
  attempt: { key: 'key-0001-abcd', fingerprint: '[["amount","350"]]' },
  payment: { payee_name: 'Gutter Pros', amount: '350' },
  at: 1_000_000,
}

describe('a submission that did not finish survives a refresh', () => {
  it('is saved and loaded again with the same key and details', () => {
    const s = fakeStorage()
    savePending(pending, s)
    expect(loadPending(1_000_500, s)).toEqual(pending)
  })

  it('is forgotten once cleared', () => {
    const s = fakeStorage()
    savePending(pending, s)
    clearPending(s)
    expect(loadPending(1_000_500, s)).toBeNull()
  })

  it('is dropped when it is too old, so an old payment is not offered', () => {
    const s = fakeStorage()
    savePending(pending, s)
    expect(loadPending(pending.at + PENDING_MAX_AGE_MS + 1, s)).toBeNull()
    expect(s.data.size).toBe(0)
  })

  it('is dropped when the clock went backwards or the data is damaged', () => {
    const s = fakeStorage()
    savePending(pending, s)
    expect(loadPending(pending.at - 5, s)).toBeNull()
    s.setItem('safepay.pending-submission', '{not json')
    expect(loadPending(1_000_500, s)).toBeNull()
    s.setItem('safepay.pending-submission', JSON.stringify({ at: 1, attempt: {}, payment: 3 }))
    expect(loadPending(1_000_500, s)).toBeNull()
  })

  it('never throws when storage is missing or blocked', () => {
    const blocked = () => {
      throw new Error('blocked')
    }
    const broken = { getItem: blocked, setItem: blocked, removeItem: blocked }
    expect(() => savePending(pending, broken)).not.toThrow()
    expect(loadPending(1, broken)).toBeNull()
    expect(() => clearPending(null)).not.toThrow()
    expect(loadPending(1, null)).toBeNull()
  })
})

describe('outcomeUnknown', () => {
  it('is true when nothing came back or the server failed, because the payment may exist', () => {
    expect(outcomeUnknown(0)).toBe(true)
    expect(outcomeUnknown(500)).toBe(true)
    expect(outcomeUnknown(503)).toBe(true)
  })

  it('is false for a clear refusal, because no payment was made', () => {
    for (const status of [400, 409, 413, 422, 429]) expect(outcomeUnknown(status)).toBe(false)
  })
})
