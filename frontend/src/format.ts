import type { Level, Payment } from './types'

export function money(amount: string, currency = 'USD'): string {
  const n = Number(amount)
  if (!Number.isFinite(n)) return `$${amount}`
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(n)
}

export function duration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h} hour${h === 1 ? '' : 's'} ${m} min`
  if (m > 0) return `${m} min ${sec} s`
  return `${sec} s`
}

export function timeAgo(iso: string): string {
  const then = Date.parse(iso)
  if (!Number.isFinite(then)) return ''
  const s = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return new Date(then).toLocaleDateString()
}

export const LEVEL_WORD: Record<Level, string> = { low: 'Low', medium: 'Medium', high: 'High' }

/** Short status word for the sender's list. Sender wording never says "authorization voided". */
export function senderStatusWord(p: Payment): string {
  switch (p.status) {
    case 'CAPTURED':
      return 'Completed'
    case 'WARNED':
      return 'Needs your OK'
    case 'HELD':
      return 'On hold'
    case 'VOIDED':
      return p.void_reason === 'sender_cancel' ? 'Cancelled' : 'Declined'
    case 'EXPIRED':
      return 'Not sent'
    case 'AUTH_FAILED':
      return 'Could not start'
    case 'VOID_FAILED':
      return 'Stopped'
    case 'CAPTURE_FAILED':
      return 'Approved, not sent yet'
    default:
      return 'In progress'
  }
}

/** Plain reasons for the sender: one line per distinct label, strongest first. */
export function reasons(p: Payment, max = 5): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const ind of p.risk?.indicators ?? []) {
    const label = ind.label.trim()
    if (!label || seen.has(label.toLowerCase())) continue
    seen.add(label.toLowerCase())
    out.push(label)
    if (out.length === max) break
  }
  return out
}

/** True when every sentence of the summary is already one of the listed reasons. */
export function summaryRepeatsReasons(summary: string, list: string[]): boolean {
  const sentences = summary
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean)
  return sentences.length > 0 && sentences.every((s) => list.includes(s))
}

/** Accepts "$1,250.50" style input from the form. */
export function cleanAmount(raw: string): string {
  return raw.replace(/[$,\s]/g, '')
}

export function amountProblem(raw: string): string | null {
  const v = cleanAmount(raw)
  if (!v) return 'Please enter how much you want to send.'
  if (!/^\d+(\.\d{1,2})?$/.test(v)) return 'Please enter the amount as a number, like 35 or 35.50.'
  const n = Number(v)
  if (n <= 0) return 'The amount must be more than $0.'
  if (n > 10000) return 'The most you can send here is $10,000.'
  return null
}
