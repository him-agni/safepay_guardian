import type { RecentPayment } from '../types'

export interface DayOutcomes {
  /** Local calendar day, YYYY-MM-DD. */
  day: string
  /** Short axis label, e.g. "Nov 10". */
  label: string
  captured: number
  stopped: number
  open: number
  /** How many of the day's payments are seeded past history rather than payments made in this demo. */
  past: number
}

function localDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * Group recent payments by the viewer's local day, oldest first, one entry per day (empty days included
 * so the time axis is honest). Only days from the first payment onwards are kept, so a short history is
 * not squeezed into a mostly empty month.
 */
export function dailyOutcomes(recent: RecentPayment[], days: number, now = new Date()): DayOutcomes[] {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (days - 1))
  const byDay = new Map<string, DayOutcomes>()
  for (let i = 0; i < days; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    byDay.set(localDay(d), { day: localDay(d), label, captured: 0, stopped: 0, open: 0, past: 0 })
  }
  for (const r of recent) {
    const entry = byDay.get(localDay(new Date(r.at)))
    if (!entry) continue
    entry[r.outcome === 'open' ? 'open' : r.outcome] += 1
    if (r.past) entry.past += 1
  }
  const all = [...byDay.values()]
  const first = all.findIndex((d) => d.captured + d.stopped + d.open > 0)
  return first < 0 ? [] : all.slice(first)
}

/** "3 payments" / "1 payment". */
export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}
