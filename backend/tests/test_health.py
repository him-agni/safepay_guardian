from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


def _client(**overrides) -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, **overrides)
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_health_defaults_to_fake_paypal_and_rules_only():
    body = _client().get("/health").json()
    assert body["status"] == "ok"
    assert body["paypal"] == {"mode": "fake", "configured": True}
    assert body["ai"]["mode"] == "rules_only"


def test_health_sandbox_without_credentials_is_not_configured():
    body = _client(paypal_mode="sandbox").get("/health").json()
    assert body["paypal"]["configured"] is False


def test_health_never_leaks_secrets():
    text = _client(
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
