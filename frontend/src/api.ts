// The only place the frontend talks to the network. Everything goes to our own backend (/api),
// which is the only thing that talks to PayPal and the AI model.

import type { Action, Health, Payment, ScreenshotRead, Stats } from './types'

const BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly payment: Payment | null

  constructor(message: string, status: number, payment: Payment | null = null) {
    super(message)
    this.status = status
    this.payment = payment
  }
}

const FIELD_HELP: Record<string, string> = {
  payee_name: 'Please enter who you are paying.',
  amount: 'Please enter an amount between $0.01 and $10,000, with at most 2 numbers after the point.',
  note: 'The note is too long. Please keep it under 500 characters.',
  message_text: 'The pasted message is too long. Please keep it under 5,000 characters.',
  body: 'Please write a message (up to 1,000 characters).',
}

export function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object') {
    const b = body as { message?: unknown; detail?: unknown }
    if (typeof b.message === 'string') return b.message
    if (Array.isArray(b.detail)) {
      // FastAPI validation errors: [{loc: ["body", "amount"], msg: "..."}]
      const fields = b.detail
        .map((d) => (Array.isArray(d?.loc) ? String(d.loc[d.loc.length - 1]) : ''))
        .filter((f) => f in FIELD_HELP)
      if (fields.length) return [...new Set(fields)].map((f) => FIELD_HELP[f]).join(' ')
    }
  }
  if (status === 404) return 'We could not find that payment.'
  if (status >= 500) return 'Something went wrong on our side. Please try again in a moment.'
  return 'Something went wrong. Please try again.'
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError('We could not reach SafePay. Please check that the server is running.', 0)
  }
  const body: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    const payment = (body as { payment?: Payment } | null)?.payment ?? null
    throw new ApiError(errorMessage(body, res.status), res.status, payment)
  }
  return body as T
}

export interface NewPayment {
  payee_name: string
  amount: string
  note: string
  message_text: string
  screenshot_id?: string
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new ApiError('We could not open that file. Please try another picture.', 0))
    reader.readAsDataURL(file)
  })
}

/** The screenshot's address through our backend (the browser never talks to anything else). */
export const screenshotSrc = (url: string) => BASE + url

export const api = {
  health: () => request<Health>('/health'),
  stats: () => request<Stats>('/stats'),
  createPayment: (p: NewPayment) => request<Payment>('/payments', { method: 'POST', body: JSON.stringify(p) }),
  getPayment: (id: string) => request<Payment>(`/payments/${encodeURIComponent(id)}`),
  listPayments: (params: { status?: string; queue?: 'guardian'; limit?: number } = {}) => {
    const q = new URLSearchParams()
    if (params.status) q.set('status', params.status)
    if (params.queue) q.set('queue', params.queue)
    if (params.limit) q.set('limit', String(params.limit))
    const qs = q.toString()
    return request<{ payments: Payment[] }>(`/payments${qs ? `?${qs}` : ''}`).then((r) => r.payments)
  },
  act: (id: string, action: Action, note?: string) =>
    request<Payment>(`/payments/${encodeURIComponent(id)}/${action}`, {
      method: 'POST',
      body: JSON.stringify(note ? { note } : {}),
    }),
  readScreenshot: async (file: File) =>
    request<ScreenshotRead>('/screenshots', {
      method: 'POST',
      body: JSON.stringify({ image_base64: await readAsDataUrl(file), mime_type: file.type }),
    }),
  addMessage: (id: string, from_role: 'sender' | 'guardian', body: string) =>
    request<Payment>(`/payments/${encodeURIComponent(id)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ from_role, body }),
    }),
}
