"""Shared types for the risk engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Level = Literal["low", "medium", "high"]
LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}


def max_level(*levels: Level) -> Level:
    return max(levels, key=lambda lv: LEVEL_ORDER[lv])


@dataclass
class PaymentContext:
    """Everything the engine may look at for one payment."""

    amount_cents: int
    currency: str
    payee_name: str
    payee_is_new: bool
    payee_trusted: bool
    note: str = ""
    message_text: str = ""
    history_amounts_cents: list[int] = field(default_factory=list)  # sender's past captured payments
    payee_history_count: int = 0
    payee_spending_limit_cents: int | None = None


@dataclass
class RiskResult:
    level: Level
    score: int
    mode: Literal["hybrid", "rules_only"]
    summary: str
    indicators: list[dict] = field(default_factory=list)  # every kept indicator, rules and AI
    rules: list[dict] = field(default_factory=list)
    ai: dict | None = None
    ai_error: str | None = None
    dropped_evidence: list[dict] = field(default_factory=list)
    patterns: list[dict] = field(default_factory=list)
    evidence_spans: list[dict] = field(default_factory=list)  # {"field", "start", "end", "text"}
    model: str | None = None
    latency_ms: int | None = None
    components: dict = field(default_factory=dict)  # rules-only / AI-only levels etc., used by the eval


class Assessor(Protocol):
    def assess(self, ctx: PaymentContext) -> RiskResult: ...
