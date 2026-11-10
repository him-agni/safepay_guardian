import { useId, useMemo, useState, type ReactNode } from 'react'
import {
  BarSeriesModule,
  CategoryAxisModule,
  LegendModule,
  NumberAxisModule,
  type AgCartesianChartOptions,
  type AgChartThemeOverrides,
} from 'ag-charts-community'
import { AgCharts } from 'ag-charts-react'
import { categoryLabel, money } from '../format'
import type { Stats } from '../types'
import { dailyOutcomes, plural, type DayOutcomes } from './insights'

// Only what these three bar charts use, so the Insights bundle stays small.
const MODULES = [BarSeriesModule, CategoryAxisModule, NumberAxisModule, LegendModule]

// Single-series charts use the brand blue. The timeline's three outcomes use a categorical palette checked
// for colour-vision deficiency (worst adjacent pair ΔE 9.2). Aqua is below 3:1 contrast on white, so the
// chart always has a legend and a table view.
const BRAND = '#0b4fa3'
const OUTCOME_COLOURS = { captured: '#2a78d6', stopped: '#eb6834', open: '#1baf7a' }

const THEME: AgChartThemeOverrides = {
  common: {
    background: { fill: '#ffffff' },
    padding: { top: 8, right: 16, bottom: 8, left: 8 },
  },
}

const baseOptions = {
  theme: {
    baseTheme: 'ag-default',
    params: {
      fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif",
      fontSize: 13,
      textColor: '#14181f',
      subtleTextColor: '#5b6474',
      gridLineColor: '#e3e7ee',
    },
    overrides: THEME,
  },
  animation: { enabled: false },
  // The card sets the height; without this AG Charts keeps its 300px default minimum.
  minHeight: 0,
} satisfies Partial<AgCartesianChartOptions>

/** Counts are whole payments: keep axis ticks on whole numbers. */
const countAxis = {
  type: 'number' as const,
  nice: true,
  interval: { minSpacing: 40 },
  label: { formatter: ({ value }: { value: unknown }) => (Number.isInteger(value) ? String(value) : '') },
}

// Axes are bound by key, not by role: for horizontal bars the category axis (x) sits on the left and the
// count axis (y) along the bottom.
const horizontalAxes = {
  // Thin bars: more than half of each row is gap.
  x: {
    type: 'category' as const,
    position: 'left' as const,
    paddingInner: 0.55,
    paddingOuter: 0.3,
    // Long names ("Government impersonation") wrap onto two lines instead of being cut off on phones.
    label: { maxWidth: 120, wrapping: 'on-space' as const },
  },
  y: { ...countAxis, position: 'bottom' as const },
}

function ChartCard({ title, caption, chart, table, height }: {
  title: string
  caption: ReactNode
  chart: ReactNode
  table: ReactNode
  height: number
}) {
  const [asTable, setAsTable] = useState(false)
  const id = useId()
  return (
    <section className="card" aria-labelledby={`${id}-title`}>
      <div className="chart-head">
        <h2 id={`${id}-title`}>{title}</h2>
        <button type="button" className="btn btn-small" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>
          {asTable ? 'Show as a chart' : 'Show as a table'}
        </button>
      </div>
      <p className="muted">{caption}</p>
      {asTable ? (
        <div className="table-scroll">{table}</div>
      ) : (
        <div className="chart" style={{ height }} role="img" aria-label={`${title}. Use “Show as a table” to read the values.`}>
          {chart}
        </div>
      )}
    </section>
  )
}

const TIMELINE_HEIGHT = 300
const barHeight = (rows: number) => Math.max(140, rows * 40 + 64)

