# SafePay Guardian

> **Sandbox only: all money is PayPal sandbox test money.**

SafePay Guardian holds a risky payment before it is captured, shows the sender and a trusted guardian exactly why it looks risky, and lets the guardian approve it or void it. It runs on PayPal's authorize, capture and void flow, with a hybrid risk engine (rules plus AI reading the message) deciding what needs a human.

Status: work in progress for the PayPal hackathon (deadline Nov 12, 2026).

## Try it without any keys

The fake PayPal and the stored AI replies for the three demo messages need no credentials:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt     # .venv/bin/python on macOS/Linux
cd backend
PAYPAL_MODE=fake AI_PROVIDER=replay AI_CACHE_DIR=demo/ai-cache DATABASE_PATH=data/judge.db   ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000
# second terminal, repo root: seed the demo history, then start the web app
PAYPAL_MODE=fake DATABASE_PATH=data/judge.db .venv/Scripts/python scripts/reset_demo.py
cd frontend && npm install && npm run dev                            # http://localhost:5173
```

Then follow the three scenarios in [demo/README.md](demo/README.md). Messages other than the demo ones are checked by the rules alone, and the screen says so.

## Run the backend

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

Two sides, one app, in light and dark mode (it follows the device setting; the moon/sun button in the header switches and remembers it):

- **Home** (`#/`): who it is for, how to use it from the sender's and the guardian's side, how it works (PayPal authorization, rules and AI, one risk level, a person decides), why to trust it (fail-safe design and the held-out test results) and common questions.
- **Sender** (large text, plain words): send money with an optional pasted message or a **screenshot of the conversation** (the AI copies the received messages word for word, leaves out the sender's own replies, and the sender checks the text before sending); see "Payment completed", a warning to confirm or cancel, or "This payment is on hold" with the reasons, the suspicious words highlighted and a **"While you wait: staying safe"** box (one tip for the kind of scam detected, then general advice such as "nobody real asks for gift cards, crypto or a wire transfer"); reply to the guardian.
- **Guardian**: a queue of held payments; a review screen with the risk level, quoted evidence (rule or AI), the matched scam pattern, payee history, the hold timer, Approve / Decline with a note, Retry after a PayPal failure, "Ask the payer", and the full audit log of every PayPal call; an **Activity** case log built with AG Grid (**"Ask about your activity"**: a plain-English question such as "high-risk payments that I declined" becomes validated grid filters shown as removable chips, read-only; live rows whose status cells flash when a decision lands, preset views such as "Needs a decision" and "Flagged by AI", evidence tooltips, top quoted evidence, who checked it, a void countdown, column and date filters, a pinned totals row for the current view, a CSV report for a bank or police report, and a remembered layout; decisions stay on the review page); and **Insights** with stat tiles and three AG Charts Community charts (payments over time by outcome, top scam categories, recipients flagged most often), each with a "Show as a table" view.

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
| `GET /stats` | Counts and totals for the guardian's Insights (attempted payments held from capture, declines, approvals, top scam categories, recipients flagged most often, and the last 30 days of payments by outcome) |
| `POST /screenshots` | Save a screenshot of the conversation (PNG, JPEG or WebP, up to 4 MB) and transcribe it for the sender to confirm |
| `GET /screenshots/{id}` | The saved screenshot, for both screens |
| `POST /activity/ask` | Turn a guardian's plain-English question into grid filters. The AI proposes, a validator keeps only known columns, operators and values; read-only |
| `POST /assess` | Run the risk engine on a message (and optional amount and payee) without creating a payment |
| `GET /health` | PayPal and AI configuration and reachability |

## Risk engine

The engine returns Low, Medium or High. The AI is never the sole decision-maker: rules set a floor, the AI adds context, and a human decides what is held.

1. **Rules** (`app/risk/rules.py`): gift or prepaid cards and crypto, wire or "safe account" requests are hard rules (High on their own). Urgency, secrecy, authority threats, a new payee, an unusual amount, a request to mark the payee as trusted, a "new phone number" story, and a new payee with no explanation add weights.
2. **AI** (`app/risk/ai.py`, Gemini 3.1 Flash-Lite): one call with a strict JSON schema returns a category, indicators with quoted evidence, confidence and a recommended action. The pasted message is treated as untrusted data inside a delimiter it cannot close, and instructions inside it are reported as manipulation.
3. **Evidence grounding**: every quote the AI returns must literally appear in the message, note, payee or amount (after normalising case, quotes, dashes and spaces). Anything else is dropped and logged, never shown.
4. **Aggregation** (`app/risk/engine.py`): final level = the highest of the hard-rule level, the level of the combined heuristic score, and the AI's floor (which needs at least one grounded indicator). The AI can raise a level but never lower one. A trusted payee only removes the "new payee" signal.
5. **Scam-pattern retrieval** (`app/risk/patterns.py`): 25 known scam scripts, written for this project, ranked with BM25 and shown as "similar known pattern". They inform the AI but add no weight.

**Screenshots** (`transcribe_screenshot` in `app/risk/ai.py`): Gemini reads the image and returns each message with who wrote it; only the received messages go to the risk check, after the sender confirms them, so the evidence is grounded in text the sender has seen. The screenshot itself is shown to the guardian next to the text. Instructions written inside the image are transcribed, never followed.

If the AI is not configured, times out (12 s), hits a rate limit or returns invalid JSON, the engine runs on rules alone and the response says "AI check unavailable, rules only". Hard rules still hold dangerous payments. Every number lives in `app/risk/config.py`.

## Evaluation

`eval/cases.json` holds 16 labelled cases written for this project (4 legitimate, 6 scams, 3 ambiguous, 3 adversarial), each with the levels that are acceptable and the evidence that must be cited. The two that test judgment: L3, a $350 deposit to a new contractor (holding it would be annoying), and A1, "Hi it's Sam, new number" asking for a rent deposit (letting it through would be unsafe).

```bash
.venv/Scripts/python eval/run_eval.py --cached      # offline, from the committed AI replies (no key needed)
.venv/Scripts/python eval/run_eval.py               # live AI for anything not cached
.venv/Scripts/python eval/run_eval.py --repeat 3    # also measure run-to-run consistency
```

It prints the case table, the metrics (scam catch rate, false hold rate, level accuracy, JSON validity, evidence grounding, injection resistance, latency) and a rules-only vs AI-only vs hybrid comparison, and saves them to [eval/results.md](eval/results.md).

### Held-out test set

The 16 cases above were used to tune the engine once before it was frozen, so they flatter it. [eval/heldout_cases.json](eval/heldout_cases.json) has **69 cases written after the freeze and never used for tuning**: 30 scams written from scam patterns published by the FTC and the FBI (each case cites its source page), 14 everyday legitimate payments, 6 ambiguous cases, 8 adversarial cases (disguised words, a scam in Spanish, lookalike letters, attempts to instruct the AI), and 11 real text messages from a public research dataset (8 scams, 3 legitimate). Results are reported as they came out ([eval/results_heldout.md](eval/results_heldout.md)):

| | Rules only | AI only | Hybrid |
|---|---|---|---|
| Scams held (High) | 22/46 (48%) | 44/46 (96%) | **44/46 (96%)** |
| Scams at least warned | 36/46 (78%) | 46/46 (100%) | **46/46 (100%)** |
| Legitimate payments held | 0 of 17 | 0 of 17 | **0 of 17** |
| Level accuracy | 47/69 (68%) | 67/69 (97%) | **68/69 (99%)** |

The one hybrid miss: a trusted grandson asking for $300 for concert tickets "on sale in an hour" was held for the guardian, where a warning was expected (over-cautious, not unsafe). The AI alone let a $400 payment to a stranger with no explanation through as Low; the rules kept it at Medium. JSON was valid for 69/69 replies and no quote was dropped. It is still a self-written set plus a handful of real messages, not a measured real-world fraud rate.

```bash
.venv/Scripts/python eval/run_eval.py --cases eval/heldout_cases.json --out results_heldout --cached
```

Real messages: Mishra, S. & Soni, D. (2022). *SMS Phishing Dataset for Machine Learning and Pattern Recognition*. Mendeley Data, v1. [doi:10.17632/f45bkkt8pr.1](https://doi.org/10.17632/f45bkkt8pr.1), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Copied verbatim except for repairing encoding damage (a lost pound sign or space, HTML entities).

## Payment safety

- Every payment uses PayPal `AUTHORIZE` intent, so nothing is captured until the app, the sender or the guardian decides.
- A decision first claims the payment inside one SQLite write transaction (`CAPTURING` or `VOIDING`), so two decisions cannot both act. A repeated decision returns the first result; an opposite one gets a clear 409.
- The authorization is read from PayPal before every capture and void.
- `PayPal-Request-Id` is `{payment_id}-{action}-{attempt}`: network retries reuse it, so a lost response can never cause a second capture.
- Held and warned payments are voided when the hold times out (24 hours by default). Silence never captures.
- Unfinished payments are resumed at startup, and every state change and PayPal call is written to the audit log.

## Security notes

- **Secrets stay on the server.** PayPal credentials, the sandbox card and the Gemini key are read from `.env` (git-ignored) as secret values, are never returned by the API or written to the audit log, and the Gemini key is sent in a header, not the URL. Error messages from PayPal and Gemini are reduced to the status and PayPal's own explanation.
- **Scam text is treated as hostile.** The message goes to the AI inside a delimiter the scammer cannot predict, with instructions in it reported as manipulation; AI evidence is kept only if it appears word for word in what the sender received; the AI can raise a risk level but never lower one; and "Ask your activity" can only produce filters that are checked against known columns and values. A broken or unexpected AI reply means "rules only", never a failed or unchecked payment.
- **Inputs are bounded.** Amounts, text lengths and list sizes are validated; request bodies over 8 MB are refused before they are read; screenshots must be real PNG, JPEG or WebP files under 4 MB and are stored under a content fingerprint, so a name can never point outside the upload folder. All SQL uses parameters.
- **Rate limits per visitor** on the endpoints that create things or call the AI (per minute: 20 payments, 10 screenshots, 20 AI checks, 30 messages; configurable in `.env`). Going over returns 429 with a plain "please wait N seconds" message and `Retry-After`. Reading is never limited.
- **The CSV report is safe to open in a spreadsheet:** cells that start like a formula (a payee named `=HYPERLINK(...)`) are written as text.
- Dependencies: `npm audit` and `pip-audit` reported no known vulnerabilities on Nov 10, 2026.

## Honest limits

- All money is PayPal sandbox test money. In the sandbox every payment settles to one sandbox merchant account; the payee name is a label.
- The risk level is a decision aid, not a validated fraud probability.
- There is no real login: a toggle switches between the sender and guardian views, and the API trusts whoever calls it. A real deployment needs sender and guardian accounts, server-side checks that only the linked guardian can approve or decline. The rate limits are per IP address and in memory (one server process).
- This is a demo of a protection workflow, not a certified fraud-prevention product.

## License

MIT, see [LICENSE](LICENSE).
