"""Demo seed/reset, voiding open holds on reset, the demo scenarios on rules alone, and replay mode."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import demo
from app.main import create_app
from app.paypal import FakePayPal
from app.risk import ai as ai_mod
from app.risk.engine import HybridEngine, build_assessor

from .conftest import make_settings

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {s["id"]: s for s in json.loads((ROOT / "demo" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}


def _client(tmp_path, paypal=None, assessor=None) -> TestClient:
    settings = make_settings(tmp_path)
    demo.reset(settings.database_file)
    return TestClient(create_app(settings, gateway=paypal or FakePayPal(), assessor=assessor or HybridEngine(None)))


def _pay(client, sc):
    return client.post("/payments", json={"payee_name": sc["payee"], "amount": sc["amount"], "note": sc["note"],
                                           "message_text": sc["message"]}).json()


def test_reset_seeds_history_that_insights_ignore(tmp_path):
    with _client(tmp_path) as client:
        rows = client.get("/payments").json()["payments"]
        assert len(rows) == len(demo.SEED_PAYMENTS)
        assert all(r["is_seed"] and r["status"] == "CAPTURED" for r in rows)
        assert client.get("/stats").json()["payments"] == 0


def test_reset_clears_previous_demo_payments(tmp_path):
    with _client(tmp_path) as client:
        _pay(client, SCENARIOS["1-obvious-scam"])
        demo.reset(make_settings(tmp_path).database_file)
        rows = client.get("/payments").json()["payments"]
        assert len(rows) == len(demo.SEED_PAYMENTS)


def test_seeded_history_drives_the_rules_as_the_demo_expects(tmp_path):
    with _client(tmp_path) as client:
        # Leo is trusted and $35 is normal for Margaret: no warning at all.
        leo = client.post("/payments", json={"payee_name": "Leo Martin", "amount": "35", "note": "birthday"}).json()
        assert (leo["status"], leo["risk"]["level"]) == ("CAPTURED", "low")
        assert "new_payee" not in [i["type"] for i in leo["risk"]["indicators"]]

        s1 = _pay(client, SCENARIOS["1-obvious-scam"])
        assert (s1["status"], s1["risk"]["level"]) == ("HELD", "high")  # hard rule, with or without the AI

        s2 = _pay(client, SCENARIOS["2-legit-contractor"])
        assert (s2["status"], s2["risk"]["level"]) == ("WARNED", "medium")
        assert {i["type"] for i in s2["risk"]["indicators"]} == {"new_payee", "amount"}

        s3 = _pay(client, SCENARIOS["3-polite-bank"])
        # No scam keywords: the rules alone do not hold it. In the demo, the AI is what makes it High.
        assert s3["risk"]["level"] != "high"
        assert "safe account" not in SCENARIOS["3-polite-bank"]["message"].lower()


def test_reset_voids_holds_left_open(tmp_path):
    paypal = FakePayPal()
    with _client(tmp_path, paypal=paypal) as client:
        held = _pay(client, SCENARIOS["1-obvious-scam"])
        auth = held["paypal"]["authorization_id"]
        assert paypal.authorizations[auth] == "CREATED"
        result = demo.void_open_authorizations(make_settings(tmp_path).database_file, paypal)
        assert result == {"voided": [auth], "failed": []}
        assert paypal.authorizations[auth] == "VOIDED"


def test_replay_mode_serves_stored_replies_and_falls_back_for_anything_else(tmp_path):
    cache = tmp_path / "cache"
    settings = make_settings(tmp_path, ai_provider="replay", ai_cache_dir=str(cache))
    engine = build_assessor(settings)
    assert isinstance(engine.provider, ai_mod.CachingProvider) and engine.provider.offline

    from app.risk.types import PaymentContext

    ctx = PaymentContext(amount_cents=30000, currency="USD", payee_name="Secure Holdings LLC", payee_is_new=True,
                         payee_trusted=False, message_text=SCENARIOS["3-polite-bank"]["message"])
    reply = {"category": "bank_impersonation",
             "indicators": [{"type": "safe_account", "evidence": "move $300 to the protected account",
                             "explanation": "Banks never ask you to move money."}],
             "payment_matches_message": False, "confidence": "high", "recommended_action": "guardian_review",
             "summary": "This looks like a bank impersonation scam."}

    class Recorder:
        model = settings.gemini_model

        def generate(self, system, user, schema):
            return json.dumps(reply)

        def check(self):
            return True

    # Store the reply the way a live run would (same prompt, including the retrieved patterns), then replay it
    # with no model at all.
    from app.risk import patterns

    patterns_for_prompt = patterns.search(ctx.message_text)
    ai_mod.CachingProvider(Recorder(), cache).generate(
        ai_mod.SYSTEM_PROMPT, ai_mod.build_user_prompt(ctx, patterns_for_prompt), {})

    replayed = engine.assess(ctx)
    assert (replayed.level, replayed.mode) == ("high", "hybrid")
    assert replayed.components["ai_cached"] is True

    other = engine.assess(PaymentContext(amount_cents=5000, currency="USD", payee_name="X", payee_is_new=True,
                                         payee_trusted=False, message_text="Something nobody stored"))
    assert other.mode == "rules_only" and "no stored AI reply" in other.ai_error


def test_replay_mode_health(tmp_path):
    settings = make_settings(tmp_path, ai_provider="replay", ai_cache_dir=str(tmp_path / "cache"))
    with TestClient(create_app(settings, gateway=FakePayPal())) as client:
        assert client.get("/health").json()["ai"]["mode"] == "replay"
