"""GET /stats for the Insights cards, and the scam category on list rows."""

from __future__ import annotations

from datetime import timedelta

from app import db


def test_stats_count_what_happened_without_claiming_money_saved(env):
    env.pay("low", "35.00", "Grandson Leo")  # auto-captured
    approved = env.pay("high", "100.00", "Plumber", category="contractor")
    env.act(approved["id"], "approve")
    declined = env.pay("high", "500.00", "Officer Collins", category="government_impersonation")
    env.act(declined["id"], "decline")
    declined2 = env.pay("high", "200.00", "Bank Security", category="bank_impersonation")
    env.act(declined2["id"], "decline")
    cancelled = env.pay("medium", "350.00", "Gutter Pros", category="contractor")
    env.act(cancelled["id"], "cancel")
    confirmed = env.pay("medium", "80.00", "Tom Becker")
    env.act(confirmed["id"], "confirm")
    env.pay("high", "300.00", "Agent Brooks", category="government_impersonation")  # nobody answers
    env.pay("high", "50.00", "Online Friend", category="romance")  # nobody answers
    env.service.sweep(now=db.utcnow() + timedelta(seconds=121))  # both holds expire
    env.pay("high", "50.00", "Online Friend", category="romance")  # a fresh hold that stays open

    s = env.client.get("/stats").json()
    assert s["payments"] == 9
    assert s["on_hold_now"] == 1
    assert s["held_for_guardian"]["count"] == 6
    assert s["warned_sender"]["count"] == 2
    # Attempted payments held from capture: reviewed (held or warned) and not captured.
    # declined 500 + 200, cancelled 350, expired 300 + 50 = 1400.00
    assert s["held_from_capture"] == {"count": 5, "total": "1400.00", "total_cents": 140000}
    assert s["declined_by_guardian"]["count"] == 2
    assert s["cancelled_by_sender"]["count"] == 1
    assert s["expired_no_answer"]["count"] == 2
    assert s["approved_by_guardian"]["count"] == 1
    assert s["confirmed_by_sender"]["count"] == 1
    assert s["auto_captured"]["count"] == 1
    assert s["by_level"] == {"low": 1, "medium": 2, "high": 6}
    top = {c["category"]: c["count"] for c in s["top_categories"]}
    assert top == {"government_impersonation": 2, "romance": 2, "contractor": 2, "bank_impersonation": 1,
                   "uncategorised": 1}
    assert s["top_categories"][-1]["category"] == "uncategorised"  # never ranked above a real category
    assert "saved" not in str(s).lower()


def test_list_rows_carry_the_scam_category(env):
    env.pay("high", category="bank_impersonation")
    env.pay("low", payee="Leo")
    rows = env.client.get("/payments").json()["payments"]
    assert [r["category"] for r in rows] == [None, "bank_impersonation"]


def test_stats_on_an_empty_database(env):
    s = env.client.get("/stats").json()
    assert s["payments"] == 0 and s["held_from_capture"]["total"] == "0.00" and s["top_categories"] == []
