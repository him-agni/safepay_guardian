from fastapi.testclient import TestClient

from app.main import create_app
from app.paypal import FakePayPal

from .conftest import make_settings


def _client(tmp_path, **overrides) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path, **overrides), gateway=FakePayPal()))


def test_health_defaults_to_fake_paypal_and_rules_only(tmp_path):
    body = _client(tmp_path).get("/health").json()
    assert body["status"] == "ok"
    assert body["paypal"] == {"mode": "fake", "configured": True, "reachable": True}
    assert body["ai"]["mode"] == "rules_only"


def test_health_sandbox_without_credentials_is_not_configured(tmp_path):
    body = _client(tmp_path, paypal_mode="sandbox").get("/health").json()
    assert body["paypal"]["configured"] is False


def test_health_never_leaks_secrets(tmp_path):
    text = _client(
        tmp_path,
        paypal_mode="sandbox",
        paypal_client_id="cid",
        paypal_client_secret="super-secret-value",
        sandbox_card_number="fake-card-number-for-test",
        sandbox_card_expiry="2030-01",
        ai_provider="gemini",
        gemini_api_key="gemini-secret-key",
    ).get("/health").text
    for secret in ("super-secret-value", "fake-card-number-for-test", "gemini-secret-key"):
        assert secret not in text
