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


def test_stats_timeline_lists_recent_outcomes(env):
    env.pay("low", "35.00", "Grandson Leo")  # captured automatically
    declined = env.pay("high", "500.00", "Officer Collins")
    env.act(declined["id"], "decline")
    env.pay("high", "200.00", "Bank Security")  # still waiting
    s = env.client.get("/stats").json()
    assert s["recent_days"] == 30
    assert [r["outcome"] for r in s["recent"]] == ["captured", "stopped", "open"]
    assert not any(r["past"] for r in s["recent"])
    assert all(r["at"].endswith("Z") for r in s["recent"])


def test_stats_flagged_payees_rank_by_how_often_they_were_warned_or_held(env):
    for _ in range(2):
        p = env.pay("high", "300.00", "Agent Brooks")
        env.act(p["id"], "decline")
    env.pay("medium", "80.00", "Gutter Pros")  # warned, still open
    env.pay("high", "900.00", "Online Friend")
    env.pay("low", "35.00", "Grandson Leo")  # never warned or held: not listed
    flagged = env.client.get("/stats").json()["flagged_payees"]
    assert [(f["payee"], f["count"], f["not_captured"]) for f in flagged] == [
        ("Agent Brooks", 2, 2), ("Online Friend", 1, 0), ("Gutter Pros", 1, 0)]
    assert flagged[0]["total"] == "600.00"


def test_list_rows_carry_the_scam_category(env):
    env.pay("high", category="bank_impersonation")
    env.pay("low", payee="Leo")
    rows = env.client.get("/payments").json()["payments"]
    assert [r["category"] for r in rows] == [None, "bank_impersonation"]


def test_stats_on_an_empty_database(env):
    s = env.client.get("/stats").json()
    assert s["payments"] == 0 and s["held_from_capture"]["total"] == "0.00" and s["top_categories"] == []


def test_list_rows_carry_a_risk_brief_with_quoted_evidence_only(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.paypal import FakePayPal
    from app.risk.engine import HybridEngine

    from .conftest import make_settings

    app = create_app(make_settings(tmp_path), gateway=FakePayPal(), assessor=HybridEngine(None))
    with TestClient(app) as client:
        client.post("/payments", json={"payee_name": "Officer Collins", "amount": "500",
                                       "message_text": "Pay in gift cards within 30 minutes or be arrested."})
        [row] = client.get("/payments").json()["payments"]
    brief = row["risk_brief"]
    assert brief["checked_by"] == "rules" and brief["ai_flagged"] is False
    assert brief["summary"]
    quotes = [q["evidence"] for q in brief["top_evidence"]]
    assert quotes[0] == "gift cards"  # the hard rule comes first
    assert len(quotes) <= 3
    assert "Officer Collins" not in quotes  # the "new payee" signal is not a quote from the message


def test_list_rows_without_an_assessment_have_no_brief(env):
    from app import demo

    demo.reset(env.service.db_path)
    rows = env.client.get("/payments").json()["payments"]
    assert rows and all(r["risk_brief"] is None for r in rows)
