import {
  CellStyleModule,
  ClientSideRowModelApiModule,
  ClientSideRowModelModule,
  ColumnApiModule,
  CsvExportModule,
  DateFilterModule,
  ExternalFilterModule,
  GridStateModule,
  HighlightChangesModule,
  ModuleRegistry,
  NumberFilterModule,
  PinnedRowModule,
  QuickFilterModule,
  RowStyleModule,
  TextFilterModule,
  TooltipModule,
  ValidationModule,
  themeQuartz,
  type CellKeyDownEvent,
  type ColDef,
  type FilterModel,
  type GridState,
  type ICellRendererParams,
  type IRowNode,
  type ITooltipParams,
  type RowClassRules,
  type TooltipCallbackParams,
} from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { ErrorNote, RiskBadge } from '../components'
import { duration, money } from '../format'
import { go, usePoll } from '../hooks'
import { LEVEL_ORDER } from '../levels'
import { useTheme } from '../theme'
import type { Level } from '../types'
import { compareDay, csvSafe, PRESETS, presetTest, toRow, totalRow, type ActivityRow, type PresetId } from './activity'
import { ASK_COLUMNS, describeFilter, describeSort, toFilterModel, type AskFilter, type AskResult, type AskSort } from './ask'

const ASK_EXAMPLES = [
  'High-risk payments that I declined',
  'Payments over $300 still waiting for a decision',
  'Bank impersonation attempts',
]

ModuleRegistry.registerModules([
  CellStyleModule,
  ClientSideRowModelModule,
  ClientSideRowModelApiModule,
  ColumnApiModule,
  CsvExportModule,
  DateFilterModule,
  ExternalFilterModule,
  GridStateModule,
  HighlightChangesModule,
  NumberFilterModule,
  PinnedRowModule,
  QuickFilterModule,
  RowStyleModule,
  TextFilterModule,
  TooltipModule,
  ...(import.meta.env.DEV ? [ValidationModule] : []),
])

// Same sizes in both modes; colours follow the app's light and dark tokens (index.css).
const gridBase = {
  fontFamily: 'inherit',
  fontSize: 16,
  headerFontSize: 15,
  rowHeight: 52,
  headerHeight: 50,
  wrapperBorderRadius: 16,
}
const GRID_THEMES = {
  light: themeQuartz.withParams({
    ...gridBase,
    browserColorScheme: 'light',
    accentColor: '#5b3fe0',
    backgroundColor: '#ffffff',
    foregroundColor: '#17132e',
    headerBackgroundColor: '#f6f4fd',
    borderColor: '#e0dcf0',
  }),
  dark: themeQuartz.withParams({
    ...gridBase,
    browserColorScheme: 'dark',
    accentColor: '#a593ff',
    backgroundColor: '#1c1544',
    foregroundColor: '#f2effd',
    headerBackgroundColor: '#251d55',
    borderColor: '#342b6a',
  }),
}

// Remembered per browser: column widths, order, sort and filters, plus the chosen preset view.
const STATE_KEY = 'safepay.activity.grid.v1'
const PRESET_KEY = 'safepay.activity.preset.v1'

function load<T>(key: string): T | undefined {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : undefined
  } catch {
    return undefined
  }
}

function save(key: string, value: unknown) {
  try {
    if (value === undefined) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* private window or storage blocked: the grid still works, it just won't remember */
  }
}

/** "3:02 PM" for today, "Nov 8, 3:02 PM" otherwise. */
function shortTime(d: Date): string {
  if (Number.isNaN(d.getTime())) return ''
  const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  if (d.toDateString() === new Date().toDateString()) return time
  return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}, ${time}`
}

const reviewHref = (r: ActivityRow) => `#/guardian/p/${r.id}`

function RiskCell({ value, data }: ICellRendererParams<ActivityRow, Level | null>) {
  if (data?.isTotal) return null
  return value ? <RiskBadge level={value} suffix="" compact /> : null
}

function PayeeCell({ value, data }: ICellRendererParams<ActivityRow, string>) {
  if (!data) return null
  if (data.isTotal) return <strong>{value}</strong>
  return <a href={reviewHref(data)}>{value}</a>
}

function EvidenceCell({ value, data }: ICellRendererParams<ActivityRow, string>) {
  if (!data || data.isTotal || !value) return null
  return <q className="grid-quote">{value}</q>
}

function ActionCell({ data }: ICellRendererParams<ActivityRow>) {
  if (!data || data.isTotal) return null
  return data.waiting ? (
    <a className="grid-action grid-action-primary" href={reviewHref(data)}>
      Review →
    </a>
  ) : (
    <a className="grid-action" href={reviewHref(data)}>
      Open
    </a>
  )
}

