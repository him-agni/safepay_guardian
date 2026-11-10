"""Robustness and abuse cases found in the security review: bad AI replies, concurrent cache use,
non-finite numbers, oversized or out-of-range requests, and messages on final payments."""

from __future__ import annotations

import json
import threading
from datetime import date

import httpx
from fastapi.testclient import TestClient

from app import activity_query as aq
from app.main import MAX_BODY_BYTES, create_app
from app.paypal import FakePayPal
from app.risk import ai as ai_mod
from app.risk.engine import HybridEngine

from .conftest import make_settings


def _gemini(tmp_path, handler) -> ai_mod.GeminiProvider:
    settings = make_settings(tmp_path, ai_provider="gemini", gemini_api_key="k-123")
    return ai_mod.GeminiProvider(settings, transport=httpx.MockTransport(handler))


def test_a_malformed_ai_reply_is_an_ai_error_not_a_crash(tmp_path):
    for body in (b"<html>proxy error</html>", b'["not", "an", "object"]', b'{"candidates": "nope"}'):
        provider = _gemini(tmp_path, lambda r, body=body: httpx.Response(200, content=body))
        try:
            provider.generate("s", "u", {})
        except ai_mod.AIError as exc:
            assert exc.kind == "invalid_json", body
        else:
            raise AssertionError(f"expected an AIError for {body!r}")


class Exploding:
    model = "exploding"

    def generate(self, system, user, schema):
        raise RuntimeError("something nobody expected")

    def check(self):
        return True


def test_an_unexpected_ai_failure_still_creates_the_payment_on_rules_only(tmp_path):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, gateway=FakePayPal(), assessor=HybridEngine(Exploding()))) as client:
        resp = client.post("/payments", json={"payee_name": "Officer Smith", "amount": "500.00",
                                              "message_text": "Pay the fine in gift cards today or be arrested."})
        assert resp.status_code == 201, resp.text
        p = resp.json()
        assert p["status"] == "HELD" and p["risk"]["mode"] == "rules_only"  # the gift-card rule still holds it


class Counting:
    model = "fake"

    def __init__(self):
        self.calls = 0

    def generate(self, system, user, schema):
        self.calls += 1
        return '{"ok": true}'


def test_an_unreadable_stored_reply_is_treated_as_missing(tmp_path):
    inner = Counting()
    cache = ai_mod.CachingProvider(inner, tmp_path / "cache")
    cache.generate("s", "u", {})
    stored = next((tmp_path / "cache").glob("*.json"))
    stored.write_text('{"response": "half a fi', encoding="utf-8")  # e.g. a write that was interrupted
    assert cache.generate("s", "u", {}) == '{"ok": true}'
    assert inner.calls == 2 and not cache.last_was_cached
    assert json.loads(stored.read_text(encoding="utf-8"))["response"] == '{"ok": true}'  # repaired
    assert not list((tmp_path / "cache").glob("*.tmp"))


def test_each_thread_reads_back_its_own_cache_status(tmp_path):
    cache = ai_mod.CachingProvider(Counting(), tmp_path / "cache")
    cache.generate("s", "stored", {})  # now stored
    results = {}
    gate = threading.Barrier(2)

    def call(name, prompt):
        cache.generate("s", prompt, {})
        gate.wait()  # both calls finished before either reads its status
        results[name] = cache.last_was_cached

    threads = [threading.Thread(target=call, args=("stored", "stored")),
               threading.Thread(target=call, args=("live", "new prompt"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == {"stored": True, "live": False}


def test_ask_drops_amounts_that_are_not_finite():
    columns = [aq.ColumnSpec(id="amount", label="Amount", type="number")]

    class Reply:
        model = "fake"

        def generate(self, system, user, schema):
            return json.dumps({"understood": True, "explanation": "x", "sort": {"column": "none", "direction": "asc"},
                               "filters": [{"column": "amount", "operator": "greater_than", "value": "inf"},
                                           {"column": "amount", "operator": "less_than", "value": "nan"}]})

    out = aq.ask(Reply(), aq.AskRequest(question="huge payments", columns=columns), date(2026, 11, 10))
    assert out.filters == [] and len(out.ignored) == 2
    json.dumps(out.as_dict(), allow_nan=False)  # the response can always be sent


def test_out_of_range_list_limits_are_rejected(env):
    assert env.client.get("/payments", params={"limit": -1}).status_code == 422
    assert env.client.get("/payments", params={"limit": 501}).status_code == 422
    assert env.client.get("/payments", params={"limit": 1}).status_code == 200


def test_oversized_request_bodies_are_refused_before_they_are_read(env):
    resp = env.client.post("/screenshots", content=b"x" * (MAX_BODY_BYTES + 1),
                           headers={"content-type": "application/json"})
    assert resp.status_code == 413 and resp.json()["error"] == "too_large"


def test_messages_cannot_be_added_once_a_payment_is_final(env):
    p = env.pay("high")
    assert env.client.post(f"/payments/{p['id']}/messages",
                           json={"from_role": "guardian", "body": "Who asked you for this?"}).status_code == 201
    env.act(p["id"], "decline")
    resp = env.client.post(f"/payments/{p['id']}/messages", json={"from_role": "sender", "body": "ok"})
    assert resp.status_code == 409
    assert len(env.get(p["id"])["messages"]) == 1
