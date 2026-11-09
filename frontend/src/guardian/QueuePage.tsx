import { ErrorNote, RiskBadge } from '../components'
import { categoryLabel, duration, guardianStatusWord, money, timeAgo } from '../format'
import type { Payment } from '../types'

export function QueuePage({ payments, error }: { payments: Payment[] | null; error: Error | null }) {
  return (
    <section className="card">
      <h1>Payments waiting for you</h1>
      <p className="muted">
        Each payment is authorized on PayPal but not captured. Nothing moves until you approve it, and if nobody
        answers in time the authorization is voided.
      </p>
      <ErrorNote error={error} />
      {payments && payments.length === 0 && (
        <p className="empty">Nothing is waiting for a decision. Held payments appear here.</p>
      )}
      {payments && payments.length > 0 && (
        <ul className="list">
          {payments.map((p) => (
            <li key={p.id}>
              <a href={`#/guardian/p/${p.id}`} className="queue-row">
                {p.risk_level && <RiskBadge level={p.risk_level} />}
                <span className="queue-main">
                  <strong>{money(p.amount)}</strong> to {p.payee.name}
                  <span className="muted"> · {categoryLabel(p.category)}</span>
                </span>
                <span className="queue-meta">
                  {p.status !== 'HELD' && <span className="chip chip-alert">{guardianStatusWord(p)}</span>}
                  <span className="muted">held {timeAgo(p.created_at)}</span>
                  {p.hold_seconds_left != null && (
                    <span className="muted">voids in {duration(p.hold_seconds_left)}</span>
                  )}
                </span>
                <span className="queue-go" aria-hidden="true">
                  Review →
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
