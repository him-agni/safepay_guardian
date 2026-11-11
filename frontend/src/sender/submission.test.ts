import { describe, expect, it } from 'vitest'
import { attemptFor, fingerprintOf, newSubmissionKey } from './submission'

const fields = { payee_name: 'Gutter Pros', amount: '350', note: '', message_text: 'Deposit', screenshot_id: undefined }

describe('submission key', () => {
  it('is accepted by the server: 8 to 64 letters, digits, - and _', () => {
    for (let i = 0; i < 20; i++) expect(newSubmissionKey()).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
  })

  it('is different every time', () => {
    expect(newSubmissionKey()).not.toBe(newSubmissionKey())
  })
})

describe('attemptFor', () => {
  it('keeps the key when the same details are sent again (a retry)', () => {
    const first = attemptFor(null, fields, () => 'key-one-0001')
    const again = attemptFor(first, { ...fields }, () => 'key-two-0002')
    expect(again.key).toBe('key-one-0001')
  })

  it('starts a new key when anything changes', () => {
    const first = attemptFor(null, fields, () => 'key-one-0001')
    expect(attemptFor(first, { ...fields, amount: '3500' }, () => 'key-two-0002').key).toBe('key-two-0002')
    expect(attemptFor(first, { ...fields, note: 'x' }, () => 'key-three-03').key).toBe('key-three-03')
  })

  it('starts a new key after a payment went through (nothing to compare with)', () => {
    expect(attemptFor(null, fields, () => 'fresh-key-0001').key).toBe('fresh-key-0001')
  })

  it('does not care about the order the fields are listed in', () => {
    expect(fingerprintOf({ a: 1, b: 2 })).toBe(fingerprintOf({ b: 2, a: 1 }))
  })

  it('treats a missing screenshot and an explicit null the same', () => {
    expect(fingerprintOf({ a: undefined })).toBe(fingerprintOf({ a: null }))
  })
})
