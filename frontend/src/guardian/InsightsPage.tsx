import { api } from '../api'
import { ErrorNote, RiskBadge } from '../components'
import { money } from '../format'
import { usePoll } from '../hooks'
import type { Bucket } from '../types'
import { CategoryChart, FlaggedPayeesChart, TimelineChart } from './InsightsCharts'

function Tile({ label, bucket, value, detail, hero }: {
  label: string
  bucket?: Bucket
  value?: number
  detail?: string
  hero?: boolean
}) {
  const count = bucket?.count ?? value ?? 0
  return (
    <div className={`tile${hero ? ' tile-hero' : ''}`}>
      <span className="tile-label">{label}</span>
      <span className="tile-value">{count}</span>
      {(detail || (bucket && bucket.count > 0)) && (
        <span className="tile-detail">{detail ?? `${money(bucket!.total)} in total`}</span>
      )}
    </div>
  )
}

export function InsightsPage() {
  const poll = usePoll(() => api.stats(), 3000, 'guardian-stats')
  const s = poll.data
  return (
    <div className="stack">
      <section className="card">
        <h1>Insights</h1>
        <p className="muted">
          Attempted payments held from capture: warned or held, then not captured. We cannot prove each one was a
          scam, so this counts what was stopped, not money saved.
        </p>
        <ErrorNote error={poll.error} />
        {s && (
          <div className="tiles">
            <Tile hero label="Attempted payments held from capture" bucket={s.held_from_capture} />
            <Tile label="Waiting for you now" value={s.on_hold_now} detail="On hold, authorization not captured" />
            <Tile label="Declined by you" bucket={s.declined_by_guardian} />
            <Tile label="Approved by you" bucket={s.approved_by_guardian} />
            <Tile label="Cancelled by the sender" bucket={s.cancelled_by_sender} />
            <Tile label="No answer in time, voided" bucket={s.expired_no_answer} />
          </div>
        )}
      </section>

      {s && <TimelineChart stats={s} />}
      {s && <CategoryChart stats={s} />}
      {s && <FlaggedPayeesChart stats={s} />}

      {s && (
        <section className="card">
          <h2>Risk checks</h2>
          <ul className="level-counts">
            {(['high', 'medium', 'low'] as const).map((lv) => (
              <li key={lv}>
                <RiskBadge level={lv} /> <strong>{s.by_level[lv]}</strong>
              </li>
            ))}
          </ul>
          <p className="muted">
            {s.payments} payment{s.payments === 1 ? '' : 's'} checked. Low risk captured automatically:{' '}
            {s.auto_captured.count}. Sender confirmed a warning: {s.confirmed_by_sender.count}.
            {s.rules_only_checks > 0 &&
              ` ${s.rules_only_checks} check${s.rules_only_checks === 1 ? '' : 's'} ran on rules only because the AI was unavailable.`}
          </p>
        </section>
      )}
    </div>
  )
}
