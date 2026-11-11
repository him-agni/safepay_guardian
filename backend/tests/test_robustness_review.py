"""Small hardening items from the second review: a checked sandbox address, sane settings, a proper 413 for a
streamed body, and a reset that never strands a sandbox authorization."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import demo
from app.config import Settings
from app.main import MAX_BODY_BYTES, create_app
from app.paypal import FakePayPal, GatewayError

from .conftest import make_settings


# ---------------------------------------------------------------- the PayPal address is checked


def sandbox(**kw) -> Settings:
    return Settings(_env_file=None, paypal_mode="sandbox", **kw)


def test_the_default_sandbox_address_is_accepted():
    s = sandbox()
    assert s.sandbox_only and s.sandbox_host_ok


@pytest.mark.parametrize("url", [
    "https://api-m.paypal.com",                              # the live PayPal
    "https://api.paypal.com",
    "http://api-m.sandbox.paypal.com",                       # not encrypted
    "https://api-m.sandbox.paypal.com.evil.example",         # looks like it, is not
    "https://api-m.sandbox.paypal.com@evil.example",         # the real host is after the @
    "https://evil.example/api-m.sandbox.paypal.com",
    "",
])
def test_sandbox_mode_refuses_any_other_paypal_address(url):
    with pytest.raises(ValidationError, match="only moves test money"):
        sandbox(paypal_base_url=url)


def test_fake_mode_does_not_need_a_paypal_address_and_is_sandbox_only():
    s = Settings(_env_file=None, paypal_mode="fake", paypal_base_url="https://api-m.paypal.com")
    assert s.sandbox_only  # no PayPal is ever contacted


def test_health_reports_what_the_configuration_really_is(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), gateway=FakePayPal())) as client:
        assert client.get("/health").json()["sandbox_only"] is True


# ---------------------------------------------------------------- settings that cannot work are refused


@pytest.mark.parametrize("name, value", [
    ("hold_timeout_seconds", 0),
    ("ai_timeout_seconds", 0),
    ("ai_timeout_seconds", -1),
    ("stuck_after_seconds", 0),
    ("auth_give_up_seconds", 0),
    ("max_screenshot_bytes", 0),
    ("rate_limit_payments", -1),
    ("sweeper_interval_seconds", -5),
])
def test_impossible_numbers_are_refused(name, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{name: value})


def test_zero_still_turns_off_what_is_meant_to_be_switchable():
    s = Settings(_env_file=None, sweeper_interval_seconds=0, rate_limit_payments=0, void_retry_seconds=0)
    assert s.sweeper_interval_seconds == 0 and s.rate_limit_payments == 0


# ---------------------------------------------------------------- a streamed body over the limit is a 413


def test_an_oversized_body_without_a_content_length_gets_a_413_not_a_crash(tmp_path):
    def chunks():
        for _ in range(MAX_BODY_BYTES // 1_000_000 + 2):
            yield b"x" * 1_000_000

    with TestClient(create_app(make_settings(tmp_path), gateway=FakePayPal())) as client:
        resp = client.post("/payments", content=chunks(), headers={"content-type": "application/json"})
        assert resp.status_code == 413
        assert resp.json()["error"] == "too_large"
        assert client.get("/health").status_code == 200  # and the server carries on


# ---------------------------------------------------------------- reset never strands an authorization


def test_reset_stops_before_deleting_when_an_authorization_could_not_be_voided(env):
    held = env.pay("high")
    env.paypal.inject("get", GatewayError("network", "read authorization failed: ReadTimeout"))

    with pytest.raises(demo.ResetBlocked) as blocked:
        demo.reset_safely(env.service.db_path, env.paypal)

    assert held["paypal"]["authorization_id"] in blocked.value.failures[0]
    assert env.get(held["id"])["status"] == "HELD"  # the record that lets us find it again is still there


def test_reset_voids_then_clears_when_everything_works(env):
    held = env.pay("high")
    result = demo.reset_safely(env.service.db_path, env.paypal)
    assert result["failed"] == [] and len(result["voided"]) == 1
    assert env.paypal.authorizations[held["paypal"]["authorization_id"]] == "VOIDED"
    assert env.client.get("/payments").json()["payments"][0]["is_seed"] is True


def test_force_deletes_even_when_a_void_failed(env):
    env.pay("high")
    env.paypal.inject("get", GatewayError("network", "read authorization failed: ReadTimeout"))
    result = demo.reset_safely(env.service.db_path, env.paypal, force=True)
    assert len(result["failed"]) == 1
    assert all(p["is_seed"] for p in env.client.get("/payments").json()["payments"])
