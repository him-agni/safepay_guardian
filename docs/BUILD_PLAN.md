# SafePay Guardian build plan

Deadline: Thursday Nov 12, 2026, 12:00pm Pacific (2:00pm Central). Build Mon to Wed; Thursday is buffer only.
The full product spec is the "SafePay Guardian: Full Build Spec" (Nov 9, 2026). This file records the decisions that fill its gaps.

## Decisions (agreed Nov 9)

| # | Topic | Decision |
|---|---|---|
| 1 | Fake PayPal | Rebuilt in-process behind a `PaymentGateway` interface; used by pytest and by `PAYPAL_MODE=fake` at runtime so judges can run without credentials |
| 2 | Payees | Labels only. In the sandbox all payments settle to one sandbox merchant; README says so |
| 3 | AI | Gemini Flash, structured JSON output, behind a small provider interface; no key = rules only |
| 5 | D3 / demo 3 | Keep "safe account" in the hard rule; D3 and demo 3 use a paraphrase ("the protected account our security team set up") so the AI is what catches it |
| 6 | Extra rules | Add "changed number / new phone" (+25) and "new payee with no note and no message" (+15) |
| 7 | Ask the payer | Promoted from Medium to High (used in demo 3) |
| 8 | Sender cancel | Sender may cancel a HELD payment. WARNED payments time out like held ones |
| 9 | CAPTURE_FAILED | Timeout voids it if nobody retries |
| 10 | Frontend | React + Vite + TypeScript |
| 11 | Python deps | pip + pinned `backend/requirements.txt`, venv at repo root `.venv` |
| 12 | Repo | This folder is the repo root; GitHub repo `safepay-guardian`; MIT, Himani Agrawal |
| 13 | Personas | Sender "Margaret", guardian "Daniel" (her son) |
| 15 | Hosting | Local only |
| — | Trusted payee flag | Promoted to Must (seeded data); a UI to manage it stays Medium |

## Payment state machine

Statuses: CREATED, AUTH_FAILED, AUTHORIZED, WARNED, HELD, CAPTURING, VOIDING, CAPTURED, VOIDED, EXPIRED, CAPTURE_FAILED, VOID_FAILED. `void_reason` is `sender_cancel`, `guardian_decline` or `timeout`.

| From | To |
|---|---|
| CREATED | AUTHORIZED, AUTH_FAILED |
| AUTHORIZED | CAPTURING (low), WARNED (medium), HELD (high) |
| WARNED | CAPTURING (sender confirm); VOIDING (sender cancel, timeout) |
| HELD | CAPTURING (guardian approve); VOIDING (guardian decline, sender cancel, timeout) |
| CAPTURING | CAPTURED; CAPTURE_FAILED; VOIDED or EXPIRED if PayPal already shows it voided or expired |
| VOIDING | VOIDED, EXPIRED (timeout reason), VOID_FAILED |
| CAPTURE_FAILED | CAPTURING (retry); VOIDING (decline, timeout) |
| VOID_FAILED | VOIDING (automatic retry by the sweeper) |

Terminal: CAPTURED, VOIDED, EXPIRED, AUTH_FAILED.

- Claim before calling PayPal: `UPDATE payments SET status='CAPTURING' WHERE id=? AND status IN (...)`, proceed only if one row changed. The loser of a race gets a 409 with the current status; a repeat of the same action returns the stored result.
- Startup recovery: any row in CAPTURING or VOIDING is reconciled by reading the authorization from PayPal.
- Sweeper: asyncio task every 15 s plus at startup; voids expired WARNED, HELD and CAPTURE_FAILED, retries VOID_FAILED.
- PayPal-Request-Id: `{payment_id}-{action}-{attempt}`. Network/5xx retries reuse the id; a guardian retry after a definite failure increments `attempt`. The authorization is read before every capture.
- PayPal capture `PENDING` counts as captured (pending). Authorization `DENIED` maps to AUTH_FAILED.
- Audit log never stores request bodies (card number) or tokens. Stores `paypal-debug-id`.
- Single uvicorn worker.

