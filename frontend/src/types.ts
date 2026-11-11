// Shapes returned by the SafePay Guardian backend (see docs/HANDOFF.md, "API shape").

export type Level = 'low' | 'medium' | 'high'

export type Status =
  | 'CREATED'
  | 'AUTH_FAILED'
  | 'AUTHORIZED'
  | 'WARNED'
  | 'HELD'
  | 'CAPTURING'
  | 'VOIDING'
  | 'CAPTURED'
  | 'VOIDED'
  | 'EXPIRED'
  | 'CAPTURE_FAILED'
  | 'CAPTURE_PENDING'
  | 'VOID_FAILED'

export interface EvidenceSpan {
  field: 'message' | 'note'
  start: number
  end: number
  text: string
  type: string
  source: 'rule' | 'ai'
}

export interface Indicator {
  source: 'rule' | 'ai'
  type: string
  label: string
  evidence: string
  explanation: string
  weight: number
  hard: boolean
}

export interface PatternMatch {
  id: string
  category: string
  title: string
  score: number
}

export interface Risk {
  level: Level
  score: number
  score_label: string
  mode: 'hybrid' | 'rules_only'
  ai_unavailable: boolean
  ai_unavailable_text: string | null
  summary: string
  category: string | null
  indicators: Indicator[]
  evidence_spans: EvidenceSpan[]
  patterns: PatternMatch[]
  dropped_evidence: { type: string; evidence: string; reason: string }[]
  model: string | null
  latency_ms: number | null
  components?: { ai_cached?: boolean; [key: string]: unknown }
}

export interface PaymentEvent {
  at: string
  actor: 'system' | 'sender' | 'guardian'
  type: string
  detail: Record<string, unknown>
}

export interface Message {
  from_role: 'sender' | 'guardian'
  body: string
  at: string
}

export interface Payment {
  id: string
  status: Status
  amount: string
  amount_cents: number
  currency: string
  payee: {
    id: number
    name: string
    email: string | null
    trusted: boolean
    captured_payments?: number
    captured_total?: string
  }
  note: string
  message_text: string
  risk_level: Level | null
  risk_score: number | null
  risk_mode: 'hybrid' | 'rules_only' | null
  paypal: { order_id: string | null; authorization_id: string | null; capture_id: string | null }
  created_at: string
  updated_at: string
  hold_expires_at: string | null
  hold_seconds_left: number | null
  decided_by: 'system' | 'sender' | 'guardian' | null
  decided_at: string | null
  decision_note: string | null
  void_reason: 'sender_cancel' | 'guardian_decline' | 'timeout' | null
  last_error: string | null
  is_seed: boolean
  category: string | null
  screenshot_url: string | null
  final: boolean
  // Only on GET /payments list rows:
  risk_brief?: {
    summary: string
    checked_by: 'ai' | 'stored_reply' | 'rules'
    ai_flagged: boolean
    top_evidence: { type: string; evidence: string; source: 'rule' | 'ai'; label: string }[]
  } | null
  text: { sender: string; guardian: string }
  can: { confirm: boolean; cancel: boolean; approve: boolean; decline: boolean; retry: boolean }
  // Only on GET /payments/{id} and action responses:
  risk?: Risk | null
  events?: PaymentEvent[]
  messages?: Message[]
}

export interface Health {
  status: string
  sandbox_only: boolean
  paypal: { mode: string; configured: boolean; reachable: boolean | null }
  ai: { provider: string; configured: boolean; model: string | null; reachable: boolean | null; mode: string }
  hold_timeout_seconds: number
}

export type Action = 'confirm' | 'cancel' | 'approve' | 'decline' | 'retry'

/** POST /screenshots: the saved screenshot and what the AI read from it. */
export interface ScreenshotRead {
  screenshot_id: string
  url: string
  read: boolean
  text: string
  sender: string
  messages_found: number
  own_messages_skipped: number
  error: string | null
  model: string | null
  cached: boolean
  latency_ms: number | null
}

export interface Bucket {
  count: number
  total: string
  total_cents: number
}

export interface Stats {
  payments: number
  on_hold_now: number
  held_for_guardian: Bucket
  warned_sender: Bucket
  held_from_capture: Bucket
  declined_by_guardian: Bucket
  cancelled_by_sender: Bucket
  expired_no_answer: Bucket
  approved_by_guardian: Bucket
  confirmed_by_sender: Bucket
  auto_captured: Bucket
  by_level: Record<Level, number>
  rules_only_checks: number
  top_categories: (Bucket & { category: string })[]
  /** Every payment of the last `recent_days` days, seeded past history included (marked `past`). */
  recent: RecentPayment[]
  recent_days: number
  /** Payees most often warned or held (seeded history excluded). */
  flagged_payees: (Bucket & { payee: string; not_captured: number })[]
}

export interface RecentPayment {
  at: string
  outcome: 'captured' | 'stopped' | 'open'
  past: boolean
}
