"""Text normalisation and evidence grounding.

Evidence is only kept if it literally appears in what the sender received or typed. Matching is
done on a normalised copy (lowercase, straight quotes and dashes, collapsed whitespace), and every
match is mapped back to character offsets in the original text so the UI highlights exactly the
words that were checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..paypal import format_amount
from .types import PaymentContext

_CHAR_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ",
}

MIN_EVIDENCE_CHARS = 4


@dataclass
class Normalized:
    text: str
    index: list[int]  # index[i] = position in the original string of normalised char i

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        return self.index[start], self.index[end - 1] + 1


def normalize(original: str) -> Normalized:
    out: list[str] = []
    index: list[int] = []
    pending_space = -1
    for pos, ch in enumerate(original):
        ch = _CHAR_MAP.get(ch, ch)
        if ch.isspace():
            if pending_space < 0:
                pending_space = pos
            continue
        if pending_space >= 0:
            if out:
                out.append(" ")
                index.append(pending_space)
            pending_space = -1
        for low in ch.lower():
            out.append(low)
            index.append(pos)
    return Normalized("".join(out), index)


def norm(text: str) -> str:
    return normalize(text).text


@dataclass
class Span:
    field: str  # "message", "note", "payee" or "amount"
    start: int
    end: int
    text: str  # the original characters at [start, end)

    def as_dict(self) -> dict:
        return {"field": self.field, "start": self.start, "end": self.end, "text": self.text}


def payment_fields(ctx: PaymentContext) -> dict[str, str]:
    """The texts evidence may be quoted from."""
    amount = format_amount(ctx.amount_cents)
    whole = amount[:-3] if amount.endswith(".00") else amount
    return {
        "message": ctx.message_text,
        "note": ctx.note,
        "payee": ctx.payee_name,
        "amount": f"${amount} {amount} ${whole} {whole} USD",
    }


def find_spans(evidence: str, fields: dict[str, str], *, all_matches: bool = True) -> list[Span]:
    needle = norm(evidence).strip(" .,;:!?\"'")
    if len(needle) < MIN_EVIDENCE_CHARS:
        return []
    spans: list[Span] = []
    for field, original in fields.items():
        if not original:
            continue
        n = normalize(original)
        start = n.text.find(needle)
        while start >= 0:
            s, e = n.original_span(start, start + len(needle))
            spans.append(Span(field, s, e, original[s:e]))
            if not all_matches:
                return spans
            start = n.text.find(needle, start + len(needle))
    return spans


def ground(evidence: str, fields: dict[str, str]) -> tuple[list[Span], str | None]:
    """Return the spans for a piece of evidence, or a reason it was dropped."""
    if not evidence or len(norm(evidence).strip(" .,;:!?\"'")) < MIN_EVIDENCE_CHARS:
        return [], "too short to verify"
    spans = find_spans(evidence, fields)
    if not spans:
        return [], "not found in the message or payment"
    return spans, None
