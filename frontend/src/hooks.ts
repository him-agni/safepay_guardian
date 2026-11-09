import { useCallback, useEffect, useRef, useState } from 'react'

/** Calls `load` now and then every `intervalMs`, pausing while the tab is hidden.
 *  Restarts when `key` changes. `enabled = false` stops polling (e.g. once a payment is final). */
export function usePoll<T>(load: () => Promise<T>, intervalMs: number, key: string, enabled = true) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })
  const tickRef = useRef<() => void>(() => {})

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      clearTimeout(timer)
      if (!document.hidden) {
        try {
          const next = await loadRef.current()
          if (!cancelled) {
            setData(next)
            setError(null)
          }
        } catch (e) {
          if (!cancelled) setError(e as Error)
        }
      }
      if (!cancelled && enabled) timer = setTimeout(tick, intervalMs)
    }
    tickRef.current = () => void tick()

    const onVisible = () => {
      if (!document.hidden) void tick()
    }
    document.addEventListener('visibilitychange', onVisible)
    void tick()
    return () => {
      cancelled = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [key, intervalMs, enabled])

  const refresh = useCallback(() => tickRef.current(), [])
  return { data, error, setData, refresh }
}

/** A local once-per-second countdown that re-syncs whenever the server sends a new value. */
export function useCountdown(seconds: number | null) {
  // Counts whole seconds since the server last sent `seconds`; resets when a new value arrives.
  const [tick, setTick] = useState({ seconds, elapsed: 0 })
  useEffect(() => {
    if (seconds == null) return
    const id = setInterval(
      () => setTick((t) => (t.seconds === seconds ? { seconds, elapsed: t.elapsed + 1 } : { seconds, elapsed: 1 })),
      1000,
    )
    return () => clearInterval(id)
  }, [seconds])
  if (seconds == null) return null
  const elapsed = tick.seconds === seconds ? tick.elapsed : 0
  return Math.max(0, seconds - elapsed)
}

/** Minimal hash router: "#/send/abc" -> ["send", "abc"]. */
export function useHashRoute(): string[] {
  const read = () =>
    window.location.hash
      .replace(/^#\/?/, '')
      .split('/')
      .filter(Boolean)
      .map(decodeURIComponent)
  const [parts, setParts] = useState(read)
  useEffect(() => {
    const onChange = () => setParts(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return parts
}

export function go(path: string) {
  window.location.hash = path.startsWith('/') ? path : `/${path}`
}
