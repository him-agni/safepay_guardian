import { useEffect, useId, useRef, useState } from 'react'
import { LockIcon, ShieldUpIcon } from '../icons'
import { nextStage, typedCount, usePrefersReducedMotion, useOnScreen } from './motion'

/*
 * The animated picture in the hero: a shield that watches the cursor, and a looping four-step story
 * (a scam text arrives, the payment goes on hold, the guardian looks, it is declined and nothing is taken).
 * Decorative: the same story is told in words by the sections below, so the picture is hidden from screen
 * readers. The four step buttons are real buttons and are not hidden.
 */

const STAGES = ['Message', 'On hold', 'Guardian', 'Decided'] as const
const STAGE_MS = 4200
const TYPE_MS = 28

// The scam text. The pieces marked true are lit up once the payment has been checked.
const MESSAGE: { t: string; mark: boolean }[] = [
  { t: 'This is the bank ', mark: false },
  { t: 'fraud team', mark: true },
  { t: '. Move your savings to a ', mark: false },
  { t: 'protected account', mark: true },
  { t: ' ', mark: false },
  { t: 'today', mark: true },
  { t: '.', mark: false },
]
const MESSAGE_LENGTH = MESSAGE.reduce((n, s) => n + s.t.length, 0)
// where each piece starts in the whole line
const MESSAGE_STARTS = MESSAGE.map((_, i) => MESSAGE.slice(0, i).reduce((n, s) => n + s.t.length, 0))

function useTyped(active: boolean, reduced: boolean): number {
  const [n, setN] = useState(0)
  const [wasActive, setWasActive] = useState(active)
  // a new run starts from nothing (adjusted while rendering, not in an effect)
  if (active !== wasActive) {
    setWasActive(active)
    if (active) setN(0)
  }
  useEffect(() => {
    if (reduced || !active) return
    const t0 = performance.now()
    const id = window.setInterval(() => {
      const c = typedCount(MESSAGE_LENGTH, performance.now() - t0, TYPE_MS)
      setN(c)
      if (c >= MESSAGE_LENGTH) window.clearInterval(id)
    }, 40)
    return () => window.clearInterval(id)
  }, [active, reduced])
  return reduced ? MESSAGE_LENGTH : n
}

function Bubble({ shown, lit }: { shown: number; lit: boolean }) {
  return (
    <div className="mock-bubble">
      {MESSAGE.map((s, i) => {
        const text = s.t.slice(0, Math.max(0, shown - MESSAGE_STARTS[i]))
        if (!text) return null
        return s.mark ? (
          <mark key={i} className={lit ? 'lit' : undefined}>
            {text}
          </mark>
        ) : (
          <span key={i}>{text}</span>
        )
      })}
      {shown < MESSAGE_LENGTH && <span className="caret" />}
    </div>
  )
}

export function Shield({ pulse, tracking }: { pulse: number; tracking: boolean }) {
  const uid = useId()
  const grad = `${uid}-g`
  const halo = `${uid}-h`
  return (
    <div className={`shield-scene${tracking ? ' tracking' : ''}`} aria-hidden="true">
      <svg viewBox="0 0 240 240" focusable="false">
        <defs>
          <linearGradient id={grad} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" className="stop-1" />
            <stop offset=".55" className="stop-2" />
            <stop offset="1" className="stop-3" />
          </linearGradient>
          <radialGradient id={halo}>
            <stop offset="0" className="halo-in" />
            <stop offset="1" className="halo-out" />
          </radialGradient>
        </defs>

        <g className="layer layer-far">
          <circle cx="120" cy="120" r="112" fill={`url(#${halo})`} />
        </g>

        <g className="orbit">
          <circle cx="120" cy="120" r="104" className="orbit-ring" />
          <circle cx="120" cy="16" r="6" className="orbit-node n1" />
          <circle cx="213" cy="150" r="5" className="orbit-node n2" />
          <circle cx="42" cy="190" r="4" className="orbit-node n3" />
        </g>

        <circle key={pulse} cx="120" cy="122" r="70" className="pulse-ring" />

        <g className="layer layer-mid">
          <path
            d="M120 28 196 56v62c0 46-32 78-76 96-44-18-76-50-76-96V56z"
            fill={`url(#${grad})`}
            className="shield-body"
          />
          <path d="M120 44 182 67v51c0 37-26 63-62 79-36-16-62-42-62-79V67z" className="shield-inner" />
        </g>

        <g className="layer layer-near">
          <path d="M104 114v-12a16 16 0 0 1 32 0v12" className="lock-shackle" />
          <rect x="94" y="112" width="52" height="42" rx="11" className="lock-body" />
          <g className="keyhole">
            <circle cx="120" cy="130" r="6" />
            <rect x="118" y="132" width="4" height="12" rx="2" />
          </g>
        </g>
      </svg>
    </div>
  )
}

