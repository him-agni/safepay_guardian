"""Step 5: scam-pattern retrieval.

A small library of known scam scripts, written for this project in our own words (no real
messages or personal data), searched with BM25. Matches are shown as "similar known pattern" and
passed to the AI as context. They add no weight on their own.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from . import config as C


@dataclass(frozen=True)
class ScamPattern:
    id: str
    category: str
    title: str
    text: str


PATTERNS: tuple[ScamPattern, ...] = (
    ScamPattern("gov-irs", "government_impersonation", "Tax agency arrest threat",
                "This is the IRS tax agency. You owe back taxes and a warrant has been issued for your arrest. "
                "Police will come today unless you pay immediately with gift cards or a wire transfer. "
                "Do not hang up and do not tell anyone."),
    ScamPattern("gov-ssa", "government_impersonation", "Social Security number suspended",
                "Your Social Security number has been suspended because of suspicious activity linked to a crime. "
                "To avoid legal action and arrest, move your money to a secure government account and pay a fee now."),
    ScamPattern("gov-warrant", "government_impersonation", "Missed jury duty or court warrant",
                "You missed jury duty and the court has issued a warrant. Pay the fine now by prepaid card or "
                "the sheriff will arrest you. Stay on the line and keep this confidential."),
    ScamPattern("gov-immigration", "government_impersonation", "Immigration status threat",
                "Immigration office notice: there is a problem with your documents. Pay the processing fee today "
                "or you will be deported. Do not contact a lawyer."),
    ScamPattern("bank-safe-account", "bank_impersonation", "Bank fraud team asks to move money to a safe account",
                "This is the fraud department of your bank. We detected unusual activity and your savings are at risk. "
                "To protect your money, transfer it to a new protected safe account our security team created for you. "
                "Do not discuss this with branch staff, they may be involved."),
    ScamPattern("bank-frozen", "bank_impersonation", "Account frozen, pay to unlock",
                "Your bank account has been frozen due to suspicious login attempts. Send a verification payment "
                "to secure and unlock your account within 24 hours, and tell no one about this security case."),
    ScamPattern("bank-card-blocked", "bank_impersonation", "Card blocked, verify by payment",
                "Alert: your card has been blocked. Confirm your identity by sending a small payment and reading us "
                "the code we text you. This is urgent and your account will be closed otherwise."),
    ScamPattern("tech-virus", "tech_support", "Virus warning and paid technician",
                "Warning: your computer is infected with a virus and your bank details are exposed. Call our certified "
                "technician now. Pay for the repair and allow remote access so we can remove the virus."),
    ScamPattern("tech-refund", "tech_support", "Refund overpayment",
                "We owe you a refund for a cancelled subscription but accidentally sent too much. Log in with remote "
                "access software and send back the difference right away by gift card or transfer."),
    ScamPattern("tech-subscription", "tech_support", "Fake subscription renewal",
                "Your antivirus subscription renewed for 399 dollars. If you did not authorise this, call support "
                "to cancel and pay a small fee to process the refund."),
    ScamPattern("grand-jail", "grandparent", "Grandchild in jail needs bail",
                "Grandma, it's me. I'm in jail after an accident and need bail money right now. Please don't tell "
                "mom and dad, I'm so embarrassed. My lawyer will explain how to send the money."),
    ScamPattern("grand-hospital", "grandparent", "Relative in hospital abroad",
                "Your grandson was in a car accident abroad and is in hospital. He needs money for treatment before "
                "they will help him. Send it immediately and keep this between us."),
    ScamPattern("family-new-number", "family_impersonation", "Family member with a new number",
                "Hi mum it's me, I lost my phone so this is my new number. Can you send money for a bill or rent "
                "today? I'll pay you back, my banking app isn't working on the new phone."),
    ScamPattern("romance-ticket", "romance", "Online partner needs money to travel",
                "My love, I want to finally meet you but I can't afford the plane ticket. Could you send money for the "
                "flight again? I promise this is the last time. I miss you so much."),
    ScamPattern("romance-emergency", "romance", "Online partner has an emergency abroad",
                "My darling, I'm stuck overseas, my wallet was stolen and I need money for customs fees and a "
                "hospital bill. Only you can help me. Please send it quickly."),
    ScamPattern("prize-fee", "prize", "Prize or lottery requires a fee",
                "Congratulations, you have won a prize in our lottery sweepstakes. To release your winnings you must "
                "first pay a processing fee and taxes. Claim within 48 hours or the prize is forfeited."),
    ScamPattern("prize-car", "prize", "Won a car, pay delivery",
                "You are the lucky winner of a new car. Pay the delivery and insurance fee today to receive your prize."),
    ScamPattern("invoice-change", "contractor", "Contractor changed bank details",
                "Please note our bank details have changed. Pay the outstanding invoice to the new account below "
                "today, the old account is closed. Do not call the office, just reply by email."),
    ScamPattern("contractor-upfront", "contractor", "Door-to-door contractor wants full payment upfront",
                "I noticed damage on your roof. I can fix it today at a discount, but you must pay the full amount "
                "upfront in cash or transfer before the materials are ordered."),
    ScamPattern("utility-shutoff", "utility_impersonation", "Utility shut-off threat",
                "Final notice from your electric company: your power will be disconnected within the hour unless you "
                "pay the overdue balance immediately by prepaid card."),
    ScamPattern("delivery-fee", "delivery", "Parcel held, pay redelivery fee",
                "Your package could not be delivered. Pay a small redelivery fee within 24 hours or it will be "
                "returned to the sender."),
    ScamPattern("job-check", "employment", "Job offer with overpaid check",
                "Congratulations on your new remote job. We sent a check for equipment; deposit it and send the extra "
                "money back to our supplier by transfer today."),
    ScamPattern("invest-crypto", "investment", "Guaranteed crypto investment",
                "Join our investment group with guaranteed returns of 30 percent a month. Deposit with bitcoin or crypto "
                "now, the opportunity closes soon. Don't tell your bank, they don't understand crypto."),
    ScamPattern("charity-disaster", "charity", "Disaster charity appeal",
                "Help the victims of the disaster now. Donate today by gift card or wire, every minute counts. "
                "Our charity cannot take credit cards."),
    ScamPattern("rental-deposit", "rental", "Rental listing needs deposit before viewing",
                "The apartment is still available but many people want it. Send the deposit today to hold it, "
                "I am out of the country so you can't view it before paying."),
)

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be but by can do for from has have i i'm if in is it its me my of on or our so that the "
    "their them then there this to too us was we will with you your yours it's im".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower().replace("'", "")) if t not in _STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in docs]
        self.lengths = [len(d) for d in docs]
        self.avg_len = sum(self.lengths) / len(docs)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, length in zip(self.docs, self.lengths):
            s = 0.0
            for t in set(query):
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg_len))
            out.append(s)
        return out


_INDEX = BM25([tokenize(f"{p.title} {p.text}") for p in PATTERNS])


def search(text: str, *, top_k: int = C.PATTERN_TOP_K, min_score: float = C.PATTERN_MIN_SCORE) -> list[dict]:
    query = tokenize(text)
    if not query:
        return []
    ranked = sorted(zip(_INDEX.scores(query), PATTERNS), key=lambda x: -x[0])
    floor = max(min_score, ranked[0][0] * C.PATTERN_MIN_RELATIVE) if min_score > 0 else 0
    return [
        {"id": p.id, "category": p.category, "title": p.title, "score": round(s, 2)}
        for s, p in ranked[:top_k]
        if s >= floor and s > 0
    ]
