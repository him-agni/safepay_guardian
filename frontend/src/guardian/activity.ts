// Pure logic for the guardian's activity grid: row mapping, preset views and the totals row.
// Kept out of the React component so it can be unit-tested.

import { categoryLabel, decidedByWord, decisionWord, guardianStatusWord, money } from '../format'
import type { Level, Payment, Status } from '../types'

export interface Quote {
  type: string
  evidence: string
  source: 'rule' | 'ai'
  label: string
}

export interface ActivityRow {
  id: string
  created: Date
  createdIso: string
  payee: string
  amount: number
  amountCents: number
  level: Level | null
  category: string
  topEvidence: string
  evidence: Quote[]
  summary: string
  checkedBy: string
  aiFlagged: boolean
  status: string
  statusCode: Status | null
  decision: string
  decidedBy: string
  voidsIn: number | null
  waiting: boolean
  isSeed: boolean
  isTotal?: boolean
}

const NEEDS_DECISION: Status[] = ['HELD', 'CAPTURE_FAILED', 'VOID_FAILED']
const NOT_CAPTURED: Status[] = ['VOIDED', 'EXPIRED']
const CHECKED_BY: Record<string, string> = { ai: 'AI + rules', stored_reply: 'Stored AI reply', rules: 'Rules only' }

export function toRow(p: Payment): ActivityRow {
  const brief = p.risk_brief
  const evidence = (brief?.top_evidence ?? []) as Quote[]
  return {
    id: p.id,
    created: new Date(p.created_at),
    createdIso: p.created_at,
    payee: p.payee.name,
    amount: p.amount_cents / 100,
    amountCents: p.amount_cents,
    level: p.risk_level,
    category: categoryLabel(p.category),
    topEvidence: evidence[0]?.evidence ?? '',
    evidence,
    summary: brief?.summary ?? '',
    checkedBy: brief ? CHECKED_BY[brief.checked_by] ?? brief.checked_by : p.is_seed ? 'Past payment' : '—',
    aiFlagged: !!brief?.ai_flagged,
    status: guardianStatusWord(p),
    statusCode: p.status,
    decision: decisionWord(p),
    decidedBy: decidedByWord(p),
    voidsIn: p.hold_seconds_left,
    waiting: NEEDS_DECISION.includes(p.status),
    isSeed: p.is_seed,
  }
}

export type PresetId = 'all' | 'decide' | 'stopped' | 'high' | 'ai'

export const PRESETS: { id: PresetId; label: string; test: (r: ActivityRow) => boolean }[] = [
  { id: 'all', label: 'All', test: () => true },
  { id: 'decide', label: 'Needs a decision', test: (r) => r.waiting },
  { id: 'stopped', label: 'Stopped (not captured)', test: (r) => !!r.statusCode && NOT_CAPTURED.includes(r.statusCode) },
  { id: 'high', label: 'High risk', test: (r) => r.level === 'high' },
  { id: 'ai', label: 'Flagged by AI', test: (r) => r.aiFlagged },
]

export const presetTest = (id: PresetId) => (PRESETS.find((p) => p.id === id) ?? PRESETS[0]).test

export interface Totals {
  count: number
  capturedCents: number
  notCapturedCents: number
  waitingCents: number
  allCents: number
}

export function totals(rows: ActivityRow[]): Totals {
  const sum = (pick: (r: ActivityRow) => boolean) =>
    rows.filter(pick).reduce((acc, r) => acc + r.amountCents, 0)
  return {
    count: rows.length,
    capturedCents: sum((r) => r.statusCode === 'CAPTURED'),
    notCapturedCents: sum((r) => !!r.statusCode && NOT_CAPTURED.includes(r.statusCode)),
    waitingCents: sum((r) => r.waiting || r.statusCode === 'WARNED'),
    allCents: sum(() => true),
  }
}

const dollars = (cents: number) => money((cents / 100).toFixed(2))

/** The pinned bottom row: totals for whatever is currently shown. */
export function totalRow(rows: ActivityRow[]): ActivityRow {
  const t = totals(rows)
  return {
    id: 'total',
    created: new Date(0),
    createdIso: '',
    payee: `${t.count} shown`,
    amount: t.allCents / 100,
    amountCents: t.allCents,
    level: null,
    category: '',
    topEvidence: '',
    evidence: [],
    summary: '',
    checkedBy: '',
    aiFlagged: false,
    status: `Captured ${dollars(t.capturedCents)}`,
    statusCode: null,
    decision: `Not captured ${dollars(t.notCapturedCents)}`,
    decidedBy: t.waitingCents ? `Waiting ${dollars(t.waitingCents)}` : '',
    voidsIn: null,
    waiting: false,
    isSeed: false,
    isTotal: true,
  }
}

/** Same calendar day comparison for AG Grid's date filter (cell values carry a time). */
export function compareDay(filterDate: Date, cell: Date | null): number {
  if (!cell) return -1
  const day = new Date(cell.getFullYear(), cell.getMonth(), cell.getDate())
  if (day.getTime() === filterDate.getTime()) return 0
  return day < filterDate ? -1 : 1
}

/**
 * Make a value safe to open in a spreadsheet. Payee names and quoted messages come from scammers, and a
 * cell such as =HYPERLINK(...) would run as a formula when the CSV is opened in Excel or Sheets. A leading
 * apostrophe makes the spreadsheet show it as text (OWASP's advice for CSV injection).
 */
export function csvSafe(value: string): string {
  return /^[=+\-@\t\r]/.test(value) ? `'${value}` : value
}
