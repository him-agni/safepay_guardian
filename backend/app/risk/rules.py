"""Step 1: deterministic rules.

Each rule that fires adds an indicator with a weight and the exact words that triggered it.
Text rules run on a normalised copy of the message and note (so "don’t" matches "don't") and
map matches back to the original text, so rule evidence is grounded by construction.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from ..paypal import format_amount
from . import config as C
from .text import Span, normalize
from .types import PaymentContext


@dataclass(frozen=True)
class TextRule:
    id: str
    type: str
    label: str  # short plain-language reason shown to the sender
    patterns: tuple[str, ...]
    hard: bool = False

    @property
    def weight(self) -> int:
        return 0 if self.hard else C.RULE_WEIGHTS[self.type]


APOS = "'?"  # matches "dont" and "don't" (curly quotes are already straightened)

TEXT_RULES: tuple[TextRule, ...] = (
    TextRule(
        "gift_card", "gift_card", "The message asks for gift cards or prepaid cards.",
        (
            r"\bgift ?cards?\b",
            r"\b(?:itunes|google play|steam|ebay|vanilla) cards?\b",
            r"\bprepaid (?:debit |visa |credit )?cards?\b",
            r"\bvouchers?\b",
            r"\bscratch (?:off|the back)\b",
            r"\bcard (?:numbers?|codes?) and (?:the )?(?:pin|pins|codes?)\b",
        ),
        hard=True,
    ),
    TextRule(
        "crypto_or_wire", "crypto_or_wire", "The message asks for crypto, a wire transfer or a \"safe account\".",
        (
            r"\bbitcoins?\b", r"\bbtc\b", r"\bcrypto(?:currency|currencies)?\b", r"\busdt\b", r"\btether\b",
            r"\bethereum\b", r"\bbitcoin atm\b", r"\bcrypto atm\b",
            r"\bwire (?:transfer|the money|the funds|money|funds)\b", r"\bwire it\b",
            r"\bwestern union\b", r"\bmoneygram\b",
            r"\bsafe account\b",
        ),
        hard=True,
    ),
    TextRule(
        "urgency", "urgency", "It pushes you to act fast.",
        (
            r"\bwithin (?:the next )?\d+ ?(?:minutes?|mins?|hours?|hrs?)\b",
            r"\bin (?:the next )?\d+ ?(?:minutes?|mins?)\b",
            r"\bimmediately\b", r"\bright (?:now|away)\b", r"\bas soon as possible\b", r"\basap\b",
            r"\burgent(?:ly)?\b", r"\btoday or\b", r"\bact now\b", r"\bhurry\b",
            r"\b(?:final|last) (?:notice|warning|chance)\b",
            r"\bbefore (?:it'?s too late|midnight|the end of (?:the )?day)\b",
            r"\bexpires? (?:today|tonight|in \d+)\b",
        ),
    ),
    TextRule(
        "secrecy", "secrecy", "It asks you to keep this secret.",
        (
            rf"\bdon{APOS}t tell\b", r"\bdo not tell\b", r"\btell no ?one\b", rf"\bdon{APOS}t let anyone know\b",
            r"\bkeep (?:this|it) (?:between us|secret|quiet|to yourself|confidential)\b",
            r"\bbetween (?:you and me|us)\b",
            rf"\b(?:don{APOS}t|do not) (?:call|contact|phone|talk to|speak to) (?:your|the) (?:bank|family|police)\b",
            rf"\b(?:don{APOS}t|do not) (?:mention|discuss) (?:this|it)\b",
        ),
    ),
    TextRule(
        "authority_threat", "authority_threat", "It threatens arrest, legal action or a frozen account.",
        (
            r"\barrest(?:ed)?\b", r"\bwarrants?\b", r"\birs\b", r"\binternal revenue\b",
            r"\bsocial security (?:number|administration|office)\b", r"\bpolice\b", r"\bsheriff\b",
            r"\blegal action\b", r"\blawsuit\b", r"\bjail\b", r"\bbail\b", r"\bdeport(?:ed|ation)?\b",
            r"\b(?:account|card)s? (?:has been |have been |is |are |will be )?(?:frozen|suspended|locked|blocked|compromised)\b",
        ),
    ),
    TextRule(
        "whitelist_request", "whitelist_request", "It tells you to mark the payee as trusted.",
        (
            r"\bwhite ?list\b",
            r"\badd (?:me|us|this (?:account|person|payee)|[a-z]+) (?:as|to) (?:a |your )?(?:trusted|safe|verified)\b",
            r"\bmark (?:me|us|this (?:account|person|payee|payment)) as (?:trusted|safe|verified)\b",
            r"\btrusted (?:contact|payee|recipient|list)\b",
        ),
    ),
    TextRule(
        "changed_contact", "changed_contact", "The person says they have a new phone number.",
        (
            r"\bnew (?:phone )?number\b", r"\bchanged (?:my )?(?:phone )?number\b", r"\blost my phone\b",
            r"\bbroke my phone\b", r"\bnew phone\b", r"\bthis is my new\b",
        ),
    ),
)

_COMPILED = {rule.id: [re.compile(p, re.IGNORECASE) for p in rule.patterns] for rule in TEXT_RULES}


def _text_matches(rule: TextRule, fields: dict[str, str]) -> list[Span]:
    spans: list[Span] = []
    for field in ("message", "note"):
        original = fields.get(field) or ""
        if not original:
            continue
        n = normalize(original)
        for pattern in _COMPILED[rule.id]:
            for m in pattern.finditer(n.text):
                s, e = n.original_span(m.start(), m.end())
                spans.append(Span(field, s, e, original[s:e]))
    spans.sort(key=lambda sp: (sp.field != "message", sp.start))
    return spans


def evaluate(ctx: PaymentContext) -> list[dict]:
    """Return one indicator per rule that fired."""
    fields = {"message": ctx.message_text, "note": ctx.note}
    out: list[dict] = []
    for rule in TEXT_RULES:
        spans = _text_matches(rule, fields)
        if spans:
            out.append(_indicator(rule.id, rule.type, rule.label, spans[0].text, rule.weight, spans, hard=rule.hard))

    if ctx.payee_is_new:
        out.append(_indicator("new_payee", "new_payee", f"You have not paid {ctx.payee_name} before.",
                              ctx.payee_name, C.RULE_WEIGHTS["new_payee"], []))
        if not ctx.note.strip() and not ctx.message_text.strip():
            out.append(_indicator("no_context", "no_context",
                                  "There is no note or message explaining this payment to someone new.",
                                  "", C.RULE_WEIGHTS["no_context"], []))

    amount = _amount_indicator(ctx)
    if amount:
        out.append(amount)
    return out


def _amount_indicator(ctx: PaymentContext) -> dict | None:
    amt = ctx.amount_cents
    shown = "$" + format_amount(amt)
    limit = ctx.payee_spending_limit_cents or C.SENDER_SINGLE_PAYMENT_LIMIT_CENTS
    reasons: list[tuple[int, str]] = []
    if amt > limit:
        reasons.append((C.RULE_WEIGHTS["amount_unusual_high"],
                        f"{shown} is above the ${format_amount(limit)} limit for a single payment."))
    history = ctx.history_amounts_cents
    if history:
        median = statistics.median(history)
        if amt > C.UNUSUAL_MULTIPLE_OF_MEDIAN * median:
            reasons.append((C.RULE_WEIGHTS["amount_unusual_high"],
                            f"{shown} is much larger than your usual payment (about ${format_amount(int(median))})."))
        elif amt > max(history):
            reasons.append((C.RULE_WEIGHTS["amount_unusual_low"],
                            f"{shown} is larger than any payment you have made before."))
    elif amt >= C.NO_HISTORY_LARGE_AMOUNT_CENTS:
        reasons.append((C.RULE_WEIGHTS["amount_unusual_low"], f"{shown} is a large first payment."))
    if not reasons:
        return None
    weight, label = max(reasons, key=lambda r: r[0])
    return _indicator("amount", "amount", label, shown, weight, [])


def _indicator(rule_id: str, type_: str, label: str, evidence: str, weight: int, spans: list[Span],
               *, hard: bool = False) -> dict:
    return {
        "source": "rule",
        "rule_id": rule_id,
        "type": type_,
        "label": label,
        "evidence": evidence,
        "explanation": label,
        "weight": weight,
        "hard": hard,
        "spans": [s.as_dict() for s in spans],
    }
