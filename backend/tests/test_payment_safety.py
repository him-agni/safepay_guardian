"""Payment safety tests against the fake PayPal.

Covers the spec's "Part 2: payment safety tests" plus the edge cases found in the plan review:
concurrent approve/cancel, lost responses, WARNED timeouts, failed voids and restart recovery.
"""

from __future__ import annotations

import threading
from datetime import timedelta

from app import db
from app.paypal import LOSE_RESPONSE, GatewayError
from app.state import ACTIONS, S


def later(seconds: int = 121):
    return db.utcnow() + timedelta(seconds=seconds)


# ---------------------------------------------------------------- the three lanes

def test_low_risk_is_captured_automatically(env):
    p = env.pay("low", "35.00", "Grandson Leo")
    assert p["status"] == "CAPTURED"
    assert p["paypal"]["capture_id"]
    assert len(env.paypal.captures) == 1
    assert p["text"]["sender"] == "Payment completed."


def test_medium_risk_waits_for_sender_then_confirm_captures(env):
    p = env.pay("medium", "350.00", "Gutter Pros")
    assert p["status"] == "WARNED"
    assert p["can"]["confirm"] and p["can"]["cancel"] and not p["can"]["approve"]
    assert env.paypal.captures == []

    done = env.act(p["id"], "confirm").json()
    assert done["status"] == "CAPTURED"
    assert done["decided_by"] == "sender"
    assert len(env.paypal.captures) == 1


def test_medium_risk_cancel_voids(env):
    p = env.pay("medium")
    done = env.act(p["id"], "cancel").json()
    assert done["status"] == "VOIDED"
    assert done["void_reason"] == "sender_cancel"
    assert done["text"]["sender"] == "You cancelled this payment. No payment was taken."
    assert env.paypal.authorizations[p["paypal"]["authorization_id"]] == "VOIDED"


def test_high_risk_is_held_and_sender_cannot_confirm_it(env):
    p = env.pay("high")
    assert p["status"] == "HELD"
    assert p["text"]["sender"].startswith("This payment is on hold.")
    assert p["hold_seconds_left"] > 100

    resp = env.act(p["id"], "confirm")
    assert resp.status_code == 409
    assert "only the guardian can approve it" in resp.json()["message"]
    assert env.paypal.captures == []


def test_guardian_decline_voids_with_paypal_wording(env):
    p = env.pay("high")
    done = env.act(p["id"], "decline", note="This is a scam, call me").json()
    assert done["status"] == "VOIDED"
    assert done["decision_note"] == "This is a scam, call me"
    assert done["text"]["guardian"].startswith("Payment not captured, authorization voided.")
    assert done["text"]["sender"] == "Declined by your guardian. No payment was taken."
    assert env.paypal.captures == []


def test_sender_can_cancel_a_held_payment(env):
    p = env.pay("high")
    assert env.act(p["id"], "cancel").json()["status"] == "VOIDED"


# ---------------------------------------------------------------- idempotency and races

def test_approve_twice_captures_once_and_returns_same_result(env):
    p = env.pay("high")
    first = env.act(p["id"], "approve")
    second = env.act(p["id"], "approve")
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "CAPTURED"
    assert first.json()["paypal"]["capture_id"] == second.json()["paypal"]["capture_id"]
    assert len(env.paypal.captures) == 1
    assert "decision.repeated" in env.event_types(p["id"])


