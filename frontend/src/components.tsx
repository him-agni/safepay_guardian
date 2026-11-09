import { useState, type FormEvent } from 'react'
import { api, ApiError } from './api'
import { LEVEL_WORD } from './format'
import { segment } from './highlight'
import type { EvidenceSpan, Level, Payment, Risk } from './types'

const LEVEL_ICON: Record<Level, string> = { low: '●', medium: '▲', high: '■' }

/** Risk is a word plus a shape plus a colour: colour is never the only signal. */
export function RiskBadge({ level, suffix = 'risk', compact = false }: {
  level: Level
  suffix?: string
  compact?: boolean
}) {
  return (
    <span className={`badge badge-${level}${compact ? ' badge-compact' : ''}`}>
      <span aria-hidden="true">{LEVEL_ICON[level]}</span> {LEVEL_WORD[level]}{suffix ? ` ${suffix}` : ''}
    </span>
  )
}

export function AiBanner({ risk }: { risk?: Risk | null }) {
  if (!risk?.ai_unavailable) return null
  return (
    <div className="banner banner-info" role="status">
      <strong>{risk.ai_unavailable_text ?? 'AI check unavailable, rules only'}.</strong> The safety rules still
      checked this payment.
    </div>
  )
}

export function ErrorNote({ error }: { error: Error | null | undefined }) {
  if (!error) return null
  return (
    <div className="banner banner-error" role="alert">
      {error.message}
    </div>
  )
}

/** The message the sender received, with the evidence words highlighted. */
export function HighlightedText({
  text,
  spans,
  field,
  label,
}: {
  text: string
  spans: EvidenceSpan[]
  field: 'message' | 'note'
  label: string
}) {
  if (!text.trim()) return null
  const segs = segment(
    text,
    spans.filter((s) => s.field === field),
  )
  const count = segs.filter((s) => s.marked).length
  return (
    <figure className="quoted">
      <figcaption>
        {label}
        {count > 0 && <span className="muted"> · the highlighted words are why it was flagged</span>}
      </figcaption>
      <blockquote>
        {segs.map((s) =>
          s.marked ? (
            <mark key={s.start} title={s.types.join(', ').replaceAll('_', ' ')}>
              {s.text}
            </mark>
          ) : (
            <span key={s.start}>{s.text}</span>
          ),
        )}
      </blockquote>
    </figure>
  )
}

/** Two-way thread between the guardian and the sender ("Ask the payer"). */
export function MessageThread({
  payment,
  role,
  onUpdate,
  prompt,
  suggestions = [],
  closed = false,
}: {
  payment: Payment
  role: 'sender' | 'guardian'
  onUpdate: (p: Payment) => void
  prompt: string
  suggestions?: string[]
  closed?: boolean
}) {
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const messages = payment.messages ?? []
  const other = role === 'sender' ? 'Your guardian' : 'Sender'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!body.trim()) return
    setBusy(true)
    setError(null)
    try {
      onUpdate(await api.addMessage(payment.id, role, body.trim()))
      setBody('')
    } catch (err) {
      setError(err instanceof ApiError ? err : new Error('Could not send the message.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="thread" aria-label="Messages">
      {messages.length > 0 && (
        <ol className="thread-list">
          {messages.map((m, i) => (
            <li key={i} className={m.from_role === role ? 'mine' : 'theirs'}>
              <span className="who">{m.from_role === role ? 'You' : other}</span>
              <span>{m.body}</span>
            </li>
          ))}
        </ol>
      )}
      {closed && messages.length === 0 && <p className="muted">No messages were exchanged.</p>}
      {!closed && (
      <form onSubmit={submit} className="thread-form">
        <label htmlFor={`reply-${payment.id}`}>{prompt}</label>
        <div className="row">
          <input
            id={`reply-${payment.id}`}
            value={body}
            maxLength={1000}
            onChange={(e) => setBody(e.target.value)}
            autoComplete="off"
          />
          <button type="submit" className="btn btn-secondary" disabled={busy || !body.trim()}>
            {busy ? 'Sending…' : 'Send'}
          </button>
        </div>
        {suggestions.length > 0 && (
          <div className="suggestions" aria-label="Suggested questions">
            {suggestions.map((q) => (
              <button key={q} type="button" className="suggestion" onClick={() => setBody(q)}>
                {q}
              </button>
            ))}
          </div>
        )}
        <ErrorNote error={error} />
      </form>
      )}
    </section>
  )
}
