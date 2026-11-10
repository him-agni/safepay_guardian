# SafePay Guardian handoff

For whoever picks this up next, whether Himani or a fresh AI session: what exists, how to run and check it, what to watch out for, and what comes next. **Update this file at the end of every phase.** The plan itself (phases, decisions, design rules) is in [BUILD_PLAN.md](BUILD_PLAN.md).

Last updated: Nov 10, 2026. Upgrades 1-5 done (trademark-free demo, activity case log, screenshot reading, 69-case held-out evaluation, "Ask your activity"); next is AG Charts and polish (BUILD_PLAN.md), then shipping on Wed.

## Where things stand

| Area | State |
|---|---|
| Backend (FastAPI) | Complete: payments, state machine, sweeper, recovery, audit log, hybrid risk engine, `/assess`, `/stats`, `/health` |
| PayPal | Real sandbox works end to end (authorize, capture, void), cross-checked on PayPal by `scripts/api_smoke.py` |
| AI | `gemini-3.1-flash-lite`, structured JSON, grounding, rules-only fallback |
| Evaluation | Frozen: hybrid 16/16, rules only 12/16, AI only 15/16; scams 9/9; 0/4 legit held; consistent over 3 runs ([eval/results.md](../eval/results.md)). **Held-out (69 cases, never tuned on):** hybrid 68/69, scams held 44/46 and all warned, 0/17 legit held ([eval/results_heldout.md](../eval/results_heldout.md)) |
| Tests | 120 pytest tests and 33 Vitest unit tests, all passing, all offline |
| Frontend | Both sides done. Sender: send, sent, warning, on hold, declined, messages. Guardian: queue, review (evidence with rule/AI labels, pattern, payee history, hold timer, approve with confirm step, decline with note, retry, ask the payer, audit log), Activity (AG Grid, lazy-loaded), Insights (stat tiles, top categories) |
| Demo | `demo/README.md` runbook, `demo/scenarios.json`, stored AI replies in `demo/ai-cache/`, `scripts/reset_demo.py` (voids open holds, seeds history), `scripts/demo_rehearsal.py` (plays all three scenarios and checks PayPal). Rehearsed 3x on the real sandbox, all passed. Replay mode lets judges run it with no keys |
| Not built yet | Fresh-clone test, final README pass, video, Devpost submission (Phase 7). Optional: screenshot analysis (stretch), trusted-payee management UI (Medium) |

## Run and check

All commands from the repo root in Git Bash on Windows (use `.venv/bin/python` on macOS/Linux).

```bash
# Tests (offline, about 5 s)
cd backend && ../.venv/Scripts/python -m pytest -q -p no:warnings && cd ..

# Backend (reads .env; PAYPAL_MODE=sandbox and AI_PROVIDER=gemini are set in Himani's .env)
cd backend && ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000

# Raw PayPal sandbox check
.venv/Scripts/python scripts/sandbox_gate.py

# End-to-end through the API, then cross-check on PayPal (start the backend with a short hold first)
cd backend && HOLD_TIMEOUT_SECONDS=20 SWEEPER_INTERVAL_SECONDS=2 DATABASE_PATH=data/smoke.db \
  ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000
.venv/Scripts/python scripts/api_smoke.py

# Frontend (second terminal; backend must be running on :8000)
cd frontend && npm install && npm run dev        # http://localhost:5173
# (in background tasks run `node node_modules/vite/bin/vite.js --port 5173` instead: stopping `npx vite` leaves its node child holding the port)
cd frontend && npm test && npm run build && npx oxlint src

# UI check without PayPal or Gemini quota: fake PayPal, rules only, separate database
cd backend && PAYPAL_MODE=fake AI_PROVIDER=none DATABASE_PATH=data/ui.db   ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000

# Demo: backend in demo mode, reset before each take, optional rehearsal (see demo/README.md)
cd backend && AI_CACHE_DIR=demo/ai-cache DATABASE_PATH=data/demo.db HOLD_TIMEOUT_SECONDS=120   ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000
DATABASE_PATH=data/demo.db .venv/Scripts/python scripts/reset_demo.py
DATABASE_PATH=data/demo.db .venv/Scripts/python scripts/demo_rehearsal.py --runs 3 --standalone 3

# Judge mode: no keys (fake PayPal + stored AI replies)
cd backend && PAYPAL_MODE=fake AI_PROVIDER=replay AI_CACHE_DIR=demo/ai-cache DATABASE_PATH=data/judge.db   ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000

# Evaluation: offline from committed replies, or live
PYTHONIOENCODING=utf-8 .venv/Scripts/python eval/run_eval.py --cached
PYTHONIOENCODING=utf-8 .venv/Scripts/python -u eval/run_eval.py --repeat 3 --sleep 4 --timeout 25
```

