"""A PayPal authorization that never got an answer is not a failure.

A timeout can mean PayPal authorized the payment and the reply was lost. Marking it failed would leave an
authorization nobody tracks. The payment stays CREATED and is retried with the same request id until a deadline.
"""

from __future__ import annotations

from datetime import timedelta

from app import db
from app.paypal import GatewayError


def later(seconds: int = 30):
    return db.utcnow() + timedelta(seconds=seconds)


def no_answer(env, times: int = 3, kind: str = "network") -> None:
    for _ in range(times):  # one create attempt is retried three times
        env.paypal.inject("create", GatewayError(kind, "create order failed: ReadTimeout"))


def age_payment(env, payment_id: str, seconds: int) -> None:
    past = db.iso(db.utcnow() - timedelta(seconds=seconds))
    with db.connect(env.service.db_path) as conn:
        conn.execute("UPDATE payments SET created_at = ? WHERE id = ?", (past, payment_id))
        conn.commit()


def test_no_answer_from_paypal_keeps_the_payment_open_instead_of_failing_it(env):
    no_answer(env)
    p = env.pay("low", payee="Grandson Leo")

    assert p["status"] == "CREATED"
    assert p["final"] is False
    assert "still trying" in p["text"]["sender"]
    assert "Nothing has been sent" in p["text"]["sender"]
    assert "paypal.authorization_uncertain" in env.event_types(p["id"])
    assert "paypal.authorization_failed" not in env.event_types(p["id"])
    assert env.paypal.captures == []


def test_a_server_error_is_treated_the_same_way(env):
    no_answer(env, kind="server")
    p = env.pay("low", payee="Grandson Leo")
    assert p["status"] == "CREATED"


def test_the_sweeper_retries_with_the_same_request_id_and_finishes_the_payment(env):
    no_answer(env)
    p = env.pay("low", payee="Grandson Leo")

    assert env.service.sweep(now=later(5))["authorization_retried"] == 0  # too soon
    assert env.service.sweep(now=later(30))["authorization_retried"] == 1

    done = env.get(p["id"])
    assert done["status"] == "CAPTURED"
    assert done["last_error"] is None
    create_ids = {rid for op, rid in env.paypal.calls if op == "create"}
    assert create_ids == {f"{p['id']}-create"}  # always the same id, so PayPal returns the same order
    assert len(env.paypal.authorizations) == 1


def test_a_held_payment_is_routed_once_after_a_late_authorization(env):
    no_answer(env)
    p = env.pay("high")
    env.service.sweep(now=later(30))
    assert env.get(p["id"])["status"] == "HELD"
    assert len(env.paypal.authorizations) == 1


def test_keeps_trying_while_paypal_stays_silent(env):
    no_answer(env)
    p = env.pay("low", payee="Grandson Leo")
    no_answer(env)  # the retry gets no answer either
    env.service.sweep(now=later(30))
    assert env.get(p["id"])["status"] == "CREATED"

    env.service.sweep(now=later(60))  # the third attempt works
    assert env.get(p["id"])["status"] == "CAPTURED"
    assert len(env.paypal.authorizations) == 1


def test_gives_up_only_after_the_deadline_and_says_what_that_means(env):
    no_answer(env)
    p = env.pay("low", payee="Grandson Leo")
    age_payment(env, p["id"], 600)  # older than auth_give_up_seconds
    no_answer(env)

    env.service.sweep(now=later(30))
    failed = env.get(p["id"])
    assert failed["status"] == "AUTH_FAILED"
    assert "expires by itself" in failed["last_error"]
    assert "paypal.authorization_gave_up" in env.event_types(p["id"])


def test_a_definite_refusal_still_fails_immediately(env):
    env.paypal.inject("create", GatewayError("client", "create order failed: HTTP 422 INSTRUMENT_DECLINED",
                                             status_code=422, issue="INSTRUMENT_DECLINED"))
    p = env.pay("low", payee="Grandson Leo")
    assert p["status"] == "AUTH_FAILED"
    assert "paypal.authorization_uncertain" not in env.event_types(p["id"])


def test_a_payment_still_being_authorized_cannot_be_decided(env):
    no_answer(env)
    p = env.pay("high")
    resp = env.act(p["id"], "approve")
    assert resp.status_code == 409
    assert "still being authorized" in resp.json()["message"]
