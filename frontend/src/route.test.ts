import { describe, expect, it } from 'vitest'
import { parseHash } from './route'

describe('parseHash', () => {
  it('splits a hash route into its parts', () => {
    expect(parseHash('#/guardian/p/abc123')).toEqual(['guardian', 'p', 'abc123'])
    expect(parseHash('#/')).toEqual([])
    expect(parseHash('')).toEqual([])
  })

  it('decodes percent-encoding', () => {
    expect(parseHash('#/send/a%20b')).toEqual(['send', 'a b'])
  })

  it('does not throw on a malformed address, so the page still loads', () => {
    expect(() => parseHash('#/send/%E0%A4%A')).not.toThrow()
    expect(parseHash('#/send/%E0%A4%A')).toEqual(['send', '%E0%A4%A'])
    expect(parseHash('#/guardian/%/x')).toEqual(['guardian', '%', 'x'])
  })
})