Environment: Python 3.10.2 in `.venv` (the `py` launcher defaults to 3.14, so use the venv), Node 24, npm 11. `gh` is not installed; git pushes over HTTPS work.

## Map of the code

| Path | What it does |
|---|---|
| `backend/app/main.py` | `create_app()` factory, routes, lifespan (recovery + sweeper), `/health` |
| `backend/app/state.py` | `PaymentService`: create, decide (claim then capture or void), sweep, recover, serialisation, status text for sender and guardian |
| `backend/app/paypal.py` | `PayPalClient` (sandbox) and `FakePayPal` (fault injection), `request_id()` |
| `backend/app/db.py` | Schema, migrations (`ADDED_COLUMNS`), `transaction()` with BEGIN IMMEDIATE |
| `backend/app/risk/` | `rules.py`, `ai.py` (prompt, schema, Gemini, cache), `text.py` (grounding), `patterns.py` (BM25), `engine.py` (aggregation), `config.py` (all numbers, frozen) |
| `backend/tests/` | Payment safety, PayPal client, risk engine, eval-set tests |
| `eval/` | `cases.json`, `run_eval.py`, `results.md/json`, `cache/` (committed AI replies), `history/` (before-tuning run) |
| `scripts/` | `sandbox_gate.py`, `api_smoke.py`, `reset_demo.py`, `demo_rehearsal.py` |
| `backend/app/demo.py` | Seed history (3 payees, 7 past payments, typical ~$50, marked `is_seed`), reset, void open authorizations |
| `demo/` | Runbook, scenarios, stored AI replies |
| `frontend/src/` | `App.tsx` (shell, header, hash routes `#/send`, `#/send/{id}`, `#/guardian`), `api.ts` (only network code), `types.ts`, `hooks.ts` (3 s polling, countdown, hash router), `highlight.ts` (evidence segments), `format.ts` (wording helpers), `components.tsx` (risk badge, AI banner, highlighted message, messages thread), `sender/` (SendPage, PaymentPage), `guardian/` (GuardianArea routes, QueuePage, ReviewPage, ActivityPage with AG Grid v36, InsightsPage, `events.ts` audit-log wording) |

## API shape the frontend relies on

`GET /payments/{id}` returns: `id`, `status`, `amount` ("500.00"), `payee {name, trusted, captured_payments}`, `note`, `message_text`, `risk {level, score, score_label, mode, ai_unavailable, ai_unavailable_text, summary, category, indicators[], evidence_spans[], patterns[]}`, `text {sender, guardian}`, `can {confirm, cancel, approve, decline, retry}`, `hold_seconds_left`, `decision_note`, `decided_by`, `last_error`, `final`, `events[]`, `messages[]`.

- `risk.indicators[]`: `{source: rule|ai, type, label, evidence, explanation, weight, hard, spans[]}`. `label` is plain language for the sender.
- `risk.evidence_spans[]`: `{field: message|note, start, end, text, type, source}`, offsets into the original `message_text` or `note`.
- `GET /payments?queue=guardian` lists the guardian queue; `?status=HELD,WARNED` filters.
- Actions: `POST /payments/{id}/confirm|cancel|approve|decline|retry` with optional `{note}`; a 409 returns `{error, message, payment}`.

## Gotchas

