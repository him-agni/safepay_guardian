# Test runs

A dated record of every manual test and live (real PayPal sandbox / real Gemini) run, with what was expected, what happened, and what changed because of it. Automated unit tests live in `backend/tests/` and `frontend/src/**/*.test.ts`; the risk-engine evaluation lives in `eval/`. This folder is for runs that a test suite cannot capture: a person using the app, or the real external services.

- [LOG.md](LOG.md): one entry per run, newest first.
- `screenshots/`: images referenced from the log, named `YYYY-MM-DD-what-it-shows.png`.

Each entry records: date, who ran it, mode (backend settings), steps, expected, actual, verdict, and follow-up.