/** Hover tooltip: the plain-language summary and every quoted piece of evidence. */
function EvidenceTooltip({ data }: ITooltipParams<ActivityRow>) {
  if (!data || data.isTotal) return null
  return (
    <div className="grid-tip" role="tooltip">
      {data.summary && <p className="grid-tip-summary">{data.summary}</p>}
      {data.evidence.length > 0 ? (
        <ul>
          {data.evidence.map((q, i) => (
            <li key={i}>
              <span className={`chip chip-${q.source}`}>{q.source === 'ai' ? 'AI' : 'Rule'}</span> “{q.evidence}”
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No quoted warning signs.</p>
      )}
      <p className="muted small">Checked by: {data.checkedBy}</p>
    </div>
  )
}

// AG Grid v36.2+: `tooltip` with a callback (tooltipValueGetter is deprecated).
const tooltip = (p: TooltipCallbackParams<ActivityRow>) => (p.data && !p.data.isTotal ? 'evidence' : null)

const columns: ColDef<ActivityRow>[] = [
  {
    colId: 'created',
    field: 'created',
    headerName: 'Time',
    sort: 'desc',
    valueFormatter: (p) => (p.data?.isTotal ? 'Totals' : shortTime(p.value)),
    filter: 'agDateColumnFilter',
    filterParams: { comparator: compareDay },
    minWidth: 140,
  },
  { colId: 'payee', field: 'payee', headerName: 'Payee', cellRenderer: PayeeCell, filter: 'agTextColumnFilter', minWidth: 170 },
  {
    colId: 'amount',
    field: 'amount',
    headerName: 'Amount',
    type: 'rightAligned',
    filter: 'agNumberColumnFilter',
    valueFormatter: (p) => money(String(p.value)),
    minWidth: 120,
  },
  {
    colId: 'level',
    field: 'level',
    headerName: 'Risk',
    cellRenderer: RiskCell,
    filter: 'agTextColumnFilter',
    comparator: (a: Level | null, b: Level | null) => (a ? LEVEL_ORDER[a] : -1) - (b ? LEVEL_ORDER[b] : -1),
    tooltip,
    tooltipComponent: EvidenceTooltip,
    minWidth: 130,
  },
  {
    colId: 'category',
    field: 'category',
    headerName: 'Looks like',
    filter: 'agTextColumnFilter',
    tooltip,
    tooltipComponent: EvidenceTooltip,
    minWidth: 180,
  },
  {
    colId: 'evidence',
    field: 'topEvidence',
    headerName: 'Top evidence',
    cellRenderer: EvidenceCell,
    filter: 'agTextColumnFilter',
    tooltip,
    tooltipComponent: EvidenceTooltip,
    minWidth: 200,
  },
  { colId: 'status', field: 'status', headerName: 'Status', filter: 'agTextColumnFilter', enableCellChangeFlash: true, minWidth: 175 },
  { colId: 'decision', field: 'decision', headerName: 'Decision', filter: 'agTextColumnFilter', enableCellChangeFlash: true, minWidth: 195 },
  { colId: 'decidedBy', field: 'decidedBy', headerName: 'Decided by', filter: 'agTextColumnFilter', minWidth: 140 },
  { colId: 'checkedBy', field: 'checkedBy', headerName: 'Checked by', filter: 'agTextColumnFilter', minWidth: 150 },
  {
    colId: 'voidsIn',
    field: 'voidsIn',
    headerName: 'Voids in',
    filter: 'agNumberColumnFilter',
    valueFormatter: (p) => (p.value == null ? '' : duration(p.value)),
    minWidth: 130,
  },
  {
    colId: 'action',
    headerName: '',
    cellRenderer: ActionCell,
    pinned: 'right',
    sortable: false,
    filter: false,
    floatingFilter: false,
    resizable: false,
    width: 125,
    minWidth: 125,
    maxWidth: 125,
    flex: 0,
  },
]

const rowClassRules: RowClassRules<ActivityRow> = {
  'row-total': (p) => !!p.data?.isTotal,
  'row-waiting': (p) => !!p.data?.waiting,
  'row-stopped': (p) => p.data?.statusCode === 'VOIDED' || p.data?.statusCode === 'EXPIRED',
  'row-seed': (p) => !!p.data?.isSeed,
}

// Exported to CSV in this order; evidence is expanded to every quote, not just the first.
const CSV_COLUMNS = ['created', 'payee', 'amount', 'level', 'category', 'evidence', 'status', 'decision', 'decidedBy', 'checkedBy']

// The most payments loaded at once. If the list is exactly this long there may be older ones that are not shown.
const ACTIVITY_LIMIT = 500

export function ActivityPage() {
  const theme = GRID_THEMES[useTheme()]
  const poll = usePoll(() => api.listPayments({ limit: ACTIVITY_LIMIT }), 3000, 'guardian-activity')
  const gridRef = useRef<AgGridReact<ActivityRow>>(null)
  const [search, setSearch] = useState('')
  const [preset, setPreset] = useState<PresetId>(() => load<PresetId>(PRESET_KEY) ?? 'all')
  const presetRef = useRef(preset)
  const [pinned, setPinned] = useState<ActivityRow[]>([])
  const rows = useMemo(() => (poll.data ?? []).map(toRow), [poll.data])
  const initialState = useMemo(() => load<GridState>(STATE_KEY), [])
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [asked, setAsked] = useState<AskResult | null>(null)

  const counts = useMemo(
    () => Object.fromEntries(PRESETS.map((p) => [p.id, rows.filter(p.test).length])) as Record<PresetId, number>,
    [rows],
  )

  useEffect(() => {
    presetRef.current = preset
    save(PRESET_KEY, preset)
    gridRef.current?.api?.onFilterChanged()
  }, [preset])

  // Setting the pinned row itself fires "model updated", so only update it when the totals really
  // change; otherwise the grid and React would update each other forever.
  const totalsKey = useRef('')
  const recomputeTotals = useCallback(() => {
    const grid = gridRef.current?.api
    if (!grid) return
    const shown: ActivityRow[] = []
    grid.forEachNodeAfterFilter((n: IRowNode<ActivityRow>) => {
      if (n.data) shown.push(n.data)
    })
    const row = totalRow(shown)
    const key = `${row.payee}|${row.amountCents}|${row.status}|${row.decision}|${row.decidedBy}`
    if (key === totalsKey.current) return
    totalsKey.current = key
    setPinned([row])
  }, [])

  const exportCsv = () => {
    const stamp = new Date().toISOString().slice(0, 10)
    gridRef.current?.api?.exportDataAsCsv({
      fileName: `safepay-activity-${stamp}.csv`,
      columnKeys: CSV_COLUMNS,
      skipPinnedBottom: true,
      // Every cell goes through csvSafe: payee names and quotes are attacker-written text.
      processCellCallback: (p) => {
        const r = p.node?.data as ActivityRow | undefined
        switch (p.column.getColId()) {
          case 'created':
            return r ? r.created.toLocaleString() : ''
          case 'amount':
            return r ? (r.amountCents / 100).toFixed(2) : ''
          case 'evidence':
            return csvSafe(r ? r.evidence.map((q) => `${q.source === 'ai' ? 'AI' : 'Rule'}: "${q.evidence}"`).join('; ') : '')
          default:
            return csvSafe(p.value == null ? '' : String(p.value))
        }
      },
    })
  }

  /** Apply validated filters to the grid. Only the view changes: nothing about a payment is touched. */
  const applyAsked = (filters: AskFilter[], sort: AskSort | null) => {
    const grid = gridRef.current?.api
    if (!grid) return
    setPreset('all')
    setSearch('')
    grid.setFilterModel(filters.length ? (toFilterModel(filters) as FilterModel) : null)
    grid.applyColumnState({
      state: [sort ? { colId: sort.column, sort: sort.direction } : { colId: 'created', sort: 'desc' }],
      defaultState: { sort: null },
    })
  }

  const runAsk = async (q: string) => {
    if (q.trim().length < 2) return
    setAsking(true)
    try {
      const result = await api.askActivity(q.trim(), ASK_COLUMNS)
      setAsked(result)
      if (!result.error) applyAsked(result.filters, result.sort)
    } catch (err) {
      setAsked({ understood: false, explanation: '', filters: [], sort: null, ignored: [], model: null, cached: false,
        latency_ms: null, error: (err as Error).message })
    } finally {
      setAsking(false)
    }
  }

  const removeChip = (index: number) => {
    if (!asked) return
    const filters = asked.filters.filter((_, i) => i !== index)
    setAsked({ ...asked, filters })
    applyAsked(filters, asked.sort)
  }

  const clearAsked = () => {
    setAsked(null)
    setQuestion('')
    applyAsked([], null)
  }

  const resetView = () => {
    const grid = gridRef.current?.api
    setAsked(null)
    setQuestion('')
    save(STATE_KEY, undefined)
    setSearch('')
    setPreset('all')
    grid?.setFilterModel(null)
    grid?.resetColumnState()
  }

  const onKeyDown = (e: CellKeyDownEvent<ActivityRow>) => {
    const key = (e.event as KeyboardEvent | null)?.key
    if (key === 'Enter' && e.data && !e.data.isTotal) go(`/guardian/p/${e.data.id}`)
  }

  return (
    <section className="card activity">
      <h1>Activity</h1>
      <p className="muted">
        Every payment, live. Hover a risk or evidence cell to see why it was flagged; press Enter or use Review to open
        it. Decisions are made on the review page, where the full evidence is.
      </p>
      {rows.length >= ACTIVITY_LIMIT && (
        <p className="banner banner-info" role="status">
          Showing the latest {ACTIVITY_LIMIT} payments. Older ones are not loaded, so filters, totals and the CSV report
          leave them out.
        </p>
      )}

      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault()
          void runAsk(question)
        }}
      >
        <label htmlFor="ask-question">Ask about your activity</label>
        <div className="row">
          <input
            id="ask-question"
            value={question}
            maxLength={300}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="For example: high-risk payments over $200 that I declined"
            autoComplete="off"
          />
          <button type="submit" className="btn btn-primary" disabled={asking || question.trim().length < 2}>
            {asking ? 'Thinking…' : 'Ask'}
          </button>
        </div>
        <div className="suggestions" aria-label="Example questions">
          {ASK_EXAMPLES.map((q) => (
            <button
              key={q}
              type="button"
              className="suggestion"
              disabled={asking}
              onClick={() => {
                setQuestion(q)
                void runAsk(q)
              }}
            >
              {q}
            </button>
          ))}
        </div>
        <div aria-live="polite">
          {asked?.error && <p className="ask-error">{asked.error}</p>}
          {asked && !asked.error && (
            <div className="ask-result">
              {asked.explanation && <p>{asked.explanation}</p>}
              <ul className="ask-chips">
                {asked.filters.map((f, i) => (
                  <li key={`${f.column}-${i}`}>
                    <span>{describeFilter(f)}</span>
                    <button type="button" aria-label={`Remove: ${describeFilter(f)}`} onClick={() => removeChip(i)}>
                      ✕
                    </button>
                  </li>
                ))}
                {asked.sort && (
                  <li>
                    <span>{describeSort(asked.sort)}</span>
                  </li>
                )}
              </ul>
              {asked.ignored.length > 0 && (
                <p className="muted small">Not used: {asked.ignored.map((i) => i.reason).join('; ')}.</p>
              )}
              <p className="muted small">
                {asked.cached ? 'Stored AI reply' : `Answered by ${asked.model ?? 'the AI'}`}. It only filters this
                table; nothing about a payment is changed.{' '}
                <button type="button" className="btn-link" onClick={clearAsked}>
                  Clear
                </button>
              </p>
            </div>
          )}
        </div>
      </form>

      <div className="presets" role="group" aria-label="Preset views">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            className="preset"
            aria-pressed={preset === p.id}
            onClick={() => setPreset(p.id)}
          >
            {p.label} <span className="preset-count">{counts[p.id] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="grid-toolbar">
        <div className="field grid-search">
          <label htmlFor="activity-search">Search all columns</label>
          <input
            id="activity-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="For example: gift, declined, Officer"
          />
        </div>
        <div className="grid-buttons">
          <button type="button" className="btn btn-secondary" onClick={exportCsv}>
            Download report (CSV)
          </button>
          <button type="button" className="btn btn-quiet" onClick={resetView}>
            Reset view
          </button>
        </div>
      </div>

      <ErrorNote error={poll.error} />
      {poll.data && poll.data.length === 0 && (
        <div className="banner banner-info" role="status">
          <strong>There are no payments in this database yet.</strong> Send one from the sender side, or load the demo
          history with <code>scripts/reset_demo.py</code> (see the README). If you expected payments here, check that
          the backend was started with the right <code>DATABASE_PATH</code>.
        </div>
      )}
      <div className="grid-box">
        <AgGridReact<ActivityRow>
          ref={gridRef}
          theme={theme}
          rowData={rows}
          columnDefs={columns}
          defaultColDef={{ sortable: true, resizable: true, flex: 1, floatingFilter: true }}
          getRowId={(p) => p.data.id}
          quickFilterText={search}
          isExternalFilterPresent={() => presetRef.current !== 'all'}
          doesExternalFilterPass={(node) => !!node.data && presetTest(presetRef.current)(node.data)}
          pinnedBottomRowData={pinned}
          rowClassRules={rowClassRules}
          initialState={initialState}
          onStateUpdated={(e) => {
            const { sort, filter, columnSizing, columnOrder } = e.state
            save(STATE_KEY, { sort, filter, columnSizing, columnOrder })
          }}
          onModelUpdated={recomputeTotals}
          onCellKeyDown={onKeyDown}
          tooltipShowDelay={250}
          tooltipInteraction
          ensureDomOrder
          overlayNoRowsTemplate="No payments match this view."
        />
      </div>
    </section>
  )
}
