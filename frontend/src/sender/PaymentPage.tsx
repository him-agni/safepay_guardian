import { useState } from 'react'
import { api, ApiError } from '../api'
import { AiBanner, ErrorNote, HighlightedText, MessageThread, RiskBadge } from '../components'
import { duration, money, reasons, summaryRepeatsReasons } from '../format'
import { useCountdown, usePoll } from '../hooks'
import { recall, remember } from '../store'
import type { Action, Payment } from '../types'

export function PaymentPage({ id }: { id: string }) {
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
  const [busy, setBusy] = useState<Action | null>(null)
  const [actionError, setActionError] = useState<Error | null>(null)
  const p = poll.data ?? initial

  const update = (next: Payment) => {
    remember(next)
    poll.setData(next)
    setFinal(next.final)
  }

  const act = async (action: Action) => {
    if (!p) return
    setBusy(action)
    setActionError(null)
    try {
      update(await api.act(p.id, action))
    } catch (err) {
      if (err instanceof ApiError && err.payment) update(err.payment)
      setActionError(err as Error)
    } finally {
      setBusy(null)
    }
  }

  if (!p) {
    return (
      <section className="card">
        <ErrorNote error={poll.error} />
        {!poll.error && <p aria-live="polite">Loading your payment…</p>}
      </section>
    )
  }

  return (
    <div className="stack">
      <a href="#/send" className="back">
        ← Send another payment
      </a>
      <ErrorNote error={poll.error} />
      <StatusCard p={p} busy={busy} onAct={act} actionError={actionError} onUpdate={update} />
    </div>
  )
}

function Summary({ p }: { p: Payment }) {
  return (
    <p className="amount-line">
      <strong>{money(p.amount)}</strong> to <strong>{p.payee.name}</strong>
      {p.note && <span className="muted"> · {p.note}</span>}
    </p>
  )
}

function Reasons({ p, heading }: { p: Payment; heading: string }) {
  const list = reasons(p)
  const summary = p.risk?.summary ?? ''
  // When the AI's summary isn't used, the summary is just some of the reasons joined together:
  // don't say the same sentences twice.
  const showSummary = !!summary && !summaryRepeatsReasons(summary, list)
  if (!list.length && !summary) return null
  return (
    <div className="reasons">
      <h2>{heading}</h2>
      {showSummary && <p>{summary}</p>}
      {list.length > 0 && (
        <ul>
          {list.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Evidence({ p }: { p: Payment }) {
  const spans = p.risk?.evidence_spans ?? []
  return (
    <>
      <HighlightedText text={p.message_text} spans={spans} field="message" label="The message you received" />
      <HighlightedText text={p.note} spans={spans} field="note" label="Your note" />
    </>
  )
}

function GuardianNote({ p }: { p: Payment }) {
  if (!p.decision_note || p.decided_by !== 'guardian') return null
  return (
    <div className="guardian-note">
      <span className="who">Message from your guardian</span>
      <p>{p.decision_note}</p>
    </div>
  )
}

function Countdown({ seconds, what }: { seconds: number | null; what: string }) {
  const left = useCountdown(seconds)
  if (left == null) return null
  return (
    <p className="muted">
      {what} in {duration(left)}.
    </p>
  )
}

function StatusCard({
  p,
  busy,
  onAct,
  actionError,
  onUpdate,
}: {
  p: Payment
  busy: Action | null
  onAct: (a: Action) => void
  actionError: Error | null
  onUpdate: (p: Payment) => void
}) {
  const level = p.risk?.level ?? p.risk_level
  const heading = <h1 aria-live="polite">{p.text.sender}</h1>

  switch (p.status) {
    case 'CAPTURED':
      return (
        <section className="card result result-ok">
          <div className="result-icon" aria-hidden="true">
            ✓
          </div>
          {heading}
          <Summary p={p} />
          {p.decided_by === 'guardian' && <p>Your guardian looked at it and approved it.</p>}
          <GuardianNote p={p} />
          <AiBanner risk={p.risk} />
        </section>
      )

    case 'WARNED':
      return (
        <section className="card result result-warn">
          <div className="result-head">
            {level && <RiskBadge level={level} />}
            <h1 aria-live="polite">Please check this payment before it is sent</h1>
          </div>
          <Summary p={p} />
          <AiBanner risk={p.risk} />
          <Reasons p={p} heading="Why we are asking" />
          <Evidence p={p} />
          <p className="lead">If you know this person and expected this payment, you can send it.</p>
          <ErrorNote error={actionError} />
          <div className="actions">
            <button className="btn btn-primary" disabled={!!busy} onClick={() => onAct('confirm')}>
              {busy === 'confirm' ? 'Sending…' : 'Yes, send it'}
            </button>
            <button className="btn btn-secondary" disabled={!!busy} onClick={() => onAct('cancel')}>
              {busy === 'cancel' ? 'Cancelling…' : 'No, cancel it'}
            </button>
          </div>
          <Countdown seconds={p.hold_seconds_left} what="If you do nothing, it will be cancelled" />
        </section>
      )

    case 'HELD':
      return (
        <section className="card result result-hold">
          <div className="result-head">
            {level && <RiskBadge level={level} />}
            <h1 aria-live="polite">This payment is on hold</h1>
          </div>
          <p className="lead">
            No money has been sent. Your guardian was asked to look at it. Here is why.
          </p>
          <Summary p={p} />
          <AiBanner risk={p.risk} />
          <Reasons p={p} heading="Why it is on hold" />
          <Evidence p={p} />
          <MessageThread
            payment={p}
            role="sender"
            onUpdate={onUpdate}
            prompt={(p.messages ?? []).some((m) => m.from_role === 'guardian') ? 'Reply to your guardian' : 'Send your guardian a message (optional)'}
          />
          <p className="muted">This page updates by itself.</p>
          <Countdown seconds={p.hold_seconds_left} what="If your guardian does not answer, it will be declined" />
          <ErrorNote error={actionError} />
          <div className="actions">
            <button className="btn btn-secondary" disabled={!!busy} onClick={() => onAct('cancel')}>
              {busy === 'cancel' ? 'Cancelling…' : 'Cancel this payment'}
            </button>
          </div>
        </section>
      )

    case 'VOIDED':
    case 'EXPIRED':
    case 'AUTH_FAILED':
      return (
        <section className="card result result-stop">
          <div className="result-icon" aria-hidden="true">
            ✕
          </div>
          {heading}
          <Summary p={p} />
          <GuardianNote p={p} />
          {p.risk && p.status !== 'AUTH_FAILED' && <Reasons p={p} heading="What we noticed" />}
        </section>
      )

    default:
      // CREATED, AUTHORIZED, CAPTURING, VOIDING, CAPTURE_FAILED, VOID_FAILED
      return (
        <section className="card result">
          {heading}
          <Summary p={p} />
          <GuardianNote p={p} />
          {!p.final && <p className="muted">This page updates by itself.</p>}
        </section>
      )
  }
}
