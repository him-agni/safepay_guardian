"""What happens to a payment rules call Low when the AI check did not run.

Rules alone caught about half the held-out scams, so "rules say Low" is weaker evidence during an AI outage.
The payment is sent to the sender for a double-check if the payee is new or the amount is far above usual;
everyday payments to people the sender has paid before still go straight through.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.paypal import FakePayPal

from .conftest import Env, FixedAssessor, make_settings


class OutageAssessor(FixedAssessor):
    """Like the fixed assessor, but can report that the AI check did not run."""

    outage = True

    def assess(self, ctx):
        result = super().assess(ctx)
        if self.outage:
            result.ai_error = "AI check failed: timeout"
        return result


def make_env(tmp_path, **settings) -> Env:
    paypal, risk = FakePayPal(), OutageAssessor("low")
    app = create_app(make_settings(tmp_path, **settings), gateway=paypal, assessor=risk)
    client = TestClient(app)
    client.__enter__()
    return Env(client, app.state.service, paypal, risk)


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    yield e
    e.client.__exit__(None, None, None)


def build_history(env, payee="Grandson Leo", times=3, amount="35.00"):
    env.risk.outage = False  # the AI worked for these
    for _ in range(times):
        assert env.pay("low", amount, payee)["status"] == "CAPTURED"
    env.risk.outage = True


def test_a_new_payee_during_an_outage_needs_the_senders_ok(env):
    p = env.pay("low", "40.00", "Gutter Pros")

    assert p["status"] == "WARNED"
    assert p["can"]["confirm"] and p["can"]["cancel"]
    assert "AI check was not available" in p["route_note"]
    assert "not paid this person before" in p["route_note"]
    assert env.paypal.captures == []
    assert "hold.warned" in env.event_types(p["id"])

    done = env.act(p["id"], "confirm").json()
    assert done["status"] == "CAPTURED"  # the sender can still go ahead


def test_a_payee_the_sender_has_paid_before_still_goes_straight_through(env):
    build_history(env)
    p = env.pay("low", "35.00", "Grandson Leo")
    assert p["status"] == "CAPTURED"
    assert p["route_note"] is None


def test_a_much_larger_than_usual_amount_needs_the_senders_ok_even_for_a_known_payee(env):
    build_history(env)
    p = env.pay("low", "500.00", "Grandson Leo")
    assert p["status"] == "WARNED"
    assert "much larger than your usual payment" in p["route_note"]
    assert "not paid this person before" not in p["route_note"]


def test_both_reasons_are_given_when_both_apply(env):
    build_history(env)
    p = env.pay("low", "500.00", "Gutter Pros")
    assert "not paid this person before and the amount is much larger" in p["route_note"]


def test_a_trusted_payee_with_a_typical_amount_is_not_slowed_down(env):
    env.service._build_context("Grandson Leo", 3500, "", "", create_payee=True)
    with env.service._conn() as conn:
        conn.execute("UPDATE payees SET trusted = 1 WHERE name_key = 'grandson leo'")
        conn.commit()
    assert env.pay("low", "35.00", "Grandson Leo")["status"] == "CAPTURED"


def test_when_the_ai_worked_a_new_payee_with_low_risk_goes_through_as_before(env):
    env.risk.outage = False
    p = env.pay("low", "40.00", "Gutter Pros")
    assert p["status"] == "CAPTURED"
    assert p["route_note"] is None


def test_medium_and_high_are_unchanged_by_the_outage_rule(env):
    assert env.pay("medium")["status"] == "WARNED"
    assert env.pay("high")["status"] == "HELD"


def test_an_unconfirmed_double_check_times_out_like_any_warning(env):
    from datetime import timedelta

    from app import db

    p = env.pay("low", "40.00", "Gutter Pros")
    env.service.sweep(now=db.utcnow() + timedelta(seconds=env.service.settings.hold_timeout_seconds + 5))
    assert env.get(p["id"])["status"] == "EXPIRED"
    assert env.paypal.captures == []


def test_the_rule_can_be_switched_off(tmp_path):
    e = make_env(tmp_path, confirm_when_ai_unavailable=False)
    try:
        assert e.pay("low", "40.00", "Gutter Pros")["status"] == "CAPTURED"
    finally:
        e.client.__exit__(None, None, None)
