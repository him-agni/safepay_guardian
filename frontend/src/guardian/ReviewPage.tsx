import { useState } from 'react'
import { api, ApiError } from '../api'
import { AiBanner, ErrorNote, HighlightedText, MessageThread, RiskBadge, ScreenshotFigure } from '../components'
import { categoryLabel, clockTime, duration, money, timeAgo } from '../format'
import { useCountdown, usePoll } from '../hooks'
import { recall, remember } from '../store'
import type { Action, Indicator, Payment, PaymentEvent } from '../types'
import { describeEvent } from './events'

const ASK = ['Did you speak to this person on the phone?', 'Do you know this person?', 'Who asked you to send this?']

export function ReviewPage({ id }: { id: string }) {
  const initial = recall(id)
  const [final, setFinal] = useState(initial?.final ?? false)
  const poll = usePoll(
    () =>
      api.getPayment(id).then((p) => {
        setFinal(p.final)
        return remember(p)
      }),
    3000,
    id,
    !final,
  )
  const p = poll.data ?? initial

  const update = (next: Payment) => {
    remember(next)
    poll.setData(next)
    setFinal(next.final)
  }

  if (!p) {
    return (
      <section className="card">
        <ErrorNote error={poll.error} />
        {!poll.error && <p aria-live="polite">Loading the payment…</p>}
      </section>
    )
  }

  return (
    <div className="stack">
      <a href="#/guardian" className="back">
        ← Back to the queue
      </a>
      <ErrorNote error={poll.error} />
      <Overview p={p} />
      <Decision p={p} onUpdate={update} />
      <Evidence p={p} />
      <section className="card">
        <h2>Ask the payer</h2>
        {!p.final && <p className="muted">The sender sees your question on their screen and can reply.</p>}
        <MessageThread
          payment={p}
          role="guardian"
          onUpdate={update}
          prompt="Your question"
          suggestions={ASK}
          closed={p.final}
        />
      </section>
      <AuditLog events={p.events ?? []} />
    </div>
  )
}

function payeeHistory(p: Payment): string {
  const n = p.payee.captured_payments ?? 0
  const paid = n > 0 ? `paid ${n} time${n === 1 ? '' : 's'} before (${money(p.payee.captured_total ?? '0')})` : ''
  if (p.payee.trusted) return `Trusted payee${paid ? `, ${paid}` : ''}`
  return paid ? paid.charAt(0).toUpperCase() + paid.slice(1) : 'New payee: never paid before'
}

function HoldTimer({ seconds }: { seconds: number | null }) {
  const left = useCountdown(seconds)
  if (left == null) return null
  return (
    <p className="timer">
      If you do not decide, the authorization is voided in <strong>{duration(left)}</strong>.
    </p>
  )
}

function Overview({ p }: { p: Payment }) {
  const risk = p.risk
  const level = risk?.level ?? p.risk_level
  return (
    <section className={`card review-head review-${level ?? 'low'}`}>
      <div className="review-badges">
        {level && <RiskBadge level={level} />}
        {risk && (
          <span className="score" title={risk.score_label}>
            Score {risk.score}/100 <span className="muted">· heuristic, not a probability</span>
          </span>
        )}
      </div>
      <h1 aria-live="polite">{p.text.guardian}</h1>
      <p className="amount-line">
        <strong>{money(p.amount)}</strong> to <strong>{p.payee.name}</strong>
        {p.note && <span className="muted"> · “{p.note}”</span>}
      </p>
      <dl className="facts">
        <div>
          <dt>Payee</dt>
          <dd>{payeeHistory(p)}</dd>
        </div>
        <div>
          <dt>Looks like</dt>
          <dd>{categoryLabel(risk?.category ?? p.category)}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>
            {clockTime(p.created_at)} ({timeAgo(p.created_at)})
          </dd>
        </div>
        {p.paypal.authorization_id && (
          <div>
            <dt>PayPal authorization</dt>
            <dd className="mono">{p.paypal.authorization_id}</dd>
          </div>
        )}
      </dl>
      <HoldTimer seconds={p.hold_seconds_left} />
      <AiBanner risk={risk} />
      {risk?.summary && <p className="summary">{risk.summary}</p>}
    </section>
  )
}

