# SafePay Guardian build plan

Deadline: **Thursday Nov 12, 2026, 12:00pm Pacific (2:00pm Central).** Build Mon to Wed; Thursday is buffer only (the move is Friday).
Source: "SafePay Guardian: Full Build Spec" (Nov 9, 2026). This file is the plan: decisions that fill the spec's gaps, the design rules, and the phases. Current state, how to run things and the progress log live in [HANDOFF.md](HANDOFF.md).

## Phases

| Phase | Planned | Status | Work | Done when |
|---|---|---|---|---|
| 0 Setup | Mon | **Done Nov 9** | Repo, LICENSE, .gitignore, .env.example, FastAPI skeleton, /health | /health responds, tests pass, no secrets committed |
| 1 Payment core | Mon | **Done Nov 9** | SQLite schema, PayPal gateway (real + fake), state machine with claims, request ids, audit log, sweeper, payment endpoints | Safety tests pass; real sandbox hold-capture and hold-void through the API |
| 2 Risk engine | Tue AM | **Done Nov 9** | Rules, AI (schema, prompt, grounding, timeout, fallback), 25 scam patterns + BM25, aggregation, POST /assess | D1, D2, D3 High with AI; rules-only works with no key |
| 3 Evaluation | Tue PM | **Done Nov 9** | 16 cases, run_eval.py, metrics, ablation, results.md, cache; tune once and freeze | Table prints; scams 100% High; 0/4 legit held |
| 4 Sender screen | Tue eve | **Done Nov 9** | See "Phase 4 scope" | All three outcomes (sent, warned, held) work end to end in the browser |
| 5 Guardian screens | Wed AM | **Done Nov 9** | See "Phase 5 scope" | Both sides drive all three demo scenarios |
| 6 Demo prep | Wed early PM | **Done Nov 9** | Seed/reset script, `demo/` messages, cached demo AI replies, fake-mode check, rehearse 3x | Clean run of all 3 scenarios on the real sandbox |
| 6b Upgrades | Tue Nov 10 | In progress (1-6 done) | See "Phase 6b scope" (agreed Nov 9) | Items 1-4 done and re-rehearsed; 5-6 if time |
| 7 Ship | Wed | Not started | README, secret scan, fresh-clone test, optional hosted no-keys demo on Render (only if time), video, Devpost submit | Submission shows as submitted |
| 8 Buffer | Thu AM | — | Fixes only; stop by noon Central | |

**Cut order** if something slips (cut from the top): screenshot analysis, Insights cards, scam-pattern retrieval, AG Grid (use a plain table). If Ask the payer is cut, demo 3 goes straight to "guardian declines".
**Never cut:** the PayPal flow, the safety tests, evidence grounding, the evaluation table, the video.

### Phase 4 scope: sender screen

- `frontend/`: React + Vite + TypeScript. The Vite dev server proxies `/api` to the backend on port 8000, so the browser never needs CORS.
- App shell on every screen: "Sandbox: test money only" label, and an "I am the sender / I am the guardian" switch (no real login; README says so).
- Polling hook: every 3 seconds, paused while the tab is hidden. Only our backend is polled, never PayPal.
- Send form (large text): who, how much, a note, and "Paste the message you received (optional)". Button: "Send for check". While waiting: "Checking your payment…".
- Result screens, worded by the backend's `text.sender` (never "authorization voided" on the sender side):
  - **Sent** (CAPTURED): "Payment completed."
  - **Warning** (WARNED): the reasons in plain words, the message with the evidence words highlighted, buttons Continue and Cancel.
  - **On hold** (HELD): "This payment is on hold. Your guardian was asked to look at it. Here is why." Updates itself every 3 seconds; shows the guardian's note and questions, with a reply box.
  - Every other status (declined, cancelled, expired, could not be started, approved but not gone through yet) shows its plain sentence.
- Risk shown as a badge with a word and a colour (never colour alone). No numeric score on the sender side.
- "AI check unavailable, rules only" banner whenever the assessment ran without the AI.
- "Your recent payments" list so a held payment can be reopened.
- Accessibility: base text 20px or larger, high contrast, buttons at least 48px tall, visible focus, status changes announced through `aria-live`.
- Tests: a unit test for the highlight segmentation (overlapping spans, offsets); `npm run build` type-checks.

### Phase 5 scope: guardian screens

