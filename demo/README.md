# Demo runbook

How to rehearse and record the three SafePay Guardian scenarios. The scenario text lives in [scenarios.json](scenarios.json); `scripts/demo_rehearsal.py` plays the same text through the API and checks every result on PayPal.

## What is in this folder

| File | Purpose |
|---|---|
| `scenarios.json` | The three scenarios: payee, amount, note, the message to paste, the expected level, and each click |
| `screenshots/` | `bank-fraud-team-text.png`, the made-up text thread uploaded in scenario 3 |
| `ai-cache/` | Gemini's replies to the three demo messages and to reading the scenario 3 screenshot, stored during rehearsal, so the recording never waits on the AI or its free-tier quota |

## 1. Start in demo mode

Two terminals, from the repo root. Demo mode uses its own database, a 2-minute hold (so a timeout can be shown), and the stored AI replies.

```bash
# Terminal 1: backend (real PayPal sandbox + Gemini from .env)
cd backend
AI_CACHE_DIR=demo/ai-cache DATABASE_PATH=data/demo.db HOLD_TIMEOUT_SECONDS=120 \
  ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000

# Terminal 2: frontend
cd frontend
npm run dev
```

Reset before every take (voids any open sandbox holds, clears payments, seeds Margaret's history):

```bash
DATABASE_PATH=data/demo.db .venv/Scripts/python scripts/reset_demo.py
```

Optional full rehearsal, checked against PayPal (about 30 seconds):

```bash
DATABASE_PATH=data/demo.db .venv/Scripts/python scripts/demo_rehearsal.py
```

After a rehearsal, reset again before recording.

## 2. Set up the screen

- Two browser windows side by side: left **Sender** at http://localhost:5173/#/send, right **Guardian** at http://localhost:5173/#/guardian.
- Zoom 110 to 125% so text reads on video. Close other tabs and notifications.
- Check http://localhost:5173/api/health shows `"paypal": {"mode": "sandbox", ...}` and `"ai": {..., "mode": "hybrid"}`.
- The "Sandbox: test money only" label is in the header: show it once on camera.

**Play the scenarios in order (1, 2, 3) after a reset.** The stored AI replies match that order exactly. Scenario 3 is also stored on its own, for a re-take of just that part (reset first). Anything else calls Gemini live, which usually takes 1 to 2 seconds but can exceed the 12-second limit; the app then falls back to rules and shows "AI check unavailable, rules only".

## 3. The scenarios

Seeded history: Margaret has paid Leo Martin (grandson, trusted), City Water Utility (trusted) and Sunrise Pharmacy before; a typical payment is about $50.

### Scenario 1: obvious scam (about 0:20 to 1:00 in the video)

Sender window, "Send money":

- Who are you paying? `Officer Collins`
- How much? `500`
- What is it for? *(leave empty)*
- Paste the message you received:

  > This is Officer Collins with the IRS. You owe $500 in back taxes. You must pay in gift cards within 30 minutes or a warrant will be issued for your arrest.

- Click **Send for check**.

Expected: **High risk**, "This payment is on hold", with "IRS", "gift cards", "within 30 minutes", "warrant" and "arrest" highlighted, and a "While you wait: staying safe" box whose first tip is about government agencies. Scroll past it briefly on camera.

Guardian window: the payment appears under "Waiting for you" within 3 seconds. Open it, point at the evidence (Hard rule: gift cards; AI: impersonation), type the note `This is a scam, Mum. The IRS never asks for gift cards. I'll call you tonight.` and click **Decline and void**.

Expected: guardian sees "Payment not captured, authorization voided." Sender's screen updates to "Declined by your guardian. No payment was taken." with the note.

Say: the payment was authorized on PayPal but never captured; the AI explained why; a person decided; the authorization was voided.

### Scenario 2: legitimate but unusual (about 1:00 to 1:35)

Sender window, **Send another payment**:

- Who: `Gutter Pros`
- How much: `350`
- What is it for? `deposit for gutter repair`
- Message:

  > Hi Margaret, this is Mike from Gutter Pros. As we discussed on Saturday, here is the invoice for the deposit on the gutter repair (invoice #1042 attached). We can start next Tuesday. Thanks!

- **Send for check**.

Expected: **Medium risk**, "Please check this payment before it is sent", reasons: above the $300 limit, new payee. Nothing highlighted in the message. Click **Yes, send it**, then "Payment completed."

Say: the system also knows when not to interrupt. No guardian was needed.

### Scenario 3: contextual scam with no keywords, from a screenshot (about 1:35 to 2:15)

Sender window:

- Who: `Secure Holdings LLC`
- How much: `300`
- What is it for? *(leave empty)*
- Under the message box, click **Add a screenshot instead** and choose `demo/screenshots/bank-fraud-team-text.png` (a made-up text thread from a fictional 555 number).
- Wait for "We read 3 messages from +1 (555) 014-2290 and put them in the box below (we left out your own replies)". Point at the box: the AI copied the scammer's words exactly, and the sender checks them.
- **Send for check**.

If the screenshot cannot be read (the AI is busy), paste this text instead; it has a stored reply too:

  > Good afternoon, this is Daniel from the Fraud Prevention Team at your bank. We noticed unusual sign-in activity on your account. As a precaution, please move $300 to the protected account our security team has set up in your name: Secure Holdings LLC. We will return it once the review is complete. Thank you for your cooperation.

Expected: **High risk**, held. The highlighted words come from the AI ("move $300 to the protected account", "Daniel from the Fraud Prevention Team at your bank"). The rules alone would only have warned.

Guardian window: open it. Show the screenshot next to the transcribed text, then the evidence labelled **AI** and "Similar known scam pattern: Bank fraud team asks to move money to a safe account". Under **Ask the payer**, click the suggestion `Did you speak to this person on the phone?` and **Send**.

Sender window: the question appears under "Reply to your guardian". Type `No, it was a text message. It said it was from my bank.` and **Send**.

Guardian window: the reply appears. Note `Banks never ask you to move money. Please call the number on the back of your card.` and **Decline and void**.

Say: no scam keywords, yet the AI linked the message to the payment and flagged the impersonation. A human made the final call.

### Closing shots (about 2:15 to 3:00)

- Guardian **Activity** tab: the grid with all three outcomes. Click the example question **High-risk payments that I declined**: the AI turns it into the chips "Risk is High" and "Decision is Declined" and the grid filters itself (stored reply, so it is instant). Say: it only filters the view; it can never approve or decline.
- Guardian **Insights** tab: "Attempted payments held from capture", then scroll past the charts: today's column shows stopped and still-open payments next to the captured history, and the recipient chart names the payee who was flagged.
- The evaluation: [eval/results.md](../eval/results.md) (16 cases: rules only 12/16, AI only 15/16, hybrid 16/16) and the held-out set [eval/results_heldout.md](../eval/results_heldout.md) (69 cases never used for tuning, including real scam texts: every scam at least warned, 96% held, no legitimate payment held).
- Say "PayPal" and "AI" out loud. Closing line: sandbox only; a decision aid with a human in charge.

## Without PayPal or Gemini keys (judges)

Replay mode serves the stored replies for these three messages with no API key, and the fake PayPal needs no credentials:

```bash
cd backend
PAYPAL_MODE=fake AI_PROVIDER=replay AI_CACHE_DIR=demo/ai-cache DATABASE_PATH=data/judge.db \
  ../.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000
# then, from the repo root:
PAYPAL_MODE=fake DATABASE_PATH=data/judge.db .venv/Scripts/python scripts/reset_demo.py
```

Any other message is checked by the rules alone, and the screen says "AI check unavailable, rules only". The guardian's review labels replayed answers "(stored reply)".
