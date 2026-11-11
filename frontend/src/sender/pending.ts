/*
 * Surviving a page refresh.
 *
 * If the answer to "Send for check" never arrived (a dropped connection, a timeout, a server error), the payment
 * may or may not exist. The attempt is kept in the browser tab's session storage, so a refresh does not lose its
 * key. Pressing "Check what happened" sends the same details with the same key: the server returns the payment if
 * it was made, or makes it once if it was not. It can never be made twice.
 */

import type { Attempt } from './submission'

export interface PendingSubmission {
  attempt: Attempt
  payment: Record<string, unknown>
  at: number
}

export interface MiniStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

const PENDING_KEY = 'safepay.pending-submission'
export const PENDING_MAX_AGE_MS = 30 * 60_000

function tabStorage(): MiniStorage | null {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage
  } catch {
    return null // blocked site data
  }
}

export function savePending(p: PendingSubmission, storage: MiniStorage | null = tabStorage()): void {
  try {
    storage?.setItem(PENDING_KEY, JSON.stringify(p))
  } catch {
    /* storage full or blocked: the in-page key still protects this visit */
  }
}

export function clearPending(storage: MiniStorage | null = tabStorage()): void {
  try {
    storage?.removeItem(PENDING_KEY)
  } catch {
    /* nothing to do */
  }
}

/** The unfinished attempt, if there is one that is recent and well formed; stale or damaged ones are dropped. */
export function loadPending(now = Date.now(), storage: MiniStorage | null = tabStorage()): PendingSubmission | null {
  try {
    const raw = storage?.getItem(PENDING_KEY)
    if (!raw) return null
    const p = JSON.parse(raw) as PendingSubmission
    const ok =
      p &&
      typeof p.at === 'number' &&
      typeof p.attempt?.key === 'string' &&
      typeof p.attempt?.fingerprint === 'string' &&
      p.payment !== null &&
      typeof p.payment === 'object'
    if (!ok || now - p.at > PENDING_MAX_AGE_MS || now < p.at) {
      clearPending(storage)
      return null
    }
    return p
  } catch {
    clearPending(storage)
    return null
  }
}

/** True when we cannot tell whether the payment was made: no answer at all, or a server error. A 4xx is a clear no. */
export function outcomeUnknown(status: number): boolean {
  return status === 0 || status >= 500
}
