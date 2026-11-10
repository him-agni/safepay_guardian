import { describe, expect, it } from 'vitest'
import { amountProblem, cleanAmount, duration, reasons, senderStatusWord, summaryRepeatsReasons } from './format'
import type { Payment } from './types'

const payment = (over: Partial<Payment>): Payment => ({ status: 'HELD', void_reason: null, ...over }) as Payment

describe('amount input', () => {
  it('accepts dollars written the way people type them', () => {
    expect(cleanAmount('$1,250.50 ')).toBe('1250.50')
    expect(amountProblem('35')).toBeNull()
    expect(amountProblem('$35.5')).toBeNull()
  })

  it('explains what is wrong in plain words', () => {
    expect(amountProblem('')).toMatch(/how much/)
    expect(amountProblem('12.345')).toMatch(/like 35 or 35.50/)
    expect(amountProblem('ten')).toMatch(/like 35 or 35.50/)
    expect(amountProblem('0')).toMatch(/more than \$0/)
    expect(amountProblem('10000.01')).toMatch(/\$10,000/)
  })
})

describe('sender wording', () => {
  it('never says "authorization voided" on the sender side', () => {
    expect(senderStatusWord(payment({ status: 'VOIDED', void_reason: 'guardian_decline' }))).toBe('Declined')
    expect(senderStatusWord(payment({ status: 'VOIDED', void_reason: 'sender_cancel' }))).toBe('Cancelled')
    expect(senderStatusWord(payment({ status: 'EXPIRED' }))).toBe('Not sent')
    expect(senderStatusWord(payment({ status: 'HELD' }))).toBe('On hold')
  })

  it('lists each reason once, strongest first, up to the limit', () => {
    const p = payment({
      risk: {
        indicators: [
          { label: 'The message asks for gift cards.' },
          { label: 'It pushes you to act fast.' },
          { label: 'it pushes you to act fast.' },
          { label: '' },
          { label: 'You have not paid Officer Smith before.' },
        ],
      } as Payment['risk'],
    })
    expect(reasons(p)).toEqual([
      'The message asks for gift cards.',
      'It pushes you to act fast.',
      'You have not paid Officer Smith before.',
    ])
    expect(reasons(p, 1)).toHaveLength(1)
  })
})

describe('summaryRepeatsReasons', () => {
  const list = ['The message asks for gift cards.', 'It pushes you to act fast.', 'You have not paid X before.']
  it('hides a rules-built summary made of listed reasons', () => {
    expect(summaryRepeatsReasons('The message asks for gift cards. It pushes you to act fast.', list)).toBe(true)
  })
  it('keeps an AI summary written in its own words', () => {
    expect(summaryRepeatsReasons('This looks like a tax scam. The IRS never asks for gift cards.', list)).toBe(false)
    expect(summaryRepeatsReasons('', list)).toBe(false)
  })
})

describe('duration', () => {
  it('reads naturally', () => {
    expect(duration(86399)).toBe('23 hours 59 min')
    expect(duration(3600)).toBe('1 hour 0 min')
    expect(duration(100)).toBe('1 min 40 s')
    expect(duration(9)).toBe('9 s')
    expect(duration(-5)).toBe('0 s')
  })
})

describe('screenshot check', () => {
  it('accepts PNG, JPEG and WebP under 4 MB', async () => {
    const { screenshotProblem } = await import('./format')
    expect(screenshotProblem({ type: 'image/png', size: 200_000 })).toBeNull()
    expect(screenshotProblem({ type: 'image/jpeg', size: 3_999_999 })).toBeNull()
    expect(screenshotProblem({ type: 'image/webp', size: 1 })).toBeNull()
  })

  it('explains what is wrong in plain words', async () => {
    const { screenshotProblem } = await import('./format')
    expect(screenshotProblem({ type: 'image/gif', size: 100 })).toMatch(/PNG, JPEG or WebP/)
    expect(screenshotProblem({ type: 'application/pdf', size: 100 })).toMatch(/PNG, JPEG or WebP/)
    expect(screenshotProblem({ type: 'image/png', size: 4_000_001 })).toMatch(/smaller than 4 MB/)
    expect(screenshotProblem({ type: 'image/png', size: 0 })).toMatch(/empty/)
  })
})