- **Gemini free tier is 20 requests/day per model** (it was for `gemini-2.5-flash`). Every payment created with the AI on costs one request. For demo rehearsals and the video, set `AI_CACHE_DIR` so repeated demo messages reuse stored replies. `gemini-3.1-flash-lite` has its own quota, limit unknown; about 80 calls worked on Nov 9.
- **`gemini-3.1-flash-lite` sometimes takes over 8 s** (twice in live use, Nov 9 and 10). The app timeout is now 12 s; past it, the app falls back to rules with the banner (by design). The eval uses `--timeout 25`.
- **Never read or print `.env`.** Check keys with a script that prints only "set/EMPTY". The card expiry there is `MM/YYYY`; config converts it to PayPal's `YYYY-MM`.
- **Commits:** only "Himani Agrawal" with `100171053+him-agni@users.noreply.github.com` (set in the repo's git config), no co-author lines, small commits with descriptive bodies. Shell heredocs break on apostrophes, so commit through a small Python script with `git commit -F -`. Scan before pushing: `git log -p origin/main..HEAD | grep -E "AIza|[0-9]{15,16}"`.
- **Ask your activity:** the frontend sends a fixed column description (`frontend/src/guardian/ask.ts`, `ASK_COLUMNS`); the backend (`app/activity_query.py`) validates every proposed filter against it. Stored replies match only if that description and the question are identical; dates go into the prompt only for time questions. If you change `ASK_COLUMNS`, re-store the three example questions with live Gemini.
- **Held-out set:** `eval/heldout_cases.json` was written after the freeze and must never be used for tuning. Run it with `--cases eval/heldout_cases.json --out results_heldout`. The 11 real messages come from a CC BY 4.0 dataset: keep the attribution in the file and the README.
- **Evaluation is frozen** (prompt `2026-11-10.2`, config `2026-11-10.2`). Changing `risk/config.py`, the prompt or the rules changes the results: re-run the eval and record it.
- Start uvicorn with `--factory`. Importing `app.main` never touches the real database.
- SQLite files live in `data/` (git-ignored). Payment ids are UUIDs, so PayPal request ids never repeat after a reset.
- **Screenshots for checking the UI:** Edge headless works (`msedge --headless=new --screenshot=... --virtual-time-budget=6000`), but give each run its own `--user-data-dir` (runs sharing one attach to the first and are dropped), wait for the file (Edge returns before writing it), and note headless windows have a minimum width of about 500px: for a true 400px phone view, load the app inside a 400px iframe served from the Vite dev server (a `file://` wrapper does not load).
- **Gemini busy spells (Nov 10):** `gemini-3.1-flash-lite` returned HTTP 503 "high demand" and timeouts for long stretches. The client retries a 503 once after 1.5 s; past that the engine falls back to rules. Without the AI, demo scenario 3 (no scam keywords) is only Medium: that is the honest rules-only result. Stored replies keep the demo independent of this.
- **Screenshots** are saved in `data/uploads/` (git-ignored) under a SHA-256 name; stored transcriptions in `demo/ai-cache/img-*.json` are keyed by the image's fingerprint, so a re-saved or edited PNG needs a new live read.
- **AG Grid update loop:** setting `pinnedBottomRowData` fires `onModelUpdated`; recomputing the totals there must skip unchanged totals (`ActivityPage.tsx` keeps a key) or the page never settles (headless screenshots time out, real browsers burn CPU).
- AG Grid v36.2 deprecated `tooltipValueGetter`; use `tooltip: (params) => ...`. `PinnedColumnModule` is not exported; column pinning is core.
- Himani may have her own app running on ports 5173 and 8000: test on other ports (`SAFEPAY_BACKEND=http://localhost:8002 node node_modules/vite/bin/vite.js --port 5174`) and never stop processes you did not start.
- Git Bash rewrites arguments that start with `/`, so `"#/guardian/..."` passed to a script becomes a Windows path. Prefix with `MSYS_NO_PATHCONV=1`.
- AG Grid v36 needs each feature's module registered (`ActivityPage.tsx`); the dev-only `ValidationModule` shows a popup naming any missing one (that is how `CellStyleModule` was found).
- **Stored demo replies only match if the prompt is identical**: same payee, amount, note, message and the same sender history. Reset, then play 1, 2, 3 in order (scenario 2's capture changes the history scenario 3 sees). Scenario 3 is also stored standalone. Changing the prompt or `PROMPT_VERSION` invalidates them: re-run `demo_rehearsal.py --standalone 3` with Gemini on.
- The AI timeout is 12 s (raised from 8 s on Nov 10). Restart the backend after changing it; `.env` sets `AI_TIMEOUT_SECONDS`.
- Sender wording comes from the backend's `text.sender`; the frontend never says "authorization voided" on the sender side (`format.ts` has a test for it).
- Known wart, left on purpose: in the Phase 2 history, deleting `risk/stub.py` landed in the first Phase 2 commit, so a few intermediate commits do not start. The final code is fine.

## Hackathon rules (read Nov 9)

https://paypalaihackathon.devpost.com/rules (WebFetch gets HTTP 403; `curl -A "Mozilla/5.0 ..."` works). Deadline Nov 12, 12:00pm PT. Must use the PayPal sandbox and any AI. Submit a text description, a "Tools" section (which AI and how), a public repo with the license visible in GitHub About (done, MIT), run instructions or a hosted URL, and a public YouTube video under 3 minutes with no third-party trademarks or copyrighted music. Five equally weighted criteria: technical implementation, design, potential impact, innovation, presentation. A project can win one main or honorable-mention prize plus one sponsor prize; the AG Grid prize is open to any AG Grid use. No rule on AI coding assistants.

## Open questions for Himani

- None right now. Phase 6b scope, priorities and the held-out evaluation approach were agreed on Nov 9.

## Progress log

- **Nov 9, Phase 0.** Repo, MIT license, `.env.example`, FastAPI skeleton, `/health`. Pushed to github.com/him-agni/safepay_guardian; history rewritten before the first push so only the no-reply email appears.
- **Nov 9, gate test.** The old gate scripts were lost; `scripts/sandbox_gate.py` rewritten and passed. Card orders come back COMPLETED with the authorization attached.
- **Nov 9, Phase 1.** State machine with claims, fake PayPal with fault injection, 49 tests (mutation-checked), sandbox smoke test passed with every authorization cross-checked on PayPal.
- **Nov 9, Phase 2.** Hybrid engine. D1, D2, D3 High with the AI (D3 is only Medium on rules). The Phase 1 placeholder engine was removed.
- **Nov 9, Phase 3.** 16-case evaluation. Switched to `gemini-3.1-flash-lite` after the 2.5-flash quota ran out. First run 15/16 (A2 miss); one tuning round (trusted-payee prompt rule, AI weights capped at the AI's own recommendation); frozen at 16/16, consistent over 3 runs. 82 tests.
- **Nov 9, docs.** Plan and handoff split into `BUILD_PLAN.md` and `HANDOFF.md`.
- **Nov 9, Phase 4.** Sender screens built and checked in headless Edge at desktop and true 400px phone width against the fake PayPal: send form, sent, warning (Medium, continue or cancel), on hold (High, highlighted evidence, guardian question and reply, countdown, cancel), declined with the guardian's note, rules-only banner. Fixed after review: the rules-built summary repeating the reasons list, four lint warnings.
- **Nov 9, Phase 5.** `GET /stats` and a scam category on list rows. Guardian queue, review, activity grid (AG Grid, loaded only on that tab so the sender's bundle stays ~256 kB), insights. Checked in headless Edge; fixed an AG Grid missing-module error, oversized badges in the grid, truncated columns, header width, doubled brackets, "Not classified" ranked first, and the question box staying open on final payments. All three demo scenarios driven through the app's API on the real sandbox with Gemini; PayPal's own records matched (VOIDED, CAPTURED, VOIDED).
- **Nov 9, Phase 6.** Demo seed and reset (`app/demo.py`, voids open sandbox holds first), `demo/scenarios.json` and runbook, rehearsal script, replay AI mode for judges. Rehearsed 3 full runs plus scenario 3 alone on the real sandbox: every level, status and AI check as expected, all 10 authorizations matched on PayPal; 4 Gemini replies stored. Judge mode (fake PayPal + replay, no keys) passed the same rehearsal. Timeout kept at 8 s.
- **Nov 9, planning.** Read the official rules (project valid; two adjustments: trademark-free demo messages, enter the AG Grid prize). Evaluated a second AI review: most of it was already built; adopted screenshot analysis, the "three layers" framing and the safety-tips box; declined Elastic, Render Workflows, APIMatic, Supabase, webhooks and engine changes. Agreed Phase 6b (AG Grid Tier 1 + 2, screenshot analysis, ~60-case held-out evaluation incl. ~8 real SMS, AG Charts) and an optional no-keys Render demo.
- **Nov 9, Phase 6b items 1-2.** Demo scenario 1 no longer names a brand (new stored reply; re-rehearsed on the sandbox). Activity grid upgraded with AG Grid Community: list rows carry a risk brief (summary, top quoted evidence, rules/AI/stored reply); preset views with counts, evidence tooltips, Top evidence / Checked by / Voids in columns, flashing Status and Decision cells, row styling, date and floating filters, pinned totals row, CSV report, remembered layout, Enter to open, pinned Review button. Found and fixed an update loop between the totals row and the grid, and a v36.2 deprecation.
