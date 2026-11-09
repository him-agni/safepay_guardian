import {
  CellStyleModule,
  ClientSideRowModelModule,
  ModuleRegistry,
  NumberFilterModule,
  QuickFilterModule,
  TextFilterModule,
  ValidationModule,
  themeQuartz,
  type ColDef,
  type ICellRendererParams,
} from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useMemo, useState } from 'react'
import { api } from '../api'
import { ErrorNote, RiskBadge } from '../components'
import { categoryLabel, decidedByWord, decisionWord, guardianStatusWord, money } from '../format'
import { usePoll } from '../hooks'
import { LEVEL_ORDER } from '../levels'
import type { Level, Payment } from '../types'

ModuleRegistry.registerModules([
  CellStyleModule,
  ClientSideRowModelModule,
  TextFilterModule,
  NumberFilterModule,
  QuickFilterModule,
  ...(import.meta.env.DEV ? [ValidationModule] : []),
])

const theme = themeQuartz.withParams({
  fontFamily: 'inherit',
  fontSize: 16,
  headerFontSize: 15,
  rowHeight: 52,
  headerHeight: 50,
  accentColor: '#0b4fa3',
  foregroundColor: '#14181f',
  headerBackgroundColor: '#eef1f5',
  borderColor: '#c9d0db',
})

interface Row {
  id: string
  created_at: string
  payee: string
  amount: number
  level: Level | null
  category: string
  status: string
  decision: string
  decided_by: string
}

/** "3:02 PM" for today, "Nov 8, 3:02 PM" otherwise. */
function shortTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  if (d.toDateString() === new Date().toDateString()) return time
  return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}, ${time}`
}

const toRow = (p: Payment): Row => ({
  id: p.id,
  created_at: p.created_at,
  payee: p.payee.name,
  amount: Number(p.amount),
  level: p.risk_level,
  category: categoryLabel(p.category),
  status: guardianStatusWord(p),
  decision: decisionWord(p),
  decided_by: decidedByWord(p),
})

function RiskCell({ value }: ICellRendererParams<Row, Level | null>) {
  return value ? <RiskBadge level={value} suffix="" compact /> : null
}

function PayeeCell({ value, data }: ICellRendererParams<Row, string>) {
  return data ? <a href={`#/guardian/p/${data.id}`}>{value}</a> : null
}

const columns: ColDef<Row>[] = [
  { field: 'created_at', headerName: 'Time', sort: 'desc', valueFormatter: (p) => shortTime(p.value), minWidth: 95 },
  { field: 'payee', headerName: 'Payee', cellRenderer: PayeeCell, filter: 'agTextColumnFilter', minWidth: 155 },
  {
    field: 'amount',
    headerName: 'Amount',
    type: 'rightAligned',
    filter: 'agNumberColumnFilter',
    valueFormatter: (p) => money(String(p.value)),
    minWidth: 115,
  },
  {
    field: 'level',
    headerName: 'Risk',
    cellRenderer: RiskCell,
    filter: 'agTextColumnFilter',
    comparator: (a: Level | null, b: Level | null) => (a ? LEVEL_ORDER[a] : -1) - (b ? LEVEL_ORDER[b] : -1),
    minWidth: 125,
  },
  { field: 'category', headerName: 'Looks like', filter: 'agTextColumnFilter', minWidth: 155 },
  { field: 'status', headerName: 'Status', filter: 'agTextColumnFilter', minWidth: 135 },
  { field: 'decision', headerName: 'Decision', filter: 'agTextColumnFilter', minWidth: 115 },
  { field: 'decided_by', headerName: 'Decided by', filter: 'agTextColumnFilter', minWidth: 130 },
]

export function ActivityPage() {
  const poll = usePoll(() => api.listPayments({ limit: 500 }), 3000, 'guardian-activity')
  const [search, setSearch] = useState('')
  const rows = useMemo(() => (poll.data ?? []).map(toRow), [poll.data])

  return (
    <section className="card">
      <h1>Activity</h1>
      <p className="muted">Every payment, newest first. Sort or filter any column; open a payee to see the full review.</p>
      <div className="field grid-search">
        <label htmlFor="activity-search">Search all columns</label>
        <input
          id="activity-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="For example: gift, declined, Officer"
        />
      </div>
      <ErrorNote error={poll.error} />
      <div className="grid-wrap">
        <div className="grid-box">
          <AgGridReact<Row>
            theme={theme}
            rowData={rows}
            columnDefs={columns}
            defaultColDef={{ sortable: true, resizable: true, flex: 1 }}
            getRowId={(p) => p.data.id}
            quickFilterText={search}
            overlayNoRowsTemplate="No payments yet."
          />
        </div>
      </div>
    </section>
  )
}
