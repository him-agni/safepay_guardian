"""The real PayPal client, against a mocked HTTP transport (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.paypal import GatewayError, PayPalClient

from .conftest import make_settings

CARD = "fake-card-number-for-test"


def make_client(tmp_path, handler):
    settings = make_settings(
        tmp_path, paypal_mode="sandbox", paypal_client_id="cid", paypal_client_secret="secret",
        sandbox_card_number=CARD, sandbox_card_expiry="01/2030", sandbox_card_security_code="123",
    )
    return PayPalClient(settings, transport=httpx.MockTransport(handler))


def token_response():
    return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 32400})


def order_response(auth_status="CREATED"):
    return httpx.Response(201, headers={"paypal-debug-id": "dbg-1"}, json={
        "id": "ORDER1", "status": "COMPLETED",
        "purchase_units": [{"payments": {"authorizations": [{"id": "AUTH1", "status": auth_status}]}}],
    })


def test_create_order_sends_authorize_intent_card_and_request_id(tmp_path):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return token_response() if req.url.path == "/v1/oauth2/token" else order_response()

    order = make_client(tmp_path, handler).create_authorized_order(
        payment_id="p1", amount_cents=50000, currency="USD", description="test")
    assert (order.order_id, order.authorization_id, order.debug_id) == ("ORDER1", "AUTH1", "dbg-1")

    create = seen[1]
    body = json.loads(create.content)
    assert body["intent"] == "AUTHORIZE"
    assert body["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "500.00"}
    assert body["payment_source"]["card"]["expiry"] == "2030-01"
    assert "name" not in body["payment_source"]["card"]
    assert create.headers["PayPal-Request-Id"] == "p1-create"
    assert create.headers["Authorization"] == "Bearer tok-1"


def test_token_is_cached_between_calls(tmp_path):
    token_calls = []

    def handler(req):
        if req.url.path == "/v1/oauth2/token":
            token_calls.append(1)
            return token_response()
        return httpx.Response(200, json={"status": "CREATED"})

    client = make_client(tmp_path, handler)
    client.get_authorization("AUTH1")
    client.get_authorization("AUTH1")
    assert len(token_calls) == 1


def test_expired_token_is_refreshed_once_on_401(tmp_path):
    calls = {"token": 0, "get": 0}

    def handler(req):
        if req.url.path == "/v1/oauth2/token":
            calls["token"] += 1
            return token_response()
        calls["get"] += 1
        return httpx.Response(401) if calls["get"] == 1 else httpx.Response(200, json={"status": "VOIDED"})

    assert make_client(tmp_path, handler).get_authorization("AUTH1").status == "VOIDED"
    assert calls == {"token": 2, "get": 2}


def test_denied_authorization_raises_and_never_leaks_the_card(tmp_path):
    def handler(req):
        return token_response() if req.url.path == "/v1/oauth2/token" else order_response("DENIED")

    with pytest.raises(GatewayError) as err:
        make_client(tmp_path, handler).create_authorized_order(
            payment_id="p1", amount_cents=100, currency="USD", description="x")
    assert err.value.kind == "client"
    assert err.value.issue == "AUTHORIZATION_DENIED"
    assert CARD not in str(err.value.as_detail())


def test_error_mapping_client_server_and_network(tmp_path):
    def unprocessable(req):
        if req.url.path == "/v1/oauth2/token":
            return token_response()
        return httpx.Response(422, headers={"paypal-debug-id": "dbg-9"}, json={
            "name": "UNPROCESSABLE_ENTITY", "message": "The requested action could not be performed.",
            "details": [{"issue": "AUTHORIZATION_VOIDED", "description": "Authorization was voided."}]})

    with pytest.raises(GatewayError) as err:
        make_client(tmp_path, unprocessable).capture("AUTH1", request_id="p1-capture-1")
    assert (err.value.kind, err.value.issue, err.value.debug_id) == ("client", "AUTHORIZATION_VOIDED", "dbg-9")
    assert not err.value.retry_same_id

    def server_error(req):
        return token_response() if req.url.path == "/v1/oauth2/token" else httpx.Response(503)

    with pytest.raises(GatewayError) as err:
        make_client(tmp_path, server_error).capture("AUTH1", request_id="p1-capture-1")
    assert err.value.kind == "server" and err.value.retry_same_id

    def timeout(req):
        if req.url.path == "/v1/oauth2/token":
            return token_response()
        raise httpx.ReadTimeout("timed out", request=req)

    with pytest.raises(GatewayError) as err:
        make_client(tmp_path, timeout).void("AUTH1", request_id="p1-void-1")
    assert err.value.kind == "network" and err.value.retry_same_id


def test_check_reports_bad_credentials_as_unreachable(tmp_path):
    def handler(req):
        return httpx.Response(401, json={"error": "invalid_client"})

    assert make_client(tmp_path, handler).check() is False
