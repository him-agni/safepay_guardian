import type { Payment } from './types'

// Payments we already have in memory (e.g. the response to "Send for check"), so the result
// page can render immediately instead of flashing a loading state before its first poll.
const known = new Map<string, Payment>()

export const remember = (p: Payment) => {
  known.set(p.id, p)
  return p
}

export const recall = (id: string) => known.get(id) ?? null
