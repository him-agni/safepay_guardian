import { useEffect, useRef, useState, useSyncExternalStore, type RefObject } from 'react'

/*
 * Motion helpers for the Home page. Rules every effect follows:
 *  - "reduce motion" in the device settings means the finished picture, no movement;
 *  - cursor effects only run where there is a real pointer (not on touch screens);
 *  - nothing is hidden for good: if the browser cannot observe scrolling, everything is shown.
 */

const REDUCED = '(prefers-reduced-motion: reduce)'
const FINE_POINTER = '(hover: hover) and (pointer: fine)'

function query(q: string): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(q).matches
}

function subscribe(q: string) {
  return (onChange: () => void) => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {}
    const mq = window.matchMedia(q)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }
}

const subscribeReduced = subscribe(REDUCED)

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReduced, () => query(REDUCED), () => false)
}

/** True for a mouse or trackpad, false for a touch screen. */
export function hasFinePointer(): boolean {
  return query(FINE_POINTER)
}

export function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n))
}

/**
 * Where the pointer is relative to the middle of a box, as -1..1 on each axis.
 * The box is the whole hero, so the shield keeps looking at the cursor wherever it is on the panel.
 */
export function lookFromPointer(
  x: number,
  y: number,
  box: { left: number; top: number; width: number; height: number },
): { x: number; y: number } {
  if (box.width <= 0 || box.height <= 0) return { x: 0, y: 0 }
  const nx = ((x - box.left) / box.width - 0.5) * 2
  const ny = ((y - box.top) / box.height - 0.5) * 2
  return { x: clamp(nx, -1, 1), y: clamp(ny, -1, 1) }
}

/** Ease-out cubic: starts fast, settles gently. */
export function easeOutCubic(t: number): number {
  const c = clamp(t, 0, 1)
  return 1 - Math.pow(1 - c, 3)
}

/** The whole number to show part-way through counting up to `target`. */
export function countAt(target: number, progress: number): number {
  return Math.round(target * easeOutCubic(progress))
}

/** The next step of a looping story. */
export function nextStage(stage: number, total: number): number {
  return total <= 0 ? 0 : (stage + 1) % total
}

/** How many characters of a typed line are showing, given the time since it started. */
export function typedCount(length: number, elapsedMs: number, msPerChar: number): number {
  if (msPerChar <= 0) return length
  return clamp(Math.floor(elapsedMs / msPerChar), 0, length)
}

/** True once the element has been on screen. Starts true if the user asked for less motion. */
export function useInView<T extends Element>(ref: RefObject<T | null>, threshold = 0.15): boolean {
  const reduced = usePrefersReducedMotion()
  // a browser that cannot observe scrolling just shows everything
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    const el = ref.current
    if (!el || seen) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true)
          io.disconnect()
        }
      },
      { threshold },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [ref, seen, threshold])
  return reduced || seen
}

/** True while the element is on screen and the tab is visible (to pause loops nobody can see). */
export function useOnScreen<T extends Element>(ref: RefObject<T | null>): boolean {
  const [on, setOn] = useState(true)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    let inView = true
    const update = () => setOn(inView && document.visibilityState === 'visible')
    const io = new IntersectionObserver((entries) => {
      inView = entries.some((e) => e.isIntersecting)
      update()
    })
    io.observe(el)
    document.addEventListener('visibilitychange', update)
    return () => {
      io.disconnect()
      document.removeEventListener('visibilitychange', update)
    }
  }, [ref])
  return on
}

/**
 * Makes `target` follow the cursor while it is over `area`, by setting --lx and --ly (-1..1) on it.
 * No re-render per move. Does nothing on touch screens or with reduced motion.
 * Returns whether tracking is on, so the page can drop the idle sway.
 */
export function usePointerLook(area: RefObject<HTMLElement | null>, target: RefObject<HTMLElement | null>): boolean {
  const reduced = usePrefersReducedMotion()
  const active = !reduced && hasFinePointer()
  useEffect(() => {
    const a = area.current
    const t = target.current
    if (!a || !t || !active) return
    let frame = 0
    let next = { x: 0, y: 0 }
    const apply = () => {
      frame = 0
      t.style.setProperty('--lx', next.x.toFixed(3))
      t.style.setProperty('--ly', next.y.toFixed(3))
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(apply)
    }
    const move = (e: PointerEvent) => {
      next = lookFromPointer(e.clientX, e.clientY, a.getBoundingClientRect())
      schedule()
    }
    const leave = () => {
      next = { x: 0, y: 0 }
      schedule()
    }
    a.addEventListener('pointermove', move)
    a.addEventListener('pointerleave', leave)
    return () => {
      a.removeEventListener('pointermove', move)
      a.removeEventListener('pointerleave', leave)
      if (frame) cancelAnimationFrame(frame)
      t.style.removeProperty('--lx')
      t.style.removeProperty('--ly')
    }
  }, [area, target, active])
  return active
}

/** Counts from 0 up to `target` the first time `ref` is on screen. Final number at once if motion is reduced. */
export function useCountUp(target: number, ref: RefObject<Element | null>, durationMs = 1300): number {
  const reduced = usePrefersReducedMotion()
  const seen = useInView(ref, 0.4)
  const [value, setValue] = useState(0)
  const started = useRef(false)
  useEffect(() => {
    if (reduced) return
    if (!seen || started.current) return
    started.current = true
    const t0 = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const p = (now - t0) / durationMs
      setValue(countAt(target, p))
      if (p < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [reduced, seen, target, durationMs])
  return reduced ? target : value
}
