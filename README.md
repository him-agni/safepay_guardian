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
../.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cp .env.example .env
cd backend
../.venv/bin/python -m uvicorn app.main:app --port 8000
```

Then open http://localhost:8000/health.

With no `.env` values the app uses a fake in-process PayPal and the rules-only risk engine, so it runs without any credentials.

Run the tests:

```bash
cd backend
../.venv/Scripts/python -m pytest -q     # or ../.venv/bin/python on macOS/Linux
```

## Honest limits

- All money is PayPal sandbox test money. In the sandbox every payment settles to one sandbox merchant account; the payee name is a label.
- The risk level is a decision aid, not a validated fraud probability.
- There is no real login: a toggle switches between the sender and guardian views.
- This is a demo of a protection workflow, not a certified fraud-prevention product.

## License

MIT, see [LICENSE](LICENSE).
