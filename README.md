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

## Run the web app

Requires Node 20 or newer. Start the backend first (above), then in a second terminal:

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The Vite dev server forwards `/api` to the backend on port 8000, so the browser only ever talks to our backend, and the backend is the only thing that talks to PayPal and the AI. Use the "I am the sender / I am the guardian" switch in the header to change sides (there is no real login). Both screens refresh every 3 seconds.

Frontend checks: `npm test` (unit tests), `npm run build` (type-check and production build), `npx oxlint src` (lint).

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
| `POST /assess` | Run the risk engine on a message (and optional amount and payee) without creating a payment |
| `GET /health` | PayPal and AI configuration and reachability |

## Risk engine

The engine returns Low, Medium or High. The AI is never the sole decision-maker: rules set a floor, the AI adds context, and a human decides what is held.

1. **Rules** (`app/risk/rules.py`): gift or prepaid cards and crypto, wire or "safe account" requests are hard rules (High on their own). Urgency, secrecy, authority threats, a new payee, an unusual amount, a request to mark the payee as trusted, a "new phone number" story, and a new payee with no explanation add weights.
2. **AI** (`app/risk/ai.py`, Gemini 3.1 Flash-Lite): one call with a strict JSON schema returns a category, indicators with quoted evidence, confidence and a recommended action. The pasted message is treated as untrusted data inside a delimiter it cannot close, and instructions inside it are reported as manipulation.
3. **Evidence grounding**: every quote the AI returns must literally appear in the message, note, payee or amount (after normalising case, quotes, dashes and spaces). Anything else is dropped and logged, never shown.
4. **Aggregation** (`app/risk/engine.py`): final level = the highest of the hard-rule level, the level of the combined heuristic score, and the AI's floor (which needs at least one grounded indicator). The AI can raise a level but never lower one. A trusted payee only removes the "new payee" signal.
5. **Scam-pattern retrieval** (`app/risk/patterns.py`): 25 known scam scripts, written for this project, ranked with BM25 and shown as "similar known pattern". They inform the AI but add no weight.

If the AI is not configured, times out, hits a rate limit or returns invalid JSON, the engine runs on rules alone and the response says "AI check unavailable, rules only". Hard rules still hold dangerous payments. Every number lives in `app/risk/config.py`.

## Evaluation

`eval/cases.json` holds 16 labelled cases written for this project (4 legitimate, 6 scams, 3 ambiguous, 3 adversarial), each with the levels that are acceptable and the evidence that must be cited. The two that test judgment: L3, a $350 deposit to a new contractor (holding it would be annoying), and A1, "Hi it's Sam, new number" asking for a rent deposit (letting it through would be unsafe).

```bash
.venv/Scripts/python eval/run_eval.py --cached      # offline, from the committed AI replies (no key needed)
.venv/Scripts/python eval/run_eval.py               # live AI for anything not cached
.venv/Scripts/python eval/run_eval.py --repeat 3    # also measure run-to-run consistency
```

It prints the case table, the metrics (scam catch rate, false hold rate, level accuracy, JSON validity, evidence grounding, injection resistance, latency) and a rules-only vs AI-only vs hybrid comparison, and saves them to [eval/results.md](eval/results.md).

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
