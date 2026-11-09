"""Sandbox gate test: proves the PayPal calls SafePay Guardian depends on.

Runs two real sandbox flows with a $1.00 order paid by the sandbox test card:
  1. create order (AUTHORIZE) -> authorization -> read status -> capture
  2. create order (AUTHORIZE) -> authorization -> void -> read status

Usage (from the repo root):
  .venv/Scripts/python scripts/sandbox_gate.py     # Windows
  .venv/bin/python scripts/sandbox_gate.py         # macOS / Linux

Reads credentials from .env. Never prints the token or card details.
"""

import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import get_settings  # noqa: E402

S = get_settings()
RUN = uuid.uuid4().hex[:8]


def fail(msg: str, resp: httpx.Response | None = None) -> None:
    print(f"FAIL: {msg}")
    if resp is not None:
        print(f"  HTTP {resp.status_code}, paypal-debug-id={resp.headers.get('paypal-debug-id')}")
        try:
            body = resp.json()
            print(f"  name={body.get('name')} message={body.get('message')}")
            for d in body.get("details", []):
                print(f"  detail: {d.get('issue')} - {d.get('description')}")
        except ValueError:
            print(f"  body: {resp.text[:300]}")
    sys.exit(1)


def get_token(client: httpx.Client) -> str:
    resp = client.post(
        "/v1/oauth2/token",
        auth=(S.paypal_client_id, S.paypal_client_secret.get_secret_value()),
        data={"grant_type": "client_credentials"},
    )
    if resp.status_code != 200:
        fail("could not get an OAuth token (check PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET)", resp)
    print("ok   token")
    return resp.json()["access_token"]


def create_authorized_order(client: httpx.Client, headers: dict, label: str) -> str:
    card = {
        "number": S.sandbox_card_number.get_secret_value(),
        "expiry": S.sandbox_card_expiry,
        "security_code": S.sandbox_card_security_code.get_secret_value(),
    }
    if S.sandbox_card_name:
        card["name"] = S.sandbox_card_name
    body = {
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "reference_id": f"gate-{RUN}-{label}",
                "description": "SafePay Guardian sandbox gate test",
                "amount": {"currency_code": "USD", "value": "1.00"},
            }
        ],
        "payment_source": {"card": card},
    }
    resp = client.post(
        "/v2/checkout/orders",
        json=body,
        headers={**headers, "PayPal-Request-Id": f"gate-{RUN}-{label}-create", "Prefer": "return=representation"},
    )
    if resp.status_code not in (200, 201):
        fail(f"[{label}] create order", resp)
    order = resp.json()
    print(f"ok   [{label}] order {order['id']} status={order.get('status')}")

    auths = order.get("purchase_units", [{}])[0].get("payments", {}).get("authorizations", [])
    if not auths:
        resp = client.post(
            f"/v2/checkout/orders/{order['id']}/authorize",
            json={},
            headers={**headers, "PayPal-Request-Id": f"gate-{RUN}-{label}-authorize", "Prefer": "return=representation"},
        )
        if resp.status_code not in (200, 201):
            fail(f"[{label}] authorize order", resp)
        auths = resp.json()["purchase_units"][0]["payments"]["authorizations"]
    auth = auths[0]
    print(f"ok   [{label}] authorization {auth['id']} status={auth.get('status')}")
    if auth.get("status") not in ("CREATED", "PENDING"):
        fail(f"[{label}] unexpected authorization status {auth.get('status')}")
    return auth["id"]


def auth_status(client: httpx.Client, headers: dict, auth_id: str) -> str:
    resp = client.get(f"/v2/payments/authorizations/{auth_id}", headers=headers)
    if resp.status_code != 200:
        fail(f"read authorization {auth_id}", resp)
    return resp.json()["status"]


def main() -> None:
    if S.paypal_mode != "sandbox" or not S.paypal_configured:
        fail("set PAYPAL_MODE=sandbox and the PayPal + card values in .env")

    with httpx.Client(base_url=S.paypal_base_url, timeout=30) as client:
        headers = {"Authorization": f"Bearer {get_token(client)}", "Content-Type": "application/json"}

        # Flow 1: hold then capture
        auth_id = create_authorized_order(client, headers, "capture")
        print(f"ok   [capture] status before capture = {auth_status(client, headers, auth_id)}")
        resp = client.post(
            f"/v2/payments/authorizations/{auth_id}/capture",
            json={},
            headers={**headers, "PayPal-Request-Id": f"gate-{RUN}-capture-capture", "Prefer": "return=representation"},
        )
        if resp.status_code not in (200, 201):
            fail("[capture] capture authorization", resp)
        print(f"ok   [capture] capture {resp.json()['id']} status={resp.json()['status']}")
        print(f"ok   [capture] authorization status now = {auth_status(client, headers, auth_id)}")

        # Flow 2: hold then void
        auth_id = create_authorized_order(client, headers, "void")
        resp = client.post(
            f"/v2/payments/authorizations/{auth_id}/void",
            headers={**headers, "PayPal-Request-Id": f"gate-{RUN}-void-void"},
        )
        if resp.status_code not in (200, 204):
            fail("[void] void authorization", resp)
        status = auth_status(client, headers, auth_id)
        print(f"ok   [void] authorization status now = {status}")
        if status != "VOIDED":
            fail(f"[void] expected VOIDED, got {status}")

    print("\nGATE PASSED: create, authorize, read, capture and void all work in this sandbox.")


if __name__ == "__main__":
    main()