export function CategoryChart({ stats }: { stats: Stats }) {
  const rows = useMemo(
    () => stats.top_categories.map((r) => ({ label: categoryLabel(r.category), count: r.count, total: r.total })),
    [stats.top_categories],
  )
  const options = useMemo<AgCartesianChartOptions>(
    () => ({
      ...baseOptions,
      data: rows,
      height: barHeight(rows.length),
      series: [
        {
          type: 'bar',
          direction: 'horizontal',
          xKey: 'label',
          yKey: 'count',
          yName: 'Payments',
          fill: BRAND,
          cornerRadius: 4,
          tooltip: {
            renderer: ({ datum }) => ({
              title: datum.label,
              data: [
                { label: 'Warned or held', value: plural(datum.count, 'payment') },
                { label: 'Amount', value: money(datum.total) },
              ],
            }),
          },
        },
      ],
      axes: horizontalAxes,
    }),
    [rows],
  )
  return (
    <ChartCard
      title="Top scam categories"
      caption="Payments that were warned or held, grouped by what they looked like."
      height={barHeight(rows.length)}
      chart={
        rows.length ? (
          <AgCharts options={options} modules={MODULES} />
        ) : (
          <p className="muted">No payments have been warned or held yet.</p>
        )
      }
      table={
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Looks like</th>
              <th scope="col">Warned or held</th>
              <th scope="col">Amount</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label}>
                <th scope="row">{r.label}</th>
                <td>{r.count}</td>
                <td>{money(r.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  )
}

const OUTCOMES = [
  { key: 'captured', name: 'Captured' },
  { key: 'stopped', name: 'Stopped, not captured' },
  { key: 'open', name: 'Still open' },
] as const

export function TimelineChart({ stats }: { stats: Stats }) {
  const days = useMemo(() => dailyOutcomes(stats.recent, stats.recent_days), [stats.recent, stats.recent_days])
  const hasPast = days.some((d) => d.past > 0)
  const options = useMemo<AgCartesianChartOptions>(
    () => ({
      ...baseOptions,
      data: days,
      height: TIMELINE_HEIGHT,
      series: OUTCOMES.map(({ key, name }) => ({
        type: 'bar' as const,
        xKey: 'label',
        yKey: key,
        yName: name,
        stacked: true,
        fill: OUTCOME_COLOURS[key],
        stroke: '#ffffff',
        strokeWidth: 2,
        cornerRadius: 4,
        tooltip: {
          renderer: ({ datum }: { datum: DayOutcomes }) => ({
            title: datum.label,
            data: [
              ...OUTCOMES.map((o) => ({ label: o.name, value: String(datum[o.key]) })),
              ...(datum.past ? [{ label: 'From past history', value: String(datum.past) }] : []),
            ],
          }),
        },
      })),
      axes: { x: { type: 'category', paddingInner: 0.35, label: { avoidCollisions: true } }, y: countAxis },
      legend: { enabled: true, position: 'bottom' },
    }),
    [days],
  )
  return (
    <ChartCard
      title="Payments over time"
      caption={
        <>
          What happened to each payment, by day, for the last {stats.recent_days} days.
          {hasPast && ' Includes earlier payments from your history.'}
        </>
      }
      height={TIMELINE_HEIGHT}
      chart={
        days.length ? (
          <AgCharts options={options} modules={MODULES} />
        ) : (
          <p className="muted">No payments in the last {stats.recent_days} days.</p>
        )
      }
      table={
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Day</th>
              {OUTCOMES.map((o) => (
                <th key={o.key} scope="col">
                  {o.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {days
              .filter((d) => d.captured + d.stopped + d.open > 0)
              .map((d) => (
                <tr key={d.day}>
                  <th scope="row">
                    {d.label}
                    {d.past > 0 && <span className="muted"> (past history)</span>}
                  </th>
                  {OUTCOMES.map((o) => (
                    <td key={o.key}>{d[o.key]}</td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      }
    />
  )
}

export function FlaggedPayeesChart({ stats }: { stats: Stats }) {
  const rows = stats.flagged_payees
  const options = useMemo<AgCartesianChartOptions>(
    () => ({
      ...baseOptions,
      data: rows,
      height: barHeight(rows.length),
      series: [
        {
          type: 'bar',
          direction: 'horizontal',
          xKey: 'payee',
          yKey: 'count',
          yName: 'Warned or held',
          fill: BRAND,
          cornerRadius: 4,
          tooltip: {
            renderer: ({ datum }) => ({
              title: datum.payee,
              data: [
                { label: 'Warned or held', value: plural(datum.count, 'payment') },
                { label: 'Not captured', value: String(datum.not_captured) },
                { label: 'Amount', value: money(datum.total) },
              ],
            }),
          },
        },
      ],
      axes: horizontalAxes,
    }),
    [rows],
  )
  return (
    <ChartCard
      title="Recipients flagged most often"
      caption="Payees whose payments were warned or held. A name that keeps coming back is worth a conversation."
      height={barHeight(rows.length)}
      chart={
        rows.length ? (
          <AgCharts options={options} modules={MODULES} />
        ) : (
          <p className="muted">No recipients have been flagged yet.</p>
        )
      }
      table={
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Payee</th>
              <th scope="col">Warned or held</th>
              <th scope="col">Not captured</th>
              <th scope="col">Amount</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.payee}>
                <th scope="row">{r.payee}</th>
                <td>{r.count}</td>
                <td>{r.not_captured}</td>
                <td>{money(r.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  )
}
