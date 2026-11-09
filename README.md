# SafePay Guardian

> **Sandbox only: all money is PayPal sandbox test money.**

SafePay Guardian holds a risky payment before it is captured, shows the sender and a trusted guardian exactly why it looks risky, and lets the guardian approve it or void it. It runs on PayPal's authorize, capture and void flow, with a hybrid risk engine (rules plus AI reading the message) deciding what needs a human.

Status: work in progress for the PayPal hackathon (deadline Nov 12, 2026).

## Run the backend (current state)

Requires Python 3.10 or newer.

Windows (Git Bash):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt
cp .env.example .env          # optional: works with no values set
cd backend
../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cp .env.example .env
cd backend
../.venv/bin/python -m uvicorn app.main:create_app --factory --port 8000
```

Then open http://localhost:8000/health.

With no `.env` values the app uses a fake in-process PayPal and the rules-only risk engine, so it runs without any credentials.

Run the tests:

```bash
cd backend
../.venv/Scripts/python -m pytest -q     # or ../.venv/bin/python on macOS/Linux
```

### Sandbox checks

With PayPal sandbox values in `.env` (`PAYPAL_MODE=sandbox`):

```bash
.venv/Scripts/python scripts/sandbox_gate.py   # raw PayPal calls: create, authorize, capture, void
```

End-to-end through the API (start the backend with a short hold so the timeout path runs too):

```bash
cd backend
HOLD_TIMEOUT_SECONDS=20 SWEEPER_INTERVAL_SECONDS=2 DATABASE_PATH=data/smoke.db \
  ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000
# in a second terminal, from the repo root:
.venv/Scripts/python scripts/api_smoke.py
```

The smoke script runs every lane (auto-capture, warn then confirm, hold then approve, hold then decline, sender cancel, hold timeout) and then reads each authorization back from PayPal to confirm it really is captured or voided.

## API

| Method and path | What it does |
|---|---|
| `POST /payments` | Create a payment, run the risk engine, authorize on PayPal, then capture, warn or hold |
| `GET /payments` | List payments (`?status=HELD,WARNED`, `?queue=guardian`) |
| `GET /payments/{id}` | One payment with risk assessment, audit events and messages |
| `POST /payments/{id}/confirm` | Sender confirms a medium-risk warning (captures) |
| `POST /payments/{id}/cancel` | Sender cancels a warned or held payment (voids) |
| `POST /payments/{id}/approve` | Guardian approves a held payment (captures, idempotent) |
| `POST /payments/{id}/decline` | Guardian declines a held payment (voids, idempotent) |
| `POST /payments/{id}/retry` | Guardian retries a failed capture or void |
| `POST /payments/{id}/messages` | Add a sender or guardian message |
| `GET /health` | PayPal and AI configuration and reachability |

## Payment safety

- Every payment uses PayPal `AUTHORIZE` intent, so nothing is captured until the app, the sender or the guardian decides.
- A decision first claims the payment inside one SQLite write transaction (`CAPTURING` or `VOIDING`), so two decisions cannot both act. A repeated decision returns the first result; an opposite one gets a clear 409.
- The authorization is read from PayPal before every capture and void.
- `PayPal-Request-Id` is `{payment_id}-{action}-{attempt}`: network retries reuse it, so a lost response can never cause a second capture.
- Held and warned payments are voided when the hold times out (24 hours by default). Silence never captures.
- Unfinished payments are resumed at startup, and every state change and PayPal call is written to the audit log.

## Honest limits

- All money is PayPal sandbox test money. In the sandbox every payment settles to one sandbox merchant account; the payee name is a label.
- The risk level is a decision aid, not a validated fraud probability.
- There is no real login: a toggle switches between the sender and guardian views.
- This is a demo of a protection workflow, not a certified fraud-prevention product.

## License

MIT, see [LICENSE](LICENSE).
