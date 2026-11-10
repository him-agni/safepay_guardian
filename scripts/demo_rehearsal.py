"""Rehearse the three demo scenarios through the running app, and check every result on PayPal.

Each run: reset the demo database (voiding open authorizations), then play scenarios 1, 2, 3 in order
through the same API calls the screens make, checking the risk level, the status after each step, that the
AI ran, and finally that PayPal's own record of every authorization matches ours.

Run the backend with the demo AI cache so the replies are stored for the recording:
  cd backend && AI_CACHE_DIR=demo/ai-cache DATABASE_PATH=data/demo.db \
    ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000
then, from the repo root with the same DATABASE_PATH:
  DATABASE_PATH=data/demo.db .venv/Scripts/python scripts/demo_rehearsal.py --runs 3 --standalone 3

--standalone 3 also plays scenario 3 alone after a reset, so its AI reply is cached for a re-take too
(scenario 2 adds a payment to the history, which changes scenario 3's prompt).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import demo  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.paypal import PayPalClient, build_gateway  # noqa: E402

SCENARIOS = json.loads((ROOT / "demo" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
failures: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("   ok   " if cond else "   FAIL ") + label)
    if not cond:
        failures.append(label)


def reset(settings) -> None:
    if settings.paypal_mode == "sandbox":
        demo.void_open_authorizations(settings.database_file, build_gateway(settings))
    demo.reset(settings.database_file)


def play(api: httpx.Client, sc: dict) -> dict:
    print(f" {sc['id']}: {sc['title']}")
    started = time.monotonic()
    message, screenshot_id = sc["message"], None
    if sc.get("screenshot"):
        image = (ROOT / sc["screenshot"]).read_bytes()
        shot = api.post("/screenshots", json={"image_base64": base64.b64encode(image).decode(),
                                              "mime_type": "image/png"}).json()
        src = "stored reply" if shot.get("cached") else f"{shot.get('latency_ms')} ms"
        check(shot["read"], f"screenshot read: {shot['messages_found']} received message(s) from "
                            f"{shot['sender'] or '?'}, {shot['own_messages_skipped']} own reply skipped ({src})"
                            + ("" if shot["read"] else f": {shot['error']}"))
        screenshot_id = shot["screenshot_id"]
        if shot["read"]:
            message = shot["text"]
    p = api.post("/payments", json={"payee_name": sc["payee"], "amount": sc["amount"], "note": sc["note"],
                                    "message_text": message, "screenshot_id": screenshot_id}).json()
    risk = p["risk"]
    src = "stored reply" if risk["components"].get("ai_cached") else f"{risk['latency_ms']} ms"
    check(p["status"] == sc["expect"]["status"] and risk["level"] == sc["expect"]["level"],
          f"{p['status']} / {risk['level']} (expected {sc['expect']['status']} / {sc['expect']['level']}), "
          f"{time.monotonic() - started:.1f}s")
    check(risk["mode"] == "hybrid", f"AI ran ({risk['mode']}, {src}){'' if risk['mode'] == 'hybrid' else ': ' + str(risk['ai_error'])}")
    for step in sc["steps"]:
        if step["action"] == "message":
            p = api.post(f"/payments/{p['id']}/messages", json={"from_role": step["who"], "body": step["body"]}).json()
        else:
            body = {"note": step["note"]} if step.get("note") else {}
            p = api.post(f"/payments/{p['id']}/{step['action']}", json=body).json()
    check(p["status"] == sc["final"], f"after {', '.join(s['who'] + ' ' + s['action'] for s in sc['steps'])}: "
                                      f"{p['status']} (expected {sc['final']})")
    return p


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--standalone", type=int, action="append", default=[],
                        help="also play this scenario number alone after a reset (repeatable)")
    args = parser.parse_args()
    settings = get_settings()

    with httpx.Client(base_url=args.base_url, timeout=90) as api:
        health = api.get("/health").json()
        print(f"backend: PayPal {health['paypal']['mode']}, AI {health['ai']['mode']} "
              f"({health['ai']['model']}), hold {health['hold_timeout_seconds']} s, database {settings.database_file}")
        played: list[dict] = []
        for run in range(1, args.runs + 1):
            print(f"\nRun {run}: reset, then scenarios 1-3 in order")
            reset(settings)
            played += [play(api, sc) for sc in SCENARIOS]
        for number in args.standalone:
            print(f"\nStandalone: reset, then scenario {number} alone")
            reset(settings)
            played.append(play(api, SCENARIOS[number - 1]))

    if settings.paypal_mode == "sandbox":
        print("\nPayPal cross-check")
        paypal = PayPalClient(settings)
        for p in played:
            got = paypal.get_authorization(p["paypal"]["authorization_id"]).status
            want = {"CAPTURED": "CAPTURED", "VOIDED": "VOIDED"}.get(p["status"], "?")
            check(got == want, f"{p['payee']['name']}: ours {p['status']}, PayPal {got}")

    print(f"\n{'REHEARSAL PASSED' if not failures else f'REHEARSAL FAILED: {len(failures)} check(s)'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