def test_two_concurrent_approvals_capture_once(env):
    p = env.pay("high")
    env.paypal.capture_delay = 0.3  # widen the race window
    results: list = []

    def approve():
        results.append(env.service.act(p["id"], "approve"))

    threads = [threading.Thread(target=approve) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert [r["status"] for r in results] == ["CAPTURED"] * 4
    assert len({r["paypal"]["capture_id"] for r in results}) == 1
    assert len(env.paypal.captures) == 1


def test_concurrent_approve_and_cancel_first_valid_change_wins(env):
    p = env.pay("high")
    env.paypal.capture_delay = 0.3
    outcomes: dict = {}

    def run(action):
        try:
            outcomes[action] = env.service.act(p["id"], action)["status"]
        except Exception as exc:  # noqa: BLE001 - the loser must get a Conflict
            outcomes[action] = type(exc).__name__

    threads = [threading.Thread(target=run, args=(a,)) for a in ("approve", "cancel")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = env.get(p["id"])["status"]
    assert sorted(outcomes.values()) in (["CAPTURED", "Conflict"], ["Conflict", "VOIDED"])
    auth_status = env.paypal.authorizations[p["paypal"]["authorization_id"]]
    assert (final, auth_status) in (("CAPTURED", "CAPTURED"), ("VOIDED", "VOIDED"))
    assert len(env.paypal.captures) + len(env.paypal.voids) == 1


def test_decline_then_approve_is_rejected_without_capture(env):
    p = env.pay("high")
    env.act(p["id"], "decline")
    resp = env.act(p["id"], "approve")
    assert resp.status_code == 409
    assert resp.json()["message"] == "Cannot approve this payment: it was already declined by the guardian."
    assert resp.json()["payment"]["status"] == "VOIDED"
    assert env.paypal.captures == []
    assert "decision.rejected" in env.event_types(p["id"])


def test_approve_then_decline_is_rejected_and_stays_captured(env):
    p = env.pay("high")
    env.act(p["id"], "approve")
    resp = env.act(p["id"], "decline")
    assert resp.status_code == 409
    assert "already approved and captured" in resp.json()["message"]
    assert env.get(p["id"])["status"] == "CAPTURED"
    assert env.paypal.voids == []


def test_decline_twice_is_idempotent(env):
    p = env.pay("high")
    assert env.act(p["id"], "decline").status_code == 200
    again = env.act(p["id"], "decline")
    assert again.status_code == 200 and again.json()["status"] == "VOIDED"
    assert len(env.paypal.voids) == 1


# ---------------------------------------------------------------- timeouts (silence fails safe)

def test_hold_timeout_voids_and_later_approval_is_rejected(env):
    p = env.pay("high")
    assert env.service.sweep(now=later(60))["expired"] == 0  # not yet

    env.service.sweep(now=later())
    expired = env.get(p["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["void_reason"] == "timeout"
    assert expired["decided_by"] == "system"
    assert env.paypal.authorizations[p["paypal"]["authorization_id"]] == "VOIDED"
    assert "Payment not captured, authorization voided." in expired["text"]["guardian"]

    resp = env.act(p["id"], "approve")
    assert resp.status_code == 409
    assert "hold already expired" in resp.json()["message"]
    assert env.paypal.captures == []


def test_unanswered_medium_warning_also_times_out(env):
    p = env.pay("medium")
    env.service.sweep(now=later())
    assert env.get(p["id"])["status"] == "EXPIRED"


def test_captured_and_voided_payments_are_not_touched_by_the_sweeper(env):
    low = env.pay("low", payee="Grandson Leo")
    declined = env.pay("high")
    env.act(declined["id"], "decline")
    env.service.sweep(now=later(10_000))
    assert env.get(low["id"])["status"] == "CAPTURED"
    assert env.get(declined["id"])["status"] == "VOIDED"


# ---------------------------------------------------------------- PayPal failures

def test_capture_error_shows_failure_and_retry_uses_a_new_request_id(env):
    p = env.pay("high")
    env.paypal.inject("capture", GatewayError("client", "capture failed: HTTP 422 INSTRUMENT_DECLINED",
                                              status_code=422, issue="INSTRUMENT_DECLINED"))
    failed = env.act(p["id"], "approve").json()
    assert failed["status"] == "CAPTURE_FAILED"
    assert "INSTRUMENT_DECLINED" in failed["last_error"]
    assert failed["can"]["retry"] and failed["can"]["decline"]
    assert env.paypal.captures == []

    retried = env.act(p["id"], "retry").json()
    assert retried["status"] == "CAPTURED"
    assert len(env.paypal.captures) == 1
    capture_ids = [rid for op, rid in env.paypal.calls if op == "capture"]
    assert capture_ids == [f"{p['id']}-capture-1", f"{p['id']}-capture-2"]


def test_lost_capture_response_is_retried_with_same_id_and_captures_once(env):
    p = env.pay("high")
    env.paypal.inject("capture", LOSE_RESPONSE)  # PayPal captured, but we never saw the answer
    done = env.act(p["id"], "approve").json()
    assert done["status"] == "CAPTURED"
    assert len(env.paypal.captures) == 1
    capture_ids = [rid for op, rid in env.paypal.calls if op == "capture"]
    assert capture_ids == [f"{p['id']}-capture-1"] * 2


def test_network_failure_after_retries_keeps_the_same_request_id_for_the_manual_retry(env):
    p = env.pay("high")
    for _ in range(3):
        env.paypal.inject("capture", GatewayError("network", "capture failed: ConnectTimeout"))
    failed = env.act(p["id"], "approve").json()
    assert failed["status"] == "CAPTURE_FAILED"

    env.act(p["id"], "retry")
    capture_ids = {rid for op, rid in env.paypal.calls if op == "capture"}
    assert capture_ids == {f"{p['id']}-capture-1"}
    assert len(env.paypal.captures) == 1


def test_capture_skipped_when_paypal_already_shows_voided(env):
    p = env.pay("high")
    env.paypal.set_status(p["paypal"]["authorization_id"], "VOIDED")
    done = env.act(p["id"], "approve").json()
    assert done["status"] == "VOIDED"
    assert "already voided" in done["last_error"]
    assert not any(op == "capture" for op, _ in env.paypal.calls)


def test_capture_skipped_when_paypal_shows_expired(env):
    p = env.pay("high")
    env.paypal.set_status(p["paypal"]["authorization_id"], "EXPIRED")
    done = env.act(p["id"], "approve").json()
    assert done["status"] == "EXPIRED"
    assert "expired" in done["last_error"]
    assert env.paypal.captures == []


def test_voided_authorization_on_capture_maps_to_clean_message(env):
    p = env.pay("high")
    auth_id = p["paypal"]["authorization_id"]
    # Read shows CREATED, then the authorization is voided before the capture lands.
    env.paypal.inject("capture", lambda: env.paypal.set_status(auth_id, "VOIDED"))
    done = env.act(p["id"], "approve").json()
    assert done["status"] == "VOIDED"
    assert done["last_error"] == "PayPal shows this authorization was already voided. Nothing was captured."
    assert env.paypal.captures == []


def test_card_declined_at_authorize_is_auth_failed_with_nothing_to_void(env):
    env.paypal.inject("create", GatewayError("client", "create order failed: HTTP 422 INSTRUMENT_DECLINED",
                                             status_code=422, issue="INSTRUMENT_DECLINED"))
    p = env.pay("high")
    assert p["status"] == "AUTH_FAILED"
    assert p["text"]["sender"] == "The payment could not be started. No payment was taken."
    assert p["paypal"]["authorization_id"] is None
    assert not any(op == "void" for op, _ in env.paypal.calls)
    env.service.sweep(now=later(10_000))
    assert env.get(p["id"])["status"] == "AUTH_FAILED"


def test_void_failure_is_visible_and_the_sweeper_retries_it(env):
    p = env.pay("high")
    env.paypal.inject("void", GatewayError("client", "void failed: HTTP 422 UNPROCESSABLE", status_code=422,
                                           issue="UNPROCESSABLE"))
    failed = env.act(p["id"], "decline").json()
    assert failed["status"] == "VOID_FAILED"
    assert failed["text"]["sender"] == "This payment is stopped and will not be sent."
    assert not failed["can"]["approve"]

    env.service.sweep()
    done = env.get(p["id"])
    assert done["status"] == "VOIDED"
    void_ids = [rid for op, rid in env.paypal.calls if op == "void"]
    assert void_ids == [f"{p['id']}-void-1", f"{p['id']}-void-2"]


def test_approve_is_rejected_while_a_void_is_failing(env):
    p = env.pay("high")
    env.paypal.inject("void", GatewayError("server", "void failed: HTTP 503"))
    env.paypal.inject("void", GatewayError("server", "void failed: HTTP 503"))
    env.paypal.inject("void", GatewayError("server", "void failed: HTTP 503"))
    env.act(p["id"], "decline")
    assert env.act(p["id"], "approve").status_code == 409
    assert env.paypal.captures == []


# ---------------------------------------------------------------- restart recovery

def test_restart_resumes_a_payment_stuck_in_capturing_without_double_capture(env):
    p = env.pay("high")
    # Simulate a crash after PayPal captured but before we stored the result.
    claimed, _ = env.service._transition(p["id"], ACTIONS["approve"].allowed_from, S.CAPTURING, "guardian")
    assert claimed
    env.paypal.capture(p["paypal"]["authorization_id"], request_id=f"{p['id']}-capture-1")

    env.service.recover()
    done = env.get(p["id"])
    assert done["status"] == "CAPTURED"
    assert len(env.paypal.captures) == 1
    assert "recovery.resumed" in env.event_types(p["id"])


# ---------------------------------------------------------------- audit log and validation

def test_every_state_change_is_in_the_audit_log(env):
    p = env.pay("high")
    env.act(p["id"], "approve")
    events = env.get(p["id"])["events"]
    path = [(e["detail"]["from"], e["detail"]["to"]) for e in events if e["type"] == "status.changed"]
    assert path == [("CREATED", "AUTHORIZED"), ("AUTHORIZED", "HELD"), ("HELD", "CAPTURING"),
                    ("CAPTURING", "CAPTURED")]
    types = [e["type"] for e in events]
    for expected in ("payment.created", "risk.assessed", "paypal.authorized", "paypal.authorization_read",
                     "paypal.capture_requested", "paypal.captured", "decision.accepted"):
        assert expected in types


def test_request_ids_are_deterministic(env):
    p = env.pay("high")
    env.act(p["id"], "decline")
    ids = [rid for op, rid in env.paypal.calls if rid]
    assert ids == [f"{p['id']}-create", f"{p['id']}-void-1"]


def test_invalid_amounts_are_rejected(env):
    for amount in ("0", "-5", "10000.01", "12.345"):
        resp = env.client.post("/payments", json={"payee_name": "X", "amount": amount})
        assert resp.status_code == 422, amount


def test_unknown_payment_is_404(env):
    assert env.client.get("/payments/nope").status_code == 404
    assert env.act("nope", "approve").status_code == 404


def test_guardian_queue_lists_held_payments_newest_first(env):
    env.pay("low", payee="Grandson Leo")
    a = env.pay("high", payee="A")
    b = env.pay("high", payee="B")
    queue = env.client.get("/payments", params={"queue": "guardian"}).json()["payments"]
    assert [p["id"] for p in queue] == [b["id"], a["id"]]


def test_messages_thread(env):
    p = env.pay("high")
    env.client.post(f"/payments/{p['id']}/messages", json={"from_role": "guardian",
                                                          "body": "Did you speak to this person?"})
    env.client.post(f"/payments/{p['id']}/messages", json={"from_role": "sender", "body": "Only by text."})
    msgs = env.get(p["id"])["messages"]
    assert [(m["from_role"], m["body"]) for m in msgs] == [
        ("guardian", "Did you speak to this person?"), ("sender", "Only by text.")]
