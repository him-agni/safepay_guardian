"""A payment is only completed when PayPal says the capture is settled.

PayPal can answer a capture with COMPLETED, PENDING, DECLINED or FAILED. Reporting "Payment completed" for
anything but a settled capture would tell the sender money moved when it may not have.
"""

from __future__ import annotations

from datetime import timedelta

from app import db
from app.paypal import GatewayError


def later(seconds: int = 30):
    return db.utcnow() + timedelta(seconds=seconds)


def capture_id_of(env, payment_id: str) -> str:
    return env.get(payment_id)["paypal"]["capture_id"]


# ---------------------------------------------------------------- pending


def test_pending_capture_is_not_reported_as_completed(env):
    env.paypal.next_capture_status("PENDING")
    p = env.pay("high")
    done = env.act(p["id"], "approve").json()

    assert done["status"] == "CAPTURE_PENDING"
    assert done["final"] is False
    assert "still confirming" in done["text"]["sender"]
    assert "pending" in done["text"]["guardian"]
    assert "Payment completed" not in done["text"]["sender"]
    assert "paypal.capture_pending" in env.event_types(p["id"])
    assert "paypal.captured" not in env.event_types(p["id"])
    # nothing more can be decided: the capture has been sent
    assert not any(done["can"].values())


def test_automatic_capture_that_is_pending_is_not_completed_either(env):
    env.paypal.next_capture_status("PENDING")
    p = env.pay("low", payee="Grandson Leo")
    assert p["status"] == "CAPTURE_PENDING"


def test_repeating_approve_while_pending_returns_the_same_result_but_decline_is_refused(env):
    env.paypal.next_capture_status("PENDING")
    p = env.pay("high")
    env.act(p["id"], "approve")

    again = env.act(p["id"], "approve")
    assert again.status_code == 200 and again.json()["status"] == "CAPTURE_PENDING"
    assert len(env.paypal.captures) == 1

    refused = env.act(p["id"], "decline")
    assert refused.status_code == 409
    assert "still confirming the capture" in refused.json()["message"]
    assert env.paypal.voids == []


def test_pending_capture_settles_when_paypal_reports_completed(env):
    env.paypal.next_capture_status("PENDING")
    p = env.pay("high")
    env.act(p["id"], "approve")
    cap = capture_id_of(env, p["id"])

    # too soon: the sweeper leaves it alone
    assert env.service.sweep(now=later(5))["capture_checked"] == 0

    # still pending at PayPal: checked, still pending, and not checked again straight away
    assert env.service.sweep(now=later(30))["capture_checked"] == 1
    assert env.get(p["id"])["status"] == "CAPTURE_PENDING"
    assert "paypal.capture_still_pending" in env.event_types(p["id"])

    env.paypal.set_capture_status(cap, "COMPLETED")
    env.service.sweep(now=later(60))
    done = env.get(p["id"])
    assert done["status"] == "CAPTURED"
    assert done["text"]["sender"] == "Payment completed."
    assert done["paypal"]["capture_id"] == cap
    assert len(env.paypal.captures) == 1


def test_pending_capture_that_is_declined_later_becomes_a_failed_capture(env):
    env.paypal.next_capture_status("PENDING")
    p = env.pay("high")
    env.act(p["id"], "approve")
    env.paypal.set_capture_status(capture_id_of(env, p["id"]), "DECLINED")

    env.service.sweep(now=later(30))
    failed = env.get(p["id"])
    assert failed["status"] == "CAPTURE_FAILED"
    assert "declined" in failed["last_error"]
    assert failed["can"]["retry"] and failed["can"]["decline"]


def test_retry_never_calls_a_payment_completed_because_the_authorization_shows_captured(env):
    # PayPal's authorization says CAPTURED, but the capture behind it was declined: the capture decides
    env.paypal.next_capture_status("PENDING")
    p = env.pay("high")
    env.act(p["id"], "approve")
    env.paypal.set_capture_status(capture_id_of(env, p["id"]), "DECLINED")
    env.service.sweep(now=later(30))

    retried = env.act(p["id"], "retry").json()
    assert retried["status"] == "CAPTURE_FAILED"
    assert "paypal.captured" not in env.event_types(p["id"])
    assert len(env.paypal.captures) == 1  # no second capture was made on top of a captured authorization


def test_failed_check_of_a_pending_capture_just_waits_and_logs_it(env):
    env.paypal.next_capture_status("PENDING")
    p = env.pay("high")
    env.act(p["id"], "approve")
    for _ in range(3):  # all three attempts of one check fail
        env.paypal.inject("get_capture", GatewayError("network", "read capture failed: ReadTimeout"))

    env.service.sweep(now=later(30))
    assert env.get(p["id"])["status"] == "CAPTURE_PENDING"
    assert "paypal.capture_check_failed" in env.event_types(p["id"])

    env.service.sweep(now=later(60))  # the next check works and still says pending
    assert env.get(p["id"])["status"] == "CAPTURE_PENDING"


# ---------------------------------------------------------------- refused or unknown


def test_declined_capture_is_a_failed_capture_not_a_completed_payment(env):
    env.paypal.next_capture_status("DECLINED")
    p = env.pay("high")
    failed = env.act(p["id"], "approve").json()

    assert failed["status"] == "CAPTURE_FAILED"
    assert "declined" in failed["last_error"]
    assert failed["text"]["sender"] != "Payment completed."
    assert "paypal.captured" not in env.event_types(p["id"])

    retried = env.act(p["id"], "retry").json()
    assert retried["status"] == "CAPTURED"  # the next capture is accepted
    capture_ids = [rid for op, rid in env.paypal.calls if op == "capture"]
    assert capture_ids == [f"{p['id']}-capture-1", f"{p['id']}-capture-2"]


def test_failed_capture_status_is_treated_like_declined(env):
    env.paypal.next_capture_status("FAILED")
    p = env.pay("high")
    assert env.act(p["id"], "approve").json()["status"] == "CAPTURE_FAILED"


def test_a_missing_or_unknown_capture_status_is_not_treated_as_completed(env):
    env.paypal.next_capture_status("")
    first = env.pay("high")
    assert env.act(first["id"], "approve").json()["status"] == "CAPTURE_PENDING"

    env.paypal.next_capture_status("SOMETHING_NEW")
    second = env.pay("high")
    assert env.act(second["id"], "approve").json()["status"] == "CAPTURE_PENDING"


def test_a_pending_capture_appears_in_the_guardian_queue_and_is_not_counted_as_approved(env):
    env.paypal.next_capture_status("PENDING")
    p = env.pay("high")
    env.act(p["id"], "approve")

    queue = env.service.list_payments(queue="guardian")
    assert p["id"] in [row["id"] for row in queue]
    assert env.service.stats()["approved_by_guardian"]["count"] == 0
