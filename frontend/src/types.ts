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
  final: boolean
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
