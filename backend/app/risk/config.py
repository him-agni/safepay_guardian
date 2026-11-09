"""Every risk-engine number in one place.

Tuned once on Tuesday Nov 10 against the 16 evaluation cases, then frozen (see docs/BUILD_PLAN.md).
Changing a value here changes the evaluation results, so re-run eval/run_eval.py after any edit.
"""

CONFIG_VERSION = "2026-11-10.1"

# Score -> level. Score is a heuristic sum of indicator weights, capped at 100. It is not a probability.
MEDIUM_AT = 30
HIGH_AT = 60
SCORE_CAP = 100

# Rule weights. "hard" rules set the level to high on their own.
RULE_WEIGHTS = {
    "urgency": 25,
    "secrecy": 30,
    "authority_threat": 25,
    "new_payee": 15,
    "amount_unusual_high": 20,  # far above the sender's usual amount, or above the limit
    "amount_unusual_low": 10,  # above anything the sender has paid before
    "whitelist_request": 30,
    "changed_contact": 25,
    "no_context": 15,
}
HARD_RULES = {"gift_card", "crypto_or_wire"}

# Amount thresholds
SENDER_SINGLE_PAYMENT_LIMIT_CENTS = 300_00  # default per-payment limit when a payee has none
UNUSUAL_MULTIPLE_OF_MEDIAN = 3.0
NO_HISTORY_LARGE_AMOUNT_CENTS = 200_00

# Weights for grounded AI indicators, by type. The same type from a rule and from the AI counts once
# (the higher weight).
AI_WEIGHTS = {
    "urgency": 25,
    "secrecy": 30,
    "authority_threat": 25,
    "impersonation": 30,
    "gift_card": 40,
    "crypto_or_wire": 40,
    "safe_account": 40,
    "remote_access": 30,
    "upfront_fee": 30,
    "emotional_manipulation": 20,
    "too_good_to_be_true": 20,
    "changed_contact": 25,
    "whitelist_request": 30,
    "prompt_injection": 30,
    "payment_mismatch": 20,
    "other": 10,
}

# The AI sets a minimum level only with at least one grounded indicator.
AI_FLOOR_HIGH_CONFIDENCE = {"medium", "high"}  # guardian_review at these confidences -> high

# Scam-pattern retrieval
PATTERN_TOP_K = 3
PATTERN_MIN_SCORE = 6.0  # legitimate messages scored under 3 in calibration; real matches 12+
PATTERN_MIN_RELATIVE = 0.6  # also keep only matches within 60% of the best one
