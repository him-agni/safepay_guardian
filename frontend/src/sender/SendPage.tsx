import { useState, type FormEvent } from 'react'
import { api, ApiError, type NewPayment } from '../api'
import { ErrorNote } from '../components'
import { amountProblem, cleanAmount, money, senderStatusWord, timeAgo } from '../format'
import { go, usePoll } from '../hooks'
import { remember } from '../store'

const EMPTY: NewPayment = { payee_name: '', amount: '', note: '', message_text: '' }

export function SendPage() {
  const [form, setForm] = useState<NewPayment>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const recent = usePoll(() => api.listPayments({ limit: 8 }), 3000, 'sender-recent')

  const set = (field: keyof NewPayment) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [field]: e.target.value }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const problem = !form.payee_name.trim() ? 'Please enter who you are paying.' : amountProblem(form.amount)
    if (problem) {
      setError(new Error(problem))
      return
    }
    setBusy(true)
    setError(null)
    try {
      const p = await api.createPayment({ ...form, payee_name: form.payee_name.trim(), amount: cleanAmount(form.amount) })
      remember(p)
      go(`/send/${p.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err : new Error('Something went wrong. Please try again.'))
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <section className="card">
        <h1>Send money</h1>
        <p className="lead">We check every payment for signs of a scam before any money is taken.</p>
        <form onSubmit={submit} className="form" noValidate>
          <div className="field">
            <label htmlFor="payee">Who are you paying?</label>
            <input id="payee" value={form.payee_name} onChange={set('payee_name')} autoComplete="off" maxLength={80} />
          </div>
          <div className="field">
            <label htmlFor="amount">How much? (US dollars)</label>
            <div className="money-input">
              <span aria-hidden="true">$</span>
              <input id="amount" inputMode="decimal" value={form.amount} onChange={set('amount')} autoComplete="off" />
            </div>
          </div>
          <div className="field">
            <label htmlFor="note">What is it for? (optional)</label>
            <input id="note" value={form.note} onChange={set('note')} maxLength={500} autoComplete="off" />
          </div>
          <div className="field">
            <label htmlFor="message">Paste the message you received (optional)</label>
            <p className="hint" id="message-hint">
              If someone texted, emailed or called asking for this money, paste their words here. It helps us spot
              scams.
            </p>
            <textarea
              id="message"
              aria-describedby="message-hint"
              rows={5}
              value={form.message_text}
              onChange={set('message_text')}
              maxLength={5000}
            />
          </div>
          <ErrorNote error={error} />
          <button type="submit" className="btn btn-primary btn-wide" disabled={busy}>
            {busy ? 'Checking your payment…' : 'Send for check'}
          </button>
          <p className="sr-only" aria-live="polite">
            {busy ? 'Checking your payment. This can take a few seconds.' : ''}
          </p>
        </form>
      </section>

      <section className="card">
        <h2>Your recent payments</h2>
        <ErrorNote error={recent.error} />
        {recent.data && recent.data.length === 0 && <p className="muted">No payments yet.</p>}
        {recent.data && recent.data.length > 0 && (
          <ul className="list">
            {recent.data.map((p) => (
              <li key={p.id}>
                <a href={`#/send/${p.id}`} className="list-row">
                  <span className="list-main">
                    <strong>{money(p.amount)}</strong> to {p.payee.name}
                  </span>
                  <span className={`chip chip-${p.status.toLowerCase()}`}>{senderStatusWord(p)}</span>
                  <span className="muted">{timeAgo(p.created_at)}</span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
