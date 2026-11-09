import { api } from '../api'
import { ErrorNote, RiskBadge } from '../components'
import { money, timeAgo } from '../format'
import { usePoll } from '../hooks'

/** Phase 4 placeholder: a read-only view of the queue. The full guardian screens come in Phase 5. */
export function GuardianPage() {
  const queue = usePoll(() => api.listPayments({ queue: 'guardian' }), 3000, 'guardian-queue')
  return (
    <section className="card">
      <h1>Payments waiting for you</h1>
      <p className="muted">The review screen with approve and decline is being built next.</p>
      <ErrorNote error={queue.error} />
      {queue.data && queue.data.length === 0 && <p>Nothing is waiting for a decision.</p>}
      {queue.data && queue.data.length > 0 && (
        <ul className="list">
          {queue.data.map((p) => (
            <li key={p.id} className="list-row">
              {p.risk_level && <RiskBadge level={p.risk_level} />}
              <span className="list-main">
                <strong>{money(p.amount)}</strong> to {p.payee.name}
              </span>
              <span className="muted">{timeAgo(p.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
