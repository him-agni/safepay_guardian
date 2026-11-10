import { describe, expect, it } from 'vitest'
import { safetyTips } from './safetyTips'

describe('safety tips', () => {
  it('leads with the tip for the kind of scam, then general advice', () => {
    const tips = safetyTips('bank_impersonation')
    expect(tips).toHaveLength(3)
    expect(tips[0]).toMatch(/safe" or "protected" account/)
    expect(tips[1]).toMatch(/gift cards, crypto or a wire transfer/)
  })

  it('falls back to the general tips when the kind of scam is unknown', () => {
    for (const c of [null, undefined, 'none', 'other', 'uncategorised']) {
      const tips = safetyTips(c)
      expect(tips).toHaveLength(3)
      expect(tips[2]).toMatch(/rush you/)
    }
  })

  it('has a tip for every scam category the AI can report', () => {
    const categories = ['government_impersonation', 'bank_impersonation', 'tech_support', 'grandparent',
      'family_impersonation', 'romance', 'prize', 'contractor', 'utility_impersonation', 'delivery', 'employment',
      'investment', 'charity', 'rental']
    for (const c of categories) expect(safetyTips(c)[0]).not.toBe(safetyTips(null)[0])
  })
})
