// "Ask your activity": the column description sent to the backend, and turning the validated filters it
// returns into AG Grid filter models and plain-language chips. Pure functions, unit-tested.

import { categoryLabel, money } from '../format'

export type ColumnType = 'text' | 'enum' | 'number' | 'date'

export interface AskColumn {
  id: string // the grid's column id
  label: string
  type: ColumnType
  values?: string[]
}

export interface AskFilter {
  column: string
  operator: 'contains' | 'equals' | 'greater_than' | 'less_than' | 'between' | 'on' | 'after' | 'before'
  value: string | number
  value_to?: string | number
}

export interface AskSort {
  column: string
  direction: 'asc' | 'desc'
}

export interface AskResult {
  understood: boolean
  explanation: string
  filters: AskFilter[]
  sort: AskSort | null
  ignored: { column?: string; value?: string; reason: string }[]
  error: string | null
  model: string | null
  cached: boolean
  latency_ms: number | null
}

const CATEGORIES = [
  'government_impersonation', 'bank_impersonation', 'tech_support', 'grandparent', 'family_impersonation', 'romance',
  'prize', 'contractor', 'utility_impersonation', 'delivery', 'employment', 'investment', 'charity', 'rental', 'other',
].map(categoryLabel)

/** A fixed description of the grid (not built from the data), so stored AI replies keep matching. */
export const ASK_COLUMNS: AskColumn[] = [
  { id: 'payee', label: 'Payee', type: 'text' },
  { id: 'amount', label: 'Amount in US dollars', type: 'number' },
  { id: 'level', label: 'Risk', type: 'enum', values: ['low', 'medium', 'high'] },
  { id: 'category', label: 'Looks like (scam type)', type: 'enum', values: [...CATEGORIES, 'Not classified'] },
  { id: 'evidence', label: 'Top evidence (quoted words)', type: 'text' },
  {
    id: 'status',
    label: 'Status',
    type: 'enum',
    values: ['Captured', 'Voided', 'Timed out, voided', 'On hold', 'Sender warned', 'Authorization failed',
      'Capture failed', 'Void failed', 'Capturing', 'Voiding', 'Authorizing'],
  },
  {
    id: 'decision',
    label: 'Decision',
    type: 'enum',
    values: ['Approved', 'Confirmed', 'Automatic', 'Declined', 'Cancelled', 'Timed out', 'Not authorized', 'Waiting',
      'In progress', 'Past payment'],
  },
  { id: 'decidedBy', label: 'Decided by', type: 'enum', values: ['Guardian', 'Sender', 'System (timeout)', 'Rules'] },
  { id: 'checkedBy', label: 'Checked by', type: 'enum', values: ['AI + rules', 'Stored AI reply', 'Rules only', 'Past payment'] },
  { id: 'created', label: 'Date of the payment', type: 'date' },
]

const TYPE_OF: Record<string, ColumnType> = Object.fromEntries(ASK_COLUMNS.map((c) => [c.id, c.type]))
const LABEL_OF: Record<string, string> = {
  payee: 'Payee', amount: 'Amount', level: 'Risk', category: 'Looks like', evidence: 'Top evidence',
  status: 'Status', decision: 'Decision', decidedBy: 'Decided by', checkedBy: 'Checked by', created: 'Date',
}

type Condition = Record<string, unknown>

function condition(f: AskFilter): Condition {
  const type = TYPE_OF[f.column]
  if (type === 'number') {
    const kind = { greater_than: 'greaterThan', less_than: 'lessThan', equals: 'equals', between: 'inRange' }[
      f.operator as 'greater_than' | 'less_than' | 'equals' | 'between'
    ]
    return { filterType: 'number', type: kind, filter: Number(f.value), ...(f.operator === 'between' ? { filterTo: Number(f.value_to) } : {}) }
  }
  if (type === 'date') {
    const kind = { on: 'equals', after: 'greaterThan', before: 'lessThan', between: 'inRange' }[
      f.operator as 'on' | 'after' | 'before' | 'between'
    ]
    return {
      filterType: 'date',
      type: kind,
      dateFrom: `${f.value} 00:00:00`,
      dateTo: f.operator === 'between' ? `${f.value_to} 00:00:00` : null,
    }
  }
  return { filterType: 'text', type: f.operator === 'contains' ? 'contains' : 'equals', filter: String(f.value) }
}

/** AG Grid filter model: one condition per column, or two combined with AND. */
export function toFilterModel(filters: AskFilter[]): Record<string, Condition> {
  const byColumn = new Map<string, AskFilter[]>()
  for (const f of filters) byColumn.set(f.column, [...(byColumn.get(f.column) ?? []), f])
  const model: Record<string, Condition> = {}
  for (const [column, list] of byColumn) {
    const conds = list.slice(0, 2).map(condition)
    model[column] = conds.length === 1 ? conds[0] : { filterType: conds[0].filterType, operator: 'AND', conditions: conds }
  }
  return model
}

const day = (iso: string | number) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
const dollars = (v: string | number) => money(Number(v).toFixed(2)).replace('.00', '')

/** "Risk is High", "Amount over $200", "Payee contains “Collins”", "Date after Nov 3". */
export function describeFilter(f: AskFilter): string {
  const label = LABEL_OF[f.column] ?? f.column
  const type = TYPE_OF[f.column]
  if (type === 'number') {
    if (f.operator === 'greater_than') return `${label} over ${dollars(f.value)}`
    if (f.operator === 'less_than') return `${label} under ${dollars(f.value)}`
    if (f.operator === 'between') return `${label} ${dollars(f.value)} to ${dollars(f.value_to ?? f.value)}`
    return `${label} is ${dollars(f.value)}`
  }
  if (type === 'date') {
    if (f.operator === 'after') return `${label} after ${day(f.value)}`
    if (f.operator === 'before') return `${label} before ${day(f.value)}`
    if (f.operator === 'between') return `${label} ${day(f.value)} to ${day(f.value_to ?? f.value)}`
    return `${label} on ${day(f.value)}`
  }
  if (f.operator === 'contains') return `${label} contains “${f.value}”`
  const value = f.column === 'level' ? String(f.value).charAt(0).toUpperCase() + String(f.value).slice(1) : String(f.value)
  return `${label} is ${value}`
}

export function describeSort(s: AskSort): string {
  const label = LABEL_OF[s.column] ?? s.column
  const order: Record<string, [string, string]> = {
    amount: ['smallest first', 'largest first'],
    created: ['oldest first', 'newest first'],
    level: ['lowest risk first', 'highest risk first'],
  }
  const [asc, desc] = order[s.column] ?? ['A to Z', 'Z to A']
  return `Sorted by ${label}, ${s.direction === 'asc' ? asc : desc}`
}