function Decision({ p, onUpdate }: { p: Payment; onUpdate: (p: Payment) => void }) {
  const [note, setNote] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState<Action | null>(null)
  const [error, setError] = useState<Error | null>(null)

  const act = async (action: Action) => {
    setBusy(action)
    setError(null)
    try {
      onUpdate(await api.act(p.id, action, note.trim() || undefined))
      setConfirming(false)
    } catch (err) {
      if (err instanceof ApiError && err.payment) onUpdate(err.payment)
      setError(err as Error)
    } finally {
      setBusy(null)
    }
  }

  if (p.final || (!p.can.approve && !p.can.decline && !p.can.retry)) {
    return (
      <section className="card decision decision-done">
        <h2>Outcome</h2>
        <p>{p.text.guardian}</p>
        {p.decided_by && (
          <p className="muted">
            Decided by {p.decided_by === 'system' ? 'the system (hold timed out)' : `the ${p.decided_by}`}
            {p.decided_at ? ` at ${clockTime(p.decided_at)}` : ''}.
          </p>
        )}
        {p.decision_note && <p>Note to the sender: “{p.decision_note}”</p>}
        {p.last_error && <p className="muted">{p.last_error}</p>}
        <ErrorNote error={error} />
      </section>
    )
  }

  return (
    <section className="card decision">
      <h2>Your decision</h2>
      {p.status === 'CAPTURE_FAILED' && (
        <div className="banner banner-error" role="alert">
          The capture failed: {p.last_error}. You can retry, or decline to void the authorization.
        </div>
      )}
      {p.status === 'CAPTURE_PENDING' && (
        <div className="banner banner-info">
          The capture was sent and PayPal still shows it as pending. It is checked again every few seconds and
          cannot be changed now.
        </div>
      )}
      {p.status === 'VOID_FAILED' && (
        <div className="banner banner-error" role="alert">
          The void failed: {p.last_error}. It is retried automatically; the payment will not be captured.
        </div>
      )}
      {(p.can.approve || p.can.decline) && (
        <div className="field">
          <label htmlFor={`note-${p.id}`}>Note to the sender (optional)</label>
          <input
            id={`note-${p.id}`}
            value={note}
            maxLength={500}
            onChange={(e) => setNote(e.target.value)}
            placeholder="For example: This is a scam. I will call you tonight."
          />
        </div>
      )}
      <ErrorNote error={error} />
      {confirming ? (
        <div className="confirm" role="group" aria-label="Confirm approval">
          <p>
            <strong>
              Capture {money(p.amount)} to {p.payee.name}?
            </strong>{' '}
            The money will be taken from the sender.
          </p>
          <div className="actions">
            <button className="btn btn-primary" disabled={!!busy} onClick={() => act('approve')}>
              {busy === 'approve' ? 'Capturing…' : 'Yes, approve and capture'}
            </button>
            <button className="btn btn-secondary" disabled={!!busy} onClick={() => setConfirming(false)}>
              Back
            </button>
          </div>
        </div>
      ) : (
        <div className="actions">
          {p.can.decline && (
            <button className="btn btn-danger" disabled={!!busy} onClick={() => act('decline')}>
              {busy === 'decline' ? 'Voiding…' : 'Decline and void'}
            </button>
          )}
          {p.can.approve && (
            <button className="btn btn-secondary" disabled={!!busy} onClick={() => setConfirming(true)}>
              Approve…
            </button>
          )}
          {p.can.retry && (
            <button className="btn btn-primary" disabled={!!busy} onClick={() => act('retry')}>
              {busy === 'retry' ? 'Retrying…' : p.status === 'VOID_FAILED' ? 'Retry void now' : 'Retry capture'}
            </button>
          )}
        </div>
      )}
    </section>
  )
}

function SourceChip({ ind }: { ind: Indicator }) {
  if (ind.hard) return <span className="chip chip-hard">Hard rule</span>
  return <span className={`chip chip-${ind.source}`}>{ind.source === 'ai' ? 'AI' : 'Rule'}</span>
}

function Evidence({ p }: { p: Payment }) {
  const risk = p.risk
  if (!risk) return null
  const spans = risk.evidence_spans
  const dropped = risk.dropped_evidence.length
  return (
    <section className="card">
      <h2>Why it was flagged</h2>
      {risk.indicators.length === 0 && <p className="muted">No warning signs were found.</p>}
      <ul className="evidence">
        {risk.indicators.map((ind, i) => (
          <li key={`${ind.source}-${ind.type}-${i}`}>
            <SourceChip ind={ind} />
            <div>
              <p className="evidence-label">{ind.label}</p>
              {ind.evidence && (ind.source === 'ai' || ind.evidence !== p.payee.name) && (
                <q className="evidence-quote">{ind.evidence}</q>
              )}
            </div>
          </li>
        ))}
      </ul>
      {risk.patterns.length > 0 && (
        <div className="patterns">
          <h3>Similar known scam pattern</h3>
          <ul>
            {risk.patterns.map((pt) => (
              <li key={pt.id}>
                {pt.title} <span className="muted">({categoryLabel(pt.category)})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <HighlightedText text={p.message_text} spans={spans} field="message" label="The full message the sender received" />
      <HighlightedText text={p.note} spans={spans} field="note" label="The sender's note" />
      {p.screenshot_url && (
        <ScreenshotFigure
          url={p.screenshot_url}
          caption="The screenshot the sender added"
          note="The message text above was read from it by AI and checked by the sender. Compare them here."
        />
      )}
      <p className="muted small">
        Every quoted word above appears in the message or payment.
        {dropped > 0 &&
          ` ${dropped} AI quote${dropped === 1 ? ' was' : 's were'} dropped because ${dropped === 1 ? 'it does' : 'they do'} not appear in the message.`}
        {risk.mode === 'hybrid' && risk.model &&
          ` Checked by rules and ${risk.model}${risk.components?.ai_cached ? ' (stored reply)' : ''}.`}
        {risk.mode === 'rules_only' && ' Checked by rules only.'}
      </p>
    </section>
  )
}

function AuditLog({ events }: { events: PaymentEvent[] }) {
  return (
    <details className="card audit">
      <summary>Audit log ({events.length} steps, including every PayPal call)</summary>
      <ol>
        {events.map((e, i) => (
          <li key={i}>
            <span className="audit-time">{new Date(e.at).toLocaleTimeString()}</span>
            <span className={`audit-actor actor-${e.actor}`}>{e.actor}</span>
            <span>{describeEvent(e)}</span>
          </li>
        ))}
      </ol>
    </details>
  )
}
