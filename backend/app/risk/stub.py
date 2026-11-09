"""Placeholder risk engine for Phase 1, replaced by engine.py in Phase 2.

It only exists so the payment flow can be exercised end to end: "gift card" means high,
"urgent" or "asap" means medium, anything else is low.
"""

from __future__ import annotations

from .types import PaymentContext, RiskResult


class StubAssessor:
    def assess(self, ctx: PaymentContext) -> RiskResult:
        text = f"{ctx.note} {ctx.message_text}".lower()
        if "gift card" in text:
            return RiskResult("high", 80, "rules_only", "The message asks for gift cards.")
        if "urgent" in text or "asap" in text:
            return RiskResult("medium", 40, "rules_only", "The message is pushing you to hurry.")
        return RiskResult("low", 0, "rules_only", "Nothing unusual found.")


class FixedAssessor:
    """Test helper: always returns the configured level."""

    def __init__(self, level: str = "low") -> None:
        self.level = level

    def assess(self, ctx: PaymentContext) -> RiskResult:
        score = {"low": 0, "medium": 40, "high": 80}[self.level]
        return RiskResult(self.level, score, "rules_only", f"Fixed {self.level} risk for tests.")  # type: ignore[arg-type]
