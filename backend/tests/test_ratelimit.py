"""Per-visitor rate limits on the endpoints that create things or call the AI."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.paypal import FakePayPal
from app.ratelimit import RateLimiter, TooManyRequests

from .conftest import FixedAssessor, make_settings


def test_sliding_window_per_bucket_and_visitor():
    now = [1000.0]
    limiter = RateLimiter({"payments": 2, "messages": 0}, clock=lambda: now[0])
    limiter.check("payments", "a")
    limiter.check("payments", "a")
    with pytest.raises(TooManyRequests) as err:
        limiter.check("payments", "a")
    assert err.value.status_code == 429 and 1 <= err.value.retry_after <= 61
    limiter.check("payments", "b")  # another visitor has their own allowance
    for _ in range(100):
        limiter.check("messages", "a")  # 0 = no limit
    now[0] += 61
    limiter.check("payments", "a")  # the window has moved on


def _client(tmp_path, **limits):
    settings = make_settings(tmp_path, **limits)
    return TestClient(create_app(settings, gateway=FakePayPal(), assessor=FixedAssessor("low")))


def test_the_api_answers_429_with_a_plain_message_and_retry_after(tmp_path):
    with _client(tmp_path, rate_limit_payments=2) as client:
        body = {"payee_name": "Leo", "amount": "20.00"}
        assert client.post("/payments", json=body).status_code == 201
        assert client.post("/payments", json=body).status_code == 201
        resp = client.post("/payments", json=body)
        assert resp.status_code == 429
        assert resp.json()["error"] == "rate_limited" and "try again" in resp.json()["message"]
        assert int(resp.headers["retry-after"]) >= 1
        assert len(client.get("/payments").json()["payments"]) == 2  # nothing was created
        assert client.get("/stats").status_code == 200  # reading is never limited


def test_limited_endpoints_and_defaults(tmp_path):
    with _client(tmp_path, rate_limit_ai_checks=1, rate_limit_screenshots=1) as client:
        assert client.post("/assess", json={"message_text": "hi"}).status_code == 200
        assert client.post("/assess", json={"message_text": "hi"}).status_code == 429
        ask = {"question": "declined payments", "columns": [{"id": "status", "label": "Status", "type": "text"}]}
        assert client.post("/activity/ask", json=ask).status_code == 429  # shares the AI allowance
        shot = {"image_base64": "aGVsbG8gd29ybGQ=", "mime_type": "image/png"}
        assert client.post("/screenshots", json=shot).status_code == 422  # counted, then rejected as not a PNG
        assert client.post("/screenshots", json=shot).status_code == 429
    defaults = make_settings(tmp_path)
    assert (defaults.rate_limit_payments, defaults.rate_limit_screenshots, defaults.rate_limit_ai_checks,
            defaults.rate_limit_messages) == (20, 10, 20, 30)