- Queue: pending payments newest first (held, capture failed, void failed), with risk badge, payee, amount, time waiting.
- Review: risk level and summary, evidence list with quoted words, highlighted full message, matched scam pattern, payee history, hold timer, "heuristic score" label. Actions: Approve, Decline (with a note to the sender), Retry after a failure, Ask the payer (two-way thread). Guardian wording: "Payment not captured, authorization voided."
- Activity: AG Grid Community with status, risk, category, payee, amount, decision, decided by, time; sort and filter.
- Insights cards: payments held from capture, declined, total value held, top scam categories (needs `GET /stats`).

### Phase 6b scope: upgrades (agreed Nov 9, in priority order; cut from the bottom)

1. **Done Nov 9.** **Trademark fix** (15 min): demo scenario 1 says "gift cards", not "Google Play gift cards" (the rules forbid third-party trademarks in the video). Store the new AI reply.
2. **Done Nov 9.** **AG Grid Tier 1, Community only** (2-3 h): cells flash on live status changes, row styling by state (badges stay), evidence tooltips (list rows gain summary + top quotes), columns Top evidence / Checked by / Voids in, preset views (Needs a decision, Stopped, High risk, Flagged by AI, All), date + floating filters, pinned totals row for the filtered view, CSV report export, remembered column state, keyboard (Enter opens review), "Review ->" button on waiting rows. **No approve/decline inside the grid**: decisions stay on the review page where the evidence is.
3. **Done Nov 10.** **Screenshot analysis** (2-3 h): upload a screenshot, Gemini extracts the conversation, the sender confirms the extracted text, then the unchanged engine runs; evidence is grounded in the confirmed text; the guardian sees the image and the text. Demo scenario 3 switches to uploading our own made-up text-message screenshot (pasted text stays as fallback).
4. **Done Nov 10.** **Held-out evaluation** (2.5-3 h): about 60 new cases, never used for tuning, reported separately from the 16-case development set, even if the numbers drop. About 30 scams across about 15 current categories and about 10 adversarial/robustness cases, written in our own words from scam patterns published by the FTC, FBI IC3 and AARP (each case cites its source); about 20 legitimate cases including tricky ones. Plus about 8 real messages from a public labelled SMS dataset, only after verifying its license (with attribution). Stored replies also extend replay mode.
5. **Done Nov 10.** **"Ask your activity"** (2-3 h): a plain-English question becomes an AG Grid filter via Gemini structured output, validated against known columns and operators, shown as chips; filter-only, never acts on money; stored replies for demo questions.
6. **Done Nov 10.** **AG Charts Community on Insights** (1-1.5 h): category chart, held vs captured over time, frequently flagged recipients (small `/stats` addition).
6a. **Done Nov 10.** **Security and robustness review** of the whole codebase before polish (see the handoff progress log).
7. **Polish and wrap-up** (1.5 h): sender safety-tips box on the hold screen; README "three layers" framing (communication, transaction, payment protection) and a note that production would use PayPal Checkout with payer approval and webhooks; tests, screenshot checks, re-rehearsal, runbook and video script, plan and handoff.

The risk engine and the 16-case evaluation stay frozen throughout.

### Reviewed and declined (Nov 9, input from a second AI review)

| Suggestion | Why not now |
|---|---|
| Elastic hybrid search | No Elastic prize; adds a service judges must run; only replaces working BM25 retrieval |
| Render Workflows | Architecture churn for no product gain; Render hosting of the no-keys demo stays an optional Wednesday item |
| APIMatic | A developer tool, not part of the product |
| Supabase | SQLite needs no setup for judges |
| PayPal webhooks | Need a public URL; polling our own backend is fine for the hackathon (README says production would use webhooks) |
| New behaviour rules (e.g. payment velocity) | The engine is frozen; changing it means re-tuning two days before the deadline |
| AG Grid Enterprise (AI Toolkit, grouping, master/detail) | Needs a paid license; without one, judges see a watermark |

## Decisions (agreed Nov 9)

