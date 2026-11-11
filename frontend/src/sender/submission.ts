/*
 * One submission key per intended payment.
 *
 * If the answer to "Send for check" is lost (a dropped connection, a slow server) and the sender presses the
 * button again, the same key tells the server this is the same payment, so it returns the first one instead of
 * making a second. If the sender changes anything, it is a different payment and gets a new key.
 */

export interface Attempt {
  key: string
  fingerprint: string
}

/** A random key the server accepts (letters, digits, - and _; 8 to 64 long). */
export function newSubmissionKey(): string {
  const c = globalThis.crypto
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  const bytes = new Uint8Array(16)
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes)
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

export function fingerprintOf(fields: Record<string, unknown>): string {
  return JSON.stringify(Object.keys(fields).sort().map((k) => [k, fields[k] ?? null]))
}

/** Keep the previous key if the details are unchanged (a retry); otherwise start a new one. */
export function attemptFor(
  previous: Attempt | null,
  fields: Record<string, unknown>,
  make: () => string = newSubmissionKey,
): Attempt {
  const fingerprint = fingerprintOf(fields)
  return previous && previous.fingerprint === fingerprint ? previous : { key: make(), fingerprint }
}
