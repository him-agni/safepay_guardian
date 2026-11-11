"""Pressing Send twice must not make two payments.

The browser sends one Idempotency-Key per intended payment. If the answer is lost and the sender sends again,
the server returns the first payment instead of creating and authorizing another.
"""

from __future__ import annotations

import threading

from app.paypal import GatewayError

KEY = "3f2b6c1e-9a4d-4e7a-8c55-0d1f6a9b2e10"
BODY = {"payee_name": "Gutter Pros", "amount": "350.00", "message_text": "Deposit for the job"}


def post(env, body=None, key=KEY):
    headers = {"Idempotency-Key": key} if key else {}
    return env.client.post("/payments", json=body or BODY, headers=headers)


def payments(env) -> list:
    return env.client.get("/payments").json()["payments"]


def test_sending_the_same_payment_twice_returns_the_first_one(env):
    env.risk.level = "high"
    first = post(env)
    second = post(env)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json()["id"] == first.json()["id"]
    assert len(payments(env)) == 1
    assert len(env.paypal.authorizations) == 1
    assert [op for op, _ in env.paypal.calls].count("create") == 1
    assert "payment.create_replayed" in env.event_types(first.json()["id"])


def test_the_replay_shows_the_payment_as_it_is_now(env):
    env.risk.level = "high"
    first = post(env).json()
    env.act(first["id"], "decline")

    again = post(env)
    assert again.status_code == 200
    assert again.json()["status"] == "VOIDED"  # not a fresh payment, not the old HELD snapshot


def test_without_a_key_each_request_is_its_own_payment(env):
    env.risk.level = "high"
    post(env, key=None)
    post(env, key=None)
    assert len(payments(env)) == 2


def test_a_new_key_is_a_new_intended_payment_even_with_the_same_details(env):
    env.risk.level = "high"
    post(env, key="aaaaaaaa-1111")
    post(env, key="bbbbbbbb-2222")
    assert len(payments(env)) == 2


def test_the_same_key_with_different_details_is_refused(env):
    env.risk.level = "high"
    first = post(env)
    changed = post(env, body={**BODY, "amount": "3500.00"})

    assert changed.status_code == 409
    assert "different payment" in changed.json()["message"]
    assert len(payments(env)) == 1
    assert payments(env)[0]["id"] == first.json()["id"]


def test_a_badly_formed_key_is_rejected(env):
    assert post(env, key="short").status_code == 422
    assert post(env, key="has spaces in it!").status_code == 422
    assert payments(env) == []


def test_replaying_while_paypal_has_not_answered_does_not_authorize_again(env):
    for _ in range(3):
        env.paypal.inject("create", GatewayError("network", "create order failed: ReadTimeout"))
    first = post(env)
    assert first.json()["status"] == "CREATED"
    creates_before = [op for op, _ in env.paypal.calls].count("create")

    second = post(env)
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]
    assert [op for op, _ in env.paypal.calls].count("create") == creates_before


def test_simultaneous_requests_with_one_key_make_one_payment(env):
    env.risk.level = "high"
    results: list = []
    errors: list = []

    def send():
        try:
            results.append(env.service.create_or_replay(
                payee_name="Gutter Pros", amount_cents=35000, message_text="Deposit for the job",
                idempotency_key=KEY))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=send) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len({payment["id"] for payment, _ in results}) == 1
    assert sum(1 for _, replayed in results if not replayed) == 1
    assert len(payments(env)) == 1
    assert len(env.paypal.authorizations) == 1


def test_an_existing_database_gains_the_key_columns_and_keeps_its_payments(tmp_path):
    from app import db

    path = tmp_path / "old.db"
    conn = db.connect(path)
    conn.executescript(db.SCHEMA)  # the schema before keys existed: no key columns yet
    conn.executemany("INSERT OR IGNORE INTO users (id, name, role) VALUES (?, ?, ?)", db.SEED_USERS)
    conn.execute("INSERT INTO payees (id, sender_id, name, name_key, first_seen_at) VALUES (1, 1, 'A', 'a', 't')")
    for pid in ("old-1", "old-2"):
        conn.execute(
            "INSERT INTO payments (id, sender_id, payee_id, amount_cents, currency, status, risk_level, "
            "risk_score, risk_mode, created_at, updated_at) VALUES (?, 1, 1, 500, 'USD', 'CAPTURED', 'low', 0, "
            "'rules_only', 't', 't')", (pid,))
    conn.commit()
    conn.close()

    db.migrate(path)
    db.migrate(path)  # running it again is harmless

    conn = db.connect(path)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(payments)")}
    assert {"idempotency_key", "request_fingerprint"} <= columns
    # many old payments with no key do not clash with each other
    assert conn.execute("SELECT COUNT(*) FROM payments WHERE idempotency_key IS NULL").fetchone()[0] == 2
    conn.close()