| # | Topic | Decision |
|---|---|---|
| 1 | Fake PayPal | In-process fake behind a `PaymentGateway` interface; used by pytest and by `PAYPAL_MODE=fake` so judges can run without credentials |
| 2 | Payees | Labels only. In the sandbox every payment settles to one sandbox merchant; README says so |
| 3 | AI | Gemini, structured JSON, behind a small provider interface; no key = rules only. Model `gemini-3.1-flash-lite` (switched from `gemini-2.5-flash` on Nov 9 after its 20 requests/day free limit ran out) |
| 4 | AI timeout | 12 s in the app (raised from 8 s on Nov 10 after two live timeouts from `gemini-3.1-flash-lite`): a slow AI still falls back to rules with the banner. The demo uses stored replies (`demo/ai-cache`) so the recording does not depend on live latency |
| 5 | D3 / demo 3 | Keep "safe account" as a hard rule; D3 and demo 3 use a paraphrase ("the protected account our security team set up") so the AI is what catches it |
| 6 | Extra rules | "Changed number / new phone" (+25) and "new payee with no note and no message" (+15) |
| 7 | Ask the payer | Promoted from Medium to High (used in demo 3) |
| 8 | Sender cancel | The sender may cancel a held payment. Warned payments time out like held ones |
| 9 | CAPTURE_FAILED | The hold timeout voids it if nobody retries |
| 10 | Frontend | React + Vite + TypeScript |
| 11 | Python deps | pip + pinned `backend/requirements.txt`, venv at repo root `.venv` |
| 12 | Repo | This folder is the repo root; GitHub `him-agni/safepay_guardian`; MIT, Himani Agrawal; commits only as "Himani Agrawal" with the GitHub no-reply email, no co-author lines; small detailed commits |
| 13 | Personas | Sender "Margaret", guardian "Daniel" (her son) |
| 14 | Hosting | Local only |
| 15 | Trusted payee flag | Must (seeded data); a UI to manage it stays Medium |
| 18 | AG Grid prize | Official rules: open to submissions "that use any AG Grid tools"; we enter it with Community features only |
| 19 | Video trademarks | No third-party brands in demo messages shown on screen (rules) |
| 20 | Evaluation growth | Held-out set evaluated on the frozen engine, reported separately, no tuning on it |
| 21 | Hosting | Optional no-keys demo on Render only if Wednesday has time; never host with real keys |
| 17 | Replay mode | `AI_PROVIDER=replay` serves stored AI replies with no key (for judges and the video); anything not stored falls back to rules with the banner; the review labels it "(stored reply)" |
| 16 | Evaluation freeze | Tuned once on Nov 9 (prompt `2026-11-10.2`, config `2026-11-10.2`), then frozen. Any change means re-running the eval and saying so |

## Design rules

### Payment state machine

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

Final statuses: CAPTURED, VOIDED, EXPIRED, AUTH_FAILED.

- Claim before calling PayPal: one write transaction moves the payment to CAPTURING or VOIDING; only the caller that made the change talks to PayPal. A repeat in the same direction returns the first result; the opposite direction gets a 409 with a plain reason.
- The authorization is read from PayPal before every capture and void.
- PayPal-Request-Id: `{payment_id}-{action}-{attempt}`. Network and 5xx retries reuse it; a definite 4xx moves to the next attempt.
- Sweeper every 5 s and at startup: voids expired WARNED, HELD and CAPTURE_FAILED; retries VOID_FAILED; resumes stuck payments.
- The audit log never stores request bodies (card number) or tokens; it stores PayPal debug ids.
- One uvicorn worker.

### Risk engine

- Score thresholds: under 30 Low, 30 to 59 Medium, 60+ High. Labelled a heuristic score, never a probability. All numbers in `backend/app/risk/config.py`.
- Final level = highest of: the rules level (hard rules = High); the combined score level capped at the AI's own recommendation; the AI floor (needs at least one grounded indicator). The AI can raise, never lower.
- The same indicator type from a rule and the AI counts once.
- The AI's summary is shown only when its recommendation matches the final level.
- Grounding: lowercase, collapse whitespace, straighten quotes and dashes; evidence under 4 characters is dropped; the backend returns character offsets for highlighting.
- Retrieval: BM25, score at least 6 and within 60% of the best match; no weight; top 3 go into the prompt.
- Prompt: the message sits inside a tag derived from its own hash (it cannot close it); temperature 0.

### Wording

- Sender side: "on hold", "declined", "No payment was taken" (only after the void succeeds). Never "authorization voided".
- Guardian side: "Payment not captured, authorization voided."
- Never "money saved" or "the money never moved". Use "attempted payments held from capture".

## Still open

- Hackathon Devpost URL, submission-period start date, judging criteria (needed for the README and Devpost text).
