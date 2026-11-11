import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type NewPayment } from '../api'
import { ErrorNote } from '../components'
import { amountProblem, cleanAmount, money, SCREENSHOT_TYPES, screenshotProblem, senderStatusWord, timeAgo } from '../format'
import { go, usePoll } from '../hooks'
import { remember } from '../store'
import { DEMO_SCENARIOS, isDemoMode, type DemoScenario } from './demoScenarios'
import { clearPending, loadPending, outcomeUnknown, savePending, type PendingSubmission } from './pending'
import { attemptFor, type Attempt } from './submission'

const EMPTY: NewPayment = { payee_name: '', amount: '', note: '', message_text: '' }

interface Shot {
  preview: string // local object URL, for the thumbnail
  id?: string // saved on the server
  status: 'reading' | 'read' | 'unread' | 'failed'
  sender?: string
  found?: number
  skipped?: number
  error?: string
}

/** "Choose a screenshot", then a thumbnail with what happened, in plain words. */
function ScreenshotPicker({ shot, onPick, onRemove }: {
  shot: Shot | null
  onPick: (file: File) => void
  onRemove: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <div className="shot-pick">
      <input
        ref={input}
        id="screenshot"
        type="file"
        accept={SCREENSHOT_TYPES.join(',')}
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onPick(file)
          e.target.value = ''
        }}
      />
      {!shot && (
        <button type="button" className="btn btn-secondary" onClick={() => input.current?.click()}>
          Add a screenshot instead
        </button>
      )}
      {shot && (
        <div className="shot-status">
          <img src={shot.preview} alt="Your screenshot" />
          <div aria-live="polite">
            {shot.status === 'reading' && <p><strong>Reading your screenshot…</strong> This takes a few seconds.</p>}
            {shot.status === 'read' && (
              <p>
                <strong>We read {shot.found} message{shot.found === 1 ? '' : 's'}</strong>
                {shot.sender ? ` from ${shot.sender}` : ''} and put {shot.found === 1 ? 'it' : 'them'} in the box
                below{shot.skipped ? ' (we left out your own replies)' : ''}.{' '}
                <strong>Please check the words match your screenshot</strong> and fix anything that is wrong.
              </p>
            )}
            {(shot.status === 'unread' || shot.status === 'failed') && <p className="shot-warn">{shot.error}</p>}
            {shot.status !== 'reading' && (
              <div className="row">
                <button type="button" className="btn btn-quiet" onClick={() => input.current?.click()}>
                  Choose another
                </button>
                <button type="button" className="btn btn-quiet" onClick={onRemove}>
                  Remove screenshot
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export function SendPage() {
  const [form, setForm] = useState<NewPayment>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const recent = usePoll(() => api.listPayments({ limit: 8 }), 3000, 'sender-recent')

  const [shot, setShot] = useState<Shot | null>(null)
  const attempt = useRef<Attempt | null>(null)

  // An attempt whose answer never arrived (kept in this tab so a refresh does not lose it)
  const [pending, setPending] = useState<PendingSubmission | null>(() => loadPending())

  // Demo buttons: when the backend replays stored AI answers (or the address has ?demo)
  const [demo, setDemo] = useState(() => isDemoMode(null, window.location.search))
  useEffect(() => {
    let alive = true
    api
      .health()
      .then((h) => alive && setDemo(isDemoMode(h, window.location.search)))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  // Free a local preview only when it is replaced or the page closes (not when its status changes).
  const previewRef = useRef<string | null>(null)
  const swapPreview = (url: string | null) => {
    if (previewRef.current && previewRef.current !== url) URL.revokeObjectURL(previewRef.current)
    previewRef.current = url
  }
  useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    },
    [],
  )

  const set = (field: keyof NewPayment) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [field]: e.target.value }))

  const pickScreenshot = async (file: File) => {
    const problem = screenshotProblem(file)
    const preview = URL.createObjectURL(file)
    swapPreview(preview)
    if (problem) {
      setShot({ preview, status: 'failed', error: problem })
      return
    }
    setShot({ preview, status: 'reading' })
    try {
      const r = await api.readScreenshot(file)
      if (r.read) setForm((f) => ({ ...f, message_text: r.text }))
      setShot({
        preview,
        id: r.screenshot_id,
        status: r.read ? 'read' : 'unread',
        sender: r.sender,
        found: r.messages_found,
        skipped: r.own_messages_skipped,
        error: r.error ?? undefined,
      })
    } catch (err) {
      setShot({ preview, status: 'failed', error: (err as Error).message })
    }
  }

  const removeScreenshot = () => {
    swapPreview(null)
    setShot(null)
  }

  /** Fill the form with one of the three prepared demo scenarios (exact text, so the stored AI replies match). */
  const loadScenario = async (sc: DemoScenario) => {
    setError(null)
    removeScreenshot()
    setForm({ payee_name: sc.payee_name, amount: sc.amount, note: sc.note, message_text: sc.message_text })
    if (!sc.screenshot) return
    try {
      const blob = await (await fetch(sc.screenshot)).blob()
      await pickScreenshot(new File([blob], 'bank-fraud-team-text.png', { type: 'image/png' }))
    } catch {
      setError(new Error('Could not load the demo screenshot. The message text was filled in instead.'))
    }
  }

  /** Send the unfinished attempt again with its own key: the payment is returned if it was made, made once if not. */
  const checkPending = async () => {
    if (!pending) return
    setBusy(true)
    setError(null)
    attempt.current = pending.attempt
    try {
      const p = await api.createPayment(pending.payment as unknown as NewPayment, pending.attempt.key)
      clearPending()
      setPending(null)
      attempt.current = null
      remember(p)
      go(`/send/${p.id}`)
    } catch (err) {
      if (!outcomeUnknown(err instanceof ApiError ? err.status : 0)) {
        clearPending()
        setPending(null)
      }
      setError(err instanceof ApiError ? err : new Error('Something went wrong. Please try again.'))
      setBusy(false)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const problem = !form.payee_name.trim() ? 'Please enter who you are paying.' : amountProblem(form.amount)
    if (problem) {
      setError(new Error(problem))
      return
    }
    setBusy(true)
    setError(null)
    const payment = {
      ...form,
      payee_name: form.payee_name.trim(),
      amount: cleanAmount(form.amount),
      screenshot_id: shot?.id,
    }
    // the same details sent again after a failure keep their key, so a lost answer never makes a second payment
    attempt.current = attemptFor(attempt.current, payment)
    savePending({ attempt: attempt.current, payment, at: Date.now() })
    try {
      const p = await api.createPayment(payment, attempt.current.key)
      attempt.current = null
      clearPending()
      remember(p)
      go(`/send/${p.id}`)
    } catch (err) {
      if (outcomeUnknown(err instanceof ApiError ? err.status : 0)) setPending(loadPending())
      else clearPending() // a clear refusal: nothing was made, so there is nothing to check
      setError(err instanceof ApiError ? err : new Error('Something went wrong. Please try again.'))
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <section className="card">
        <h1>Send money</h1>
        <p className="lead">We check every payment for signs of a scam before any money is taken.</p>
        {pending && (
          <div className="banner banner-info" role="status">
            <strong>Your last payment did not finish.</strong> {money(String(pending.payment.amount))} to{' '}
            {String(pending.payment.payee_name)}: we did not see the answer, so we cannot tell if it went through.
            Press <em>Check what happened</em>. It will never be sent twice.
            <div className="demo-buttons">
              <button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={checkPending}>
                {busy ? 'Checking…' : 'Check what happened'}
              </button>
              <button
                type="button"
                className="btn btn-quiet btn-small"
                disabled={busy}
                onClick={() => {
                  clearPending()
                  setPending(null)
                }}
              >
                Start a new payment
              </button>
            </div>
          </div>
        )}
        {demo && (
          <div className="banner banner-info demo-box">
            <strong>Demo mode.</strong> Load a prepared scenario, then press <em>Send for check</em>. After a reset, play
            them in order: 1, 2, 3.
            <ul className="demo-list">
              {DEMO_SCENARIOS.map((sc) => (
                <li key={sc.id}>
                  <button type="button" className="btn btn-secondary btn-small" disabled={busy} onClick={() => loadScenario(sc)}>
                    {sc.label}
                  </button>
                  <span className="muted small">{sc.hint}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
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
              If someone texted, emailed or called asking for this money, paste their words here, or add a screenshot
              of the conversation. It helps us spot scams.
            </p>
            <ScreenshotPicker
              shot={shot}
              onPick={pickScreenshot}
              onRemove={removeScreenshot}
            />
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
          <button type="submit" className="btn btn-primary btn-wide" disabled={busy || shot?.status === 'reading'}>
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
