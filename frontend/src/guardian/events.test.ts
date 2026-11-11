import { describe, expect, it } from 'vitest'
import { categoryLabel, decidedByWord, decisionWord, guardianStatusWord, senderStatusWord } from '../format'
import type { Payment, PaymentEvent } from '../types'
import { describeEvent } from './events'

const ev = (type: string, detail: Record<string, unknown> = {}): PaymentEvent => ({
  at: '2026-11-09T20:00:00.000Z',
  actor: 'system',
  type,
  detail,
})
const p = (over: Partial<Payment>) => ({ status: 'HELD', decided_by: null, void_reason: null, ...over }) as Payment

describe('audit log lines', () => {
  it('describes PayPal steps with their ids', () => {
    expect(describeEvent(ev('paypal.authorized', { authorization_id: 'AUTH1', authorization_status: 'CREATED' }))).toBe(
      'PayPal authorization AUTH1 placed (CREATED)',
    )
    expect(describeEvent(ev('paypal.capture_requested', { request_id: 'p1-capture-1' }))).toBe(
      'Capture sent to PayPal (request id p1-capture-1)',
    )
    expect(describeEvent(ev('status.changed', { from: 'HELD', to: 'VOIDING' }))).toBe('Status HELD → VOIDING')
  })

  it('explains repeated and rejected decisions', () => {
    expect(describeEvent(ev('decision.repeated', { action: 'approve' }))).toMatch(/nothing sent to PayPal again/)
    expect(describeEvent(ev('decision.rejected', { action: 'approve', status: 'VOIDED' }))).toBe(
      'approve rejected: the payment was already VOIDED',
    )
    expect(describeEvent(ev('decision.accepted', { action: 'timeout' }))).toBe('Hold timed out with no decision')
    expect(describeEvent(ev('decision.accepted', { action: 'decline', note: 'Scam' }))).toBe(
      'Guardian declined, note: “Scam”',
    )
  })

  it('counts dropped AI quotes in the risk line', () => {
    expect(
      describeEvent(ev('risk.assessed', { level: 'high', mode: 'hybrid', dropped_evidence: [{}, {}] })),
    ).toBe('Risk check: high (rules + AI), 2 unverifiable AI quotes dropped')
  })

  it('falls back to the event name', () => {
    expect(describeEvent(ev('something.new'))).toBe('something.new')
  })
})

describe('guardian wording', () => {
  it('uses PayPal terms on the guardian side', () => {
    expect(guardianStatusWord(p({ status: 'VOIDED' }))).toBe('Voided')
    expect(guardianStatusWord(p({ status: 'EXPIRED' }))).toBe('Timed out, voided')
    expect(guardianStatusWord(p({ status: 'CAPTURED' }))).toBe('Captured')
  })

  it('does not call a pending capture captured', () => {
    expect(guardianStatusWord(p({ status: 'CAPTURE_PENDING' }))).toBe('Capture pending')
    expect(senderStatusWord(p({ status: 'CAPTURE_PENDING' }))).toBe('Confirming')
  })

  it('says who decided', () => {
    expect(decisionWord(p({ status: 'CAPTURED', decided_by: 'guardian' }))).toBe('Approved')
    expect(decidedByWord(p({ status: 'CAPTURED', decided_by: 'guardian' }))).toBe('Guardian')
    expect(decisionWord(p({ status: 'CAPTURED' }))).toBe('Automatic')
    expect(decidedByWord(p({ status: 'CAPTURED' }))).toBe('Rules')
    expect(decisionWord(p({ status: 'VOIDED', void_reason: 'sender_cancel' }))).toBe('Cancelled')
    expect(decisionWord(p({ status: 'EXPIRED', void_reason: 'timeout', decided_by: 'system' }))).toBe('Timed out')
    expect(decidedByWord(p({ status: 'EXPIRED', decided_by: 'system' }))).toBe('System (timeout)')
  })

  it('labels categories in plain words', () => {
    expect(categoryLabel('government_impersonation')).toBe('Government impersonation')
    expect(categoryLabel(null)).toBe('Not classified')
    expect(categoryLabel('uncategorised')).toBe('Not classified')
  })
})
