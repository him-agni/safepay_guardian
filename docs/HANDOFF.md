# SafePay Guardian handoff

For whoever picks this up next, whether Himani or a fresh AI session: what exists, how to run and check it, what to watch out for, and what comes next. **Update this file at the end of every phase.** The plan itself (phases, decisions, design rules) is in [BUILD_PLAN.md](BUILD_PLAN.md).

Last updated: Nov 9, 2026, after Phase 3 (Phase 4 starting).

## Where things stand

| Area | State |
|---|---|
| Backend (FastAPI) | Complete for the Must list: payments, state machine, sweeper, recovery, audit log, hybrid risk engine, `/assess`, `/health` |
| PayPal | Real sandbox works end to end (authorize, capture, void), cross-checked on PayPal by `scripts/api_smoke.py` |
| AI | `gemini-3.1-flash-lite`, structured JSON, grounding, rules-only fallback |
| Evaluation | Frozen: hybrid 16/16, rules only 12/16, AI only 15/16; scams 9/9; 0/4 legit held; consistent over 3 runs ([eval/results.md](../eval/results.md)) |
| Tests | 82 pytest tests, all passing, all offline |
| Frontend | Not built yet (Phase 4 next) |
| Not built yet | `GET /stats`, seed/reset script, `demo/` messages, guardian screens, AG Grid, Insights, video, Devpost submission |

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
| `scripts/` | `sandbox_gate.py`, `api_smoke.py` |

## API shape the frontend relies on

`GET /payments/{id}` returns: `id`, `status`, `amount` ("500.00"), `payee {name, trusted, captured_payments}`, `note`, `message_text`, `risk {level, score, score_label, mode, ai_unavailable, ai_unavailable_text, summary, category, indicators[], evidence_spans[], patterns[]}`, `text {sender, guardian}`, `can {confirm, cancel, approve, decline, retry}`, `hold_seconds_left`, `decision_note`, `decided_by`, `last_error`, `final`, `events[]`, `messages[]`.

- `risk.indicators[]`: `{source: rule|ai, type, label, evidence, explanation, weight, hard, spans[]}`. `label` is plain language for the sender.
- `risk.evidence_spans[]`: `{field: message|note, start, end, text, type, source}`, offsets into the original `message_text` or `note`.
- `GET /payments?queue=guardian` lists the guardian queue; `?status=HELD,WARNED` filters.
- Actions: `POST /payments/{id}/confirm|cancel|approve|decline|retry` with optional `{note}`; a 409 returns `{error, message, payment}`.

## Gotchas

- **Gemini free tier is 20 requests/day per model** (it was for `gemini-2.5-flash`). Every payment created with the AI on costs one request. For demo rehearsals and the video, set `AI_CACHE_DIR` so repeated demo messages reuse stored replies. `gemini-3.1-flash-lite` has its own quota, limit unknown; about 80 calls worked on Nov 9.
- **`gemini-3.1-flash-lite` sometimes takes over 8 s.** The app then falls back to rules with the banner (by design). The eval uses `--timeout 25`.
- **Never read or print `.env`.** Check keys with a script that prints only "set/EMPTY". The card expiry there is `MM/YYYY`; config converts it to PayPal's `YYYY-MM`.
- **Commits:** only "Himani Agrawal" with `100171053+him-agni@users.noreply.github.com` (set in the repo's git config), no co-author lines, small commits with descriptive bodies. Shell heredocs break on apostrophes, so commit through a small Python script with `git commit -F -`. Scan before pushing: `git log -p origin/main..HEAD | grep -E "AIza|[0-9]{15,16}"`.
- **Evaluation is frozen** (prompt `2026-11-10.2`, config `2026-11-10.2`). Changing `risk/config.py`, the prompt or the rules changes the results: re-run the eval and record it.
- Start uvicorn with `--factory`. Importing `app.main` never touches the real database.
- SQLite files live in `data/` (git-ignored). Payment ids are UUIDs, so PayPal request ids never repeat after a reset.
- Known wart, left on purpose: in the Phase 2 history, deleting `risk/stub.py` landed in the first Phase 2 commit, so a few intermediate commits do not start. The final code is fine.

## Open questions for Himani

- Hackathon Devpost URL, submission-period start date, judging criteria.
- AI timeout: keep 8 s or raise to about 12 s (currently 8 s).

## Progress log

- **Nov 9, Phase 0.** Repo, MIT license, `.env.example`, FastAPI skeleton, `/health`. Pushed to github.com/him-agni/safepay_guardian; history rewritten before the first push so only the no-reply email appears.
- **Nov 9, gate test.** The old gate scripts were lost; `scripts/sandbox_gate.py` rewritten and passed. Card orders come back COMPLETED with the authorization attached.
- **Nov 9, Phase 1.** State machine with claims, fake PayPal with fault injection, 49 tests (mutation-checked), sandbox smoke test passed with every authorization cross-checked on PayPal.
- **Nov 9, Phase 2.** Hybrid engine. D1, D2, D3 High with the AI (D3 is only Medium on rules). The Phase 1 placeholder engine was removed.
- **Nov 9, Phase 3.** 16-case evaluation. Switched to `gemini-3.1-flash-lite` after the 2.5-flash quota ran out. First run 15/16 (A2 miss); one tuning round (trusted-payee prompt rule, AI weights capped at the AI's own recommendation); frozen at 16/16, consistent over 3 runs. 82 tests.
