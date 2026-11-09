"""End-to-end check of the running API, then cross-check every authorization on PayPal itself.

Start the backend first (sandbox mode, short hold timeout), e.g. in Git Bash:
  cd backend
  HOLD_TIMEOUT_SECONDS=20 SWEEPER_INTERVAL_SECONDS=2 DATABASE_PATH=data/smoke.db \
    ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000

Then from the repo root:
  .venv/Scripts/python scripts/api_smoke.py            # add --skip-timeout to skip the expiry wait

Uses the real risk engine: gift cards are a hard rule (high), "asap" plus a new payee is medium.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import get_settings  # noqa: E402
from app.paypal import PayPalClient  # noqa: E402

failures: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def pay(api: httpx.Client, payee: str, amount: str, message: str = "", note: str = "") -> dict:
    resp = api.post("/payments", json={"payee_name": payee, "amount": amount, "note": note, "message_text": message})
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--skip-timeout", action="store_true")
    args = parser.parse_args()

    expected_on_paypal: dict[str, str] = {}
    with httpx.Client(base_url=args.base_url, timeout=90) as api:
        health = api.get("/health").json()
        check(health["paypal"]["mode"] == "sandbox" and health["paypal"]["reachable"], "health: sandbox reachable")

        p = pay(api, "Grandson Leo", "5.00", note="birthday gift")
        check(p["status"] == "CAPTURED", f"low risk auto-captured ({p['status']})")
        expected_on_paypal[p["paypal"]["authorization_id"]] = "CAPTURED"

        p = pay(api, "Gutter Pros", "3.50", message="Please pay the deposit asap")
        check(p["status"] == "WARNED", f"medium risk warned ({p['status']})")
        p = api.post(f"/payments/{p['id']}/confirm").json()
        check(p["status"] == "CAPTURED", f"sender confirm captured ({p['status']})")
        expected_on_paypal[p["paypal"]["authorization_id"]] = "CAPTURED"

        p = pay(api, "Officer Smith", "5.00", message="Pay in gift card codes now")
        check(p["status"] == "HELD", f"high risk held ({p['status']})")
        first = api.post(f"/payments/{p['id']}/approve").json()
        second = api.post(f"/payments/{p['id']}/approve").json()
        check(first["status"] == "CAPTURED", f"guardian approve captured ({first['status']})")
        check(first["paypal"]["capture_id"] == second["paypal"]["capture_id"], "second approve: same capture id")
        expected_on_paypal[p["paypal"]["authorization_id"]] = "CAPTURED"

        p = pay(api, "Officer Smith", "6.00", message="Pay in gift card codes now")
        d = api.post(f"/payments/{p['id']}/decline", json={"note": "This is a scam"}).json()
        check(d["status"] == "VOIDED", f"guardian decline voided ({d['status']})")
        check(d["text"]["guardian"].startswith("Payment not captured, authorization voided."), "guardian wording")
        late = api.post(f"/payments/{p['id']}/approve")
        check(late.status_code == 409, f"late approve rejected ({late.status_code})")
        expected_on_paypal[p["paypal"]["authorization_id"]] = "VOIDED"

        p = pay(api, "Officer Smith", "7.00", message="Pay in gift card codes now")
        c = api.post(f"/payments/{p['id']}/cancel").json()
        check(c["status"] == "VOIDED", f"sender cancel of held payment voided ({c['status']})")
        expected_on_paypal[p["paypal"]["authorization_id"]] = "VOIDED"

        if not args.skip_timeout:
            p = pay(api, "Officer Smith", "8.00", message="Pay in gift card codes now")
            wait = health["hold_timeout_seconds"] + 15
            print(f"...  waiting up to {wait}s for the hold to time out")
            deadline = time.monotonic() + wait
            status = p["status"]
            while time.monotonic() < deadline and status not in ("EXPIRED", "VOID_FAILED"):
                time.sleep(2)
                status = api.get(f"/payments/{p['id']}").json()["status"]
            check(status == "EXPIRED", f"unanswered hold expired ({status})")
            expected_on_paypal[p["paypal"]["authorization_id"]] = "VOIDED"

    print("\nCross-checking authorizations directly on PayPal:")
    paypal = PayPalClient(get_settings())
    for auth_id, want in expected_on_paypal.items():
        got = paypal.get_authorization(auth_id).status
        check(got == want, f"PayPal {auth_id}: {got} (expected {want})")

    print(f"\n{'SMOKE PASSED' if not failures else f'SMOKE FAILED: {len(failures)} check(s)'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