export function Story({ onStage }: { onStage?: (stage: number) => void }) {
  const reduced = usePrefersReducedMotion()
  const rootRef = useRef<HTMLDivElement>(null)
  const onScreen = useOnScreen(rootRef)
  // null until a stage is chosen or the loop starts: then the first stage, or the last (finished) one if motion is reduced
  const [picked, setPicked] = useState<number | null>(null)
  const stage = picked ?? (reduced ? STAGES.length - 1 : 0)
  const [hovering, setHovering] = useState(false)
  // bumped on a click so the timer restarts and the stage just chosen is not skipped straight away
  const [tick, setTick] = useState(0)
  const playing = onScreen && !reduced && !hovering

  useEffect(() => {
    if (!playing) return
    const id = window.setInterval(() => setPicked((s) => nextStage(s ?? 0, STAGES.length)), STAGE_MS)
    return () => window.clearInterval(id)
  }, [playing, tick])

  useEffect(() => {
    onStage?.(stage)
  }, [stage, onStage])

  const typed = useTyped(stage === 0, reduced)
  const shown = stage === 0 ? typed : MESSAGE_LENGTH

  const pos = (i: number) => (stage - i < 0 ? 'ahead' : stage - i === 0 ? 'now' : stage - i === 1 ? 'back1' : stage - i === 2 ? 'back2' : 'gone')

  return (
    <div className="story" ref={rootRef} onPointerEnter={(e) => e.pointerType === 'mouse' && setHovering(true)}
      onPointerLeave={() => setHovering(false)}>
      <div className="mock" aria-hidden="true">
        <div className={`mock-card deck ${pos(0)}`}>
          <span className="mock-from">Text message</span>
          <Bubble shown={shown} lit={stage >= 1} />
        </div>

        <div className={`mock-card mock-hold deck ${pos(1)}`}>
          <span className="mock-lock">
            <LockIcon />
          </span>
          <div>
            <strong>$300.00 is on hold</strong>
            <div>Waiting for your guardian</div>
          </div>
          <span className="mock-pill">High risk</span>
        </div>

        <div className={`mock-card deck ${pos(2)}`}>
          <strong>Daniel, your guardian</strong>
          <div>"This is not your bank. Do not move any money."</div>
          <div className="mock-buttons">
            <span className={`mock-decline${stage === 2 ? ' press' : ''}`}>Decline</span>
            <span className="mock-approve">Approve</span>
          </div>
        </div>

        <div className={`mock-card mock-done deck ${pos(3)}`}>
          <span className="mock-lock mock-lock-ok">
            <ShieldUpIcon />
          </span>
          <div>
            <strong>Declined. No payment was taken.</strong>
            <div>The hold was released.</div>
          </div>
        </div>
      </div>

      <div className="story-tabs" role="group" aria-label="Follow a payment on hold, step by step">
        <span className="story-pill" style={{ transform: `translateX(${stage * 100}%)` }} aria-hidden="true" />
        {STAGES.map((label, i) => (
          <button
            key={label}
            type="button"
            aria-pressed={stage === i}
            onClick={() => {
              setPicked(i)
              setTick((t) => t + 1)
            }}
          >
            <span className="story-num" aria-hidden="true">
              {i + 1}
            </span>
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}
