# Test run log

Newest first. Modes: **sandbox + Gemini** (real PayPal sandbox, live AI), **demo** (sandbox + stored AI replies, 2-minute hold), **judge** (fake PayPal + stored AI replies, no keys), **fake** (fake PayPal, rules only).

---

## 2026-11-10 · Live · Screenshot reading and demo rehearsal (sandbox + Gemini)

- **Run by:** Claude, on separate ports and a separate database (Himani's own app untouched).
- **Mode:** demo (real sandbox, Gemini with stored replies), new screenshot flow for scenario 3.
- **Steps:** upload `demo/screenshots/bank-fraud-team-text.png` through `POST /screenshots`; run `scripts/demo_rehearsal.py --runs 1 --standalone 3`.
- **Expected:** the AI copies the three received messages word for word and skips Margaret's own reply; scenario 3 is High from the AI; PayPal matches.
- **Actual:**
  - First probe: Gemini answered **HTTP 503 "high demand"**; the second probe transcribed every bubble exactly (1.5 s), labelled the scammer "them" and Margaret "me".
  - In the app, the first two reads failed with 503 (4.0 s and 12.1 s including the new single retry); the third succeeded and is stored.
  - Rehearsal attempt 1: the in-order run passed, but the standalone scenario 3 AI check **timed out at 12 s**, so rules alone decided: **Medium (warning), not High**, exactly as the evaluation predicts for rules alone on this scam. Attempt 2 passed every check; PayPal matched for all authorizations.
  - Found and fixed during the run: a failed read reported the previous call's latency (797 ms every time).
- **Verdict:** Pass after retries. The feature works; the live AI was unreliable today.
- **Follow-up:** the demo uses stored replies; the README states that without the AI, contextual scams get a warning rather than a hold.
- **Screenshot:** [screenshots/2026-11-10-guardian-review-with-screenshot.png](screenshots/2026-11-10-guardian-review-with-screenshot.png) (judge mode: the guardian sees the transcribed text with the AI's quotes highlighted and the original screenshot beneath it).

## 2026-11-10 · Manual · Sender: IRS gift-card scam (live Gemini)

- **Run by:** Himani, in her browser.
- **Mode:** sandbox + Gemini, default database, 24-hour hold.
- **Steps:** Sender sends $500 to "Officer Collins" with the IRS gift-card message from demo scenario 1.
- **Expected:** High risk, on hold, evidence highlighted; AI summary shown.
- **Actual:** High risk, on hold. Reasons listed (gift cards, urgency, arrest threat, above the $300 limit, new payee) and "IRS", "gift cards", "within 30 minutes", "warrant", "arrest" highlighted. Banner: "AI check unavailable, rules only". The audit log shows the Gemini call **timed out after 8.1 s** (`gemini-3.1-flash-lite`), so the engine fell back to rules.
- **Verdict:** Pass for safety (the hard rule held the payment and the fallback was announced). The AI part did not run.
- **Follow-up:** Second live timeout from this model (the first was demo scenario 2 on Nov 9). The demo uses stored replies so the video is unaffected, but live use is degraded when the model is slow. Options were raised with Himani; she chose to raise the app timeout from 8 s to 12 s (Nov 10).
- **Screenshot:** [screenshots/2026-11-10-sender-irs-scam-held-ai-timeout.png](screenshots/2026-11-10-sender-irs-scam-held-ai-timeout.png)

## 2026-11-10 · Manual · Guardian activity grid after seeding

- **Run by:** Himani.
- **Mode:** sandbox + Gemini, default database.
- **Steps:** `scripts/reset_demo.py` on the default database, then opened I am the guardian → Activity.
- **Expected:** Margaret's 7 seeded past payments, totals row.
- **Actual:** 7 rows labelled "Past payment", All 7, totals "7 shown · $335.00 · Captured $335.00".
- **Verdict:** Pass.
- **Screenshot:** [screenshots/2026-11-10-activity-after-seeding.png](screenshots/2026-11-10-activity-after-seeding.png)

## 2026-11-10 · Manual · Guardian activity grid was empty

- **Run by:** Himani.
- **Mode:** backend restarted with the plain command (no `DATABASE_PATH`), so it used the empty default `data/safepay.db`.
- **Expected:** demo payments in the grid.
- **Actual:** every count 0, "No payments match this view".
- **Verdict:** Not a code bug (wrong database), but a usability gap: the empty state does not say the database has no payments or how to seed it.
- **Follow-up:** Improve the empty state to explain an empty database and point to `scripts/reset_demo.py`.
- **Screenshot:** [screenshots/2026-11-10-activity-empty-default-database.png](screenshots/2026-11-10-activity-empty-default-database.png)

## 2026-11-09 · Automated live runs (summary)

Recorded in the commit history and `docs/HANDOFF.md`; listed here so all live evidence is in one place.

| Run | Mode | Result |
|---|---|---|
| `scripts/sandbox_gate.py` | sandbox | create + authorize, read, capture, void all worked |
| `scripts/api_smoke.py` (2 runs) | sandbox (+ Gemini on the second) | every lane incl. hold timeout; 6/6 authorizations matched on PayPal each run |
| Three demo scenarios through the app's API | sandbox + Gemini | VOIDED / CAPTURED / VOIDED, matched on PayPal; scenario 2's AI call timed out once (rules fallback, still Medium) |
| `scripts/demo_rehearsal.py --runs 3 --standalone 3` | demo | all checks passed; 10/10 authorizations matched on PayPal |
| `scripts/demo_rehearsal.py` | judge (no keys) | all checks passed |
| Scenario 1 re-recorded without a brand name | demo | all checks passed; PayPal matched |
| `eval/run_eval.py` (live, then `--repeat 3`) | Gemini | hybrid 16/16, rules only 12/16, AI only 15/16; identical across 3 runs |
