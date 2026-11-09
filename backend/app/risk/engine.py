"""Step 4: aggregation. Rules set a floor, the AI adds context, and a human decides what is held.

final level = the highest of:
  * the rules level: high if any hard rule fired (gift cards, crypto, wire, "safe account"), otherwise the
    level of the rule score
  * the level of the combined score (rule weights + grounded AI indicator weights; one weight per type),
    capped at the AI's own recommended level
  * the AI floor: guardian_review with medium/high confidence and at least one grounded indicator -> high;
    warn with at least one grounded indicator -> medium
The AI can raise a level, at most to what it recommends. It can never lower one: the rules level is never capped.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from . import ai as ai_mod
from . import config as C
from . import patterns as pattern_mod
from . import rules as rules_mod
from .types import LEVEL_ORDER, Level, PaymentContext, RiskResult, max_level


def score_level(score: int) -> Level:
    if score >= C.HIGH_AT:
        return "high"
    if score >= C.MEDIUM_AT:
        return "medium"
    return "low"


def _score(indicators: list[dict]) -> int:
    by_type: dict[str, int] = {}
    for ind in indicators:
        by_type[ind["type"]] = max(by_type.get(ind["type"], 0), ind["weight"])
    return min(C.SCORE_CAP, sum(by_type.values()))


class HybridEngine:
    def __init__(self, provider: ai_mod.AIProvider | None = None) -> None:
        self.provider = provider

    @property
    def ai_enabled(self) -> bool:
        return self.provider is not None

    def assess(self, ctx: PaymentContext) -> RiskResult:
        rule_inds = rules_mod.evaluate(ctx)
        hard = any(i["hard"] for i in rule_inds)
        rules_score = _score(rule_inds)
        rules_level: Level = "high" if hard else score_level(rules_score)

        query = f"{ctx.message_text}\n{ctx.note}".strip()
        patterns = pattern_mod.search(query) if query else []

        if self.provider is not None:
            outcome = ai_mod.analyze(self.provider, ctx, patterns)
        else:
            outcome = ai_mod.AIOutcome(error="AI check not configured", error_kind="not_configured")

        ai_inds = outcome.kept if outcome.ok else []
        indicators = rule_inds + ai_inds
        score = _score(indicators)

        ai_only_level: Level | None = None
        ai_floor: Level = "low"
        if outcome.ok:
            analysis = outcome.analysis
            ai_only_level = ai_mod.ACTION_LEVEL[analysis["recommended_action"]]  # type: ignore[assignment]
            if ai_inds:
                if analysis["recommended_action"] == "guardian_review" and \
                        analysis["confidence"] in C.AI_FLOOR_HIGH_CONFIDENCE:
                    ai_floor = "high"
                elif analysis["recommended_action"] in ("warn", "guardian_review"):
                    ai_floor = "medium"

        # AI indicator weights may raise the level only as far as the AI's own recommendation: a model that says
        # "warn" cannot push a payment to High through its quote weights alone. Rules are never capped.
        combined_level = score_level(score)
        ai_cap: Level = ai_only_level if ai_only_level is not None else "low"
        if LEVEL_ORDER[combined_level] > LEVEL_ORDER[ai_cap]:
            combined_level = ai_cap
        level = max_level(rules_level, combined_level, ai_floor)
        mode = "hybrid" if outcome.ok else "rules_only"
        summary = self._summary(level, indicators, outcome, ai_only_level)

        indicators_sorted = sorted(indicators, key=lambda i: (not i["hard"], -i["weight"]))
        spans = []
        seen = set()
        for ind in indicators_sorted:
            for sp in ind["spans"]:
                key = (sp["field"], sp["start"], sp["end"])
                if sp["field"] in ("message", "note") and key not in seen:
                    seen.add(key)
                    spans.append({**sp, "type": ind["type"], "source": ind["source"]})

        return RiskResult(
            level=level,
            score=score,
            mode=mode,
            summary=summary,
            indicators=indicators_sorted,
            rules=rule_inds,
            ai=outcome.analysis,
            ai_error=outcome.error,
            dropped_evidence=outcome.dropped,
            patterns=patterns,
            evidence_spans=sorted(spans, key=lambda s: (s["field"], s["start"])),
            model=outcome.model if self.provider is not None else None,
            latency_ms=outcome.latency_ms if self.provider is not None else None,
            components={
                "config_version": C.CONFIG_VERSION,
                "prompt_version": ai_mod.PROMPT_VERSION,
                "rules_score": rules_score,
                "rules_level": rules_level,
                "hard_rule": hard,
                "ai_ok": outcome.ok,
                "ai_error_kind": outcome.error_kind,
                "ai_only_level": ai_only_level,
                "ai_floor": ai_floor if outcome.ok else None,
                "ai_valid_first_try": outcome.valid_first_try,
                "ai_cached": outcome.cached,
                "ai_kept": len(ai_inds),
                "ai_dropped": len(outcome.dropped),
                "score_level": score_level(score),
            },
        )

    @staticmethod
    def _summary(level: Level, indicators: list[dict], outcome: ai_mod.AIOutcome, ai_only_level: Level | None) -> str:
        # Use the AI's own words only when its recommendation agrees with the final level. Otherwise (for
        # example a message that tricked the AI into saying "safe" while a rule holds it) build the summary
        # from the indicators, so the sender never reads "this is safe" next to "on hold".
        if outcome.ok and ai_only_level == level and outcome.analysis.get("summary"):
            return outcome.analysis["summary"].strip()
        if level == "low" and not any(i["weight"] >= 15 or i["hard"] for i in indicators):
            return "Nothing unusual found."
        ranked = sorted(indicators, key=lambda i: (not i["hard"], -i["weight"]))
        labels: list[str] = []
        for ind in ranked:
            label = ind["label"].strip()
            if label and label not in labels:
                labels.append(label if label.endswith((".", "!", "?")) else label + ".")
            if len(labels) == 3:
                break
        return " ".join(labels) or "Nothing unusual found."


def build_assessor(settings: Settings) -> HybridEngine:
    if not settings.ai_configured:
        return HybridEngine(None)
    provider: ai_mod.AIProvider = ai_mod.GeminiProvider(settings)
    if settings.ai_cache_dir:
        cache = Path(settings.ai_cache_dir)
        if not cache.is_absolute():
            from ..config import REPO_ROOT
            cache = REPO_ROOT / cache
        provider = ai_mod.CachingProvider(provider, cache)
    return HybridEngine(provider)