## Risk engine numbers (tune once on Tuesday, then freeze)

- Thresholds: score < 30 Low, 30 to 59 Medium, 60+ High. All in one config file.
- Unusual amount: more than 3x the sender's median past payment, or above the per-sender limit.
- Same indicator type from rules and AI counts once (higher weight).
- AI floor: `guardian_review` with confidence medium/high and at least one grounded indicator = High; `warn` = at least Medium; an ungrounded escalation is logged and sets no floor.
- Final level = max(rules level, score level, AI floor). The AI never lowers anything.
- AI summary is shown to the sender only if its recommended action matches the final level; otherwise a rules-built plain-language summary.
- Grounding: lowercase, collapse whitespace, normalise curly quotes and dashes; drop evidence under 4 characters; "payment text" is `amount / payee / note`. The backend returns character offsets for highlighting.
- Retrieval: BM25 with a minimum score; matches add no weight, are shown as "similar known pattern", and the top 3 go into the AI prompt.
- Prompt: message inside delimiters marked as untrusted data; short sender-history summary; temperature 0.

## Evaluation additions

- `cases.json` carries each case's sender history and trusted payees.
- AI only = recommended action mapped directly (proceed/warn/guardian_review = Low/Medium/High), same context.
- AI responses cached in `eval/cache/` and committed; `run_eval.py --cached` runs offline.
- Optional: 6 held-out cases written after freezing, reported separately.

## Phases

| Phase | When | Work | Done when |
|---|---|---|---|
| 0 Setup | Mon | Repo, LICENSE, .gitignore, .env.example, FastAPI skeleton, /health, this plan | /health responds, tests pass, first commit has no secrets |
| 1 Payment core | Mon | db.py (7 tables + new columns), PaymentGateway (real + fake), state machine with claims, request ids, audit log, sweeper, payment endpoints with a stub risk engine | 10 pytest safety tests pass; real sandbox create-hold-capture and create-hold-void via the API |
| 2 Risk engine | Tue AM | rules.py, ai.py (schema, prompt, grounding, 8 s timeout, fallback), patterns.py (25 templates, BM25), engine.py, POST /assess | D1, D2, D3 High with AI; rules-only works with no key |
| 3 Evaluation | Tue PM | 16 cases, run_eval.py, metrics, ablation, results.md, cache; tune once and freeze | Table prints; scams 100% High; 0/4 legit held |
| 4 Sender screen | Tue eve | Vite app, role toggle, sandbox label, 3 s polling; send form; sent/warning/on-hold results with highlights; large text; aria-live | All three outcomes end to end |
| 5 Guardian screens | Wed AM | Queue, review (evidence, pattern, payee history, message, hold timer), approve/decline/note, retry, AI-unavailable banner, AG Grid, Insights, Ask the payer | Both sides drive all three demo scenarios |
| 6 Demo prep | Wed early PM | Seed/reset script, demo/ messages, fake mode check, rehearse 3x | Clean run of all 3 scenarios on the real sandbox |
| 7 Ship | Wed PM to eve | README, secret scan, fresh-clone test, video, Devpost submit | Submission shows as submitted |
| 8 Buffer | Thu AM | Fixes only; stop by noon Central | |

Cut order if something slips: screenshot analysis, Insights cards, scam-pattern retrieval, AG Grid (plain table). If Ask the payer is cut, demo 3 goes straight to "guardian declines".
Never cut: PayPal flow, safety tests, evidence grounding, evaluation table, video.

## Still open

- Hackathon Devpost URL, submission-period start date, judging criteria.
- Gate scripts from the earlier sandbox test (not in this folder yet).
- PayPal sandbox client id/secret and test card go into `.env` (Phase 1 sandbox run).
- Gemini API key goes into `.env` (Phase 2).
