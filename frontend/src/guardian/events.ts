import type { PaymentEvent } from '../types'

const str = (v: unknown) => (v == null ? '' : String(v))

const ACTION_PHRASE: Record<string, string> = {
  auto_capture: 'Low risk: automatic capture started',
  confirm: 'Sender confirmed the warning',
  approve: 'Guardian approved',
  decline: 'Guardian declined',
  cancel: 'Sender cancelled',
  timeout: 'Hold timed out with no decision',
  retry_capture: 'Capture retry started',
  retry_void: 'Void retry started',
}

/** One readable line per audit event. Unknown event types fall back to their name. */
export function describeEvent(e: PaymentEvent): string {
  const d = e.detail
  switch (e.type) {
    case 'payment.created':
      return `Payment created: $${str(d.amount)} to ${str(d.payee)}${d.payee_is_new ? ' (new payee)' : ''}`
    case 'risk.assessed': {
      const dropped = Array.isArray(d.dropped_evidence) ? d.dropped_evidence.length : 0
      return `Risk check: ${str(d.level)} (${d.mode === 'hybrid' ? 'rules + AI' : 'rules only'})${
        dropped ? `, ${dropped} unverifiable AI quote${dropped === 1 ? '' : 's'} dropped` : ''
      }`
    }
    case 'status.changed':
      return `Status ${str(d.from)} → ${str(d.to)}`
    case 'paypal.authorized':
      return `PayPal authorization ${str(d.authorization_id)} placed (${str(d.authorization_status)})`
    case 'paypal.authorization_failed':
      return `PayPal authorization failed: ${str(d.message)}`
    case 'paypal.authorization_read':
      return `PayPal shows the authorization as ${str(d.status)}`
    case 'paypal.capture_requested':
      return `Capture sent to PayPal (request id ${str(d.request_id)})`
    case 'paypal.captured':
      return `PayPal capture ${str(d.capture_id)} ${str(d.capture_status).toLowerCase()}`
    case 'paypal.capture_failed':
      return `Capture failed: ${str(d.message)}`
    case 'paypal.void_requested':
      return `Void sent to PayPal (request id ${str(d.request_id)})`
    case 'paypal.voided':
      return 'PayPal authorization voided'
    case 'paypal.void_failed':
      return `Void failed: ${str(d.message)}`
    case 'paypal.capture_skipped':
    case 'paypal.void_skipped':
      return str(d.message)
    case 'hold.placed':
      return 'Held for the guardian'
    case 'hold.warned':
      return 'Sender warned and asked to confirm'
    case 'decision.accepted':
      return `${ACTION_PHRASE[str(d.action)] ?? str(d.action)}${d.note ? `, note: “${str(d.note)}”` : ''}`
    case 'decision.repeated':
      return `Repeated ${str(d.action)}: the first result was returned, nothing sent to PayPal again`
    case 'decision.rejected':
      return `${str(d.action)} rejected: the payment was already ${str(d.status)}`
    case 'message.added':
      return 'Message added to the thread'
    case 'seed.history':
      return 'Past payment added as demo history (no PayPal call)'
    case 'recovery.resumed':
      return `Resumed after a restart (was ${str(d.status)})`
    default:
      return e.type
  }
}
