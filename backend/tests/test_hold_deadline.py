"""The hold deadline is enforced by the decision itself, not only by the sweeper.

The sweeper runs every few seconds. Between the deadline and the next sweep, an approval must not capture.
"""

from __future__ import annotations

from datetime import timedelta

from app import db
from app.paypal import GatewayError


def expire_now(env, payment_id: str, seconds_ago: int = 5) -> None:
    """Move the deadline into the past without running the sweeper."""
    past = db.iso(db.utcnow() - timedelta(seconds=seconds_ago))
    with db.connect(env.service.db_path) as conn:
        conn.execute("UPDATE payments SET hold_expires_at = ? WHERE id = ?", (past, payment_id))
        conn.commit()


def test_guardian_approval_after_the_deadline_does_not_capture(env):
    p = env.pay("high")
    expire_now(env, p["id"])

    resp = env.act(p["id"], "approve")
    assert resp.status_code == 409
    assert "hold already expired" in resp.json()["message"]

    after = env.get(p["id"])
    assert after["status"] == "EXPIRED"
    assert after["void_reason"] == "timeout"
    assert env.paypal.captures == []
    assert env.paypal.authorizations[p["paypal"]["authorization_id"]] == "VOIDED"
    assert "decision.too_late" in env.event_types(p["id"])


def test_sender_confirmation_after_the_deadline_does_not_capture(env):
    p = env.pay("medium")
    expire_now(env, p["id"])

    resp = env.act(p["id"], "confirm")
    assert resp.status_code == 409
    assert env.get(p["id"])["status"] == "EXPIRED"
    assert env.paypal.captures == []


def test_retrying_a_failed_capture_after_the_deadline_voids_instead(env):
    p = env.pay("high")
    env.paypal.inject("capture", GatewayError("client", "capture failed: HTTP 422 INSTRUMENT_DECLINED",
                                              status_code=422, issue="INSTRUMENT_DECLINED"))
    assert env.act(p["id"], "approve").json()["status"] == "CAPTURE_FAILED"
    expire_now(env, p["id"])

    resp = env.act(p["id"], "retry")
    assert resp.status_code == 409
    assert env.get(p["id"])["status"] == "EXPIRED"
    assert env.paypal.captures == []


def test_a_decline_after_the_deadline_still_works(env):
    p = env.pay("high")
    expire_now(env, p["id"])
    done = env.act(p["id"], "decline", note="No").json()
    assert done["status"] == "VOIDED"
    assert env.paypal.captures == []


def test_approval_before_the_deadline_still_captures(env):
    p = env.pay("high")
    assert env.act(p["id"], "approve").json()["status"] == "CAPTURED"


def test_a_capture_already_claimed_before_the_deadline_is_not_cancelled_by_it(env):
    # approved in time, then the hold passes while PayPal is being called: the claim already won
    p = env.pay("high")
    env.paypal.inject("capture", lambda: expire_now(env, p["id"]))
    done = env.act(p["id"], "approve").json()
    assert done["status"] == "CAPTURED"
