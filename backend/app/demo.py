"""Demo data: Margaret's payment history and trusted payees, and a reset that keeps PayPal tidy.

The seeded history makes the rules meaningful on screen: a typical payment is about $50, Leo (her grandson)
and the water utility are trusted, so "new payee" and "larger than usual" have something to compare with.
Seeded rows are marked `is_seed` and excluded from the Insights numbers.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from . import db
from .paypal import GatewayError, PaymentGateway

# (name, trusted)
SEED_PAYEES = [
    ("Leo Martin", True),  # grandson
    ("City Water Utility", True),
    ("Sunrise Pharmacy", False),
]

# (payee, amount in cents, note, days ago)
SEED_PAYMENTS = [
    ("City Water Utility", 6000, "monthly water bill", 28),
    ("Leo Martin", 3500, "birthday gift", 26),
    ("Sunrise Pharmacy", 4500, "prescriptions", 20),
    ("City Water Utility", 6000, "monthly water bill", 14),
    ("Leo Martin", 5000, "books for school", 9),
    ("Sunrise Pharmacy", 2500, "prescriptions", 5),
    ("City Water Utility", 6000, "monthly water bill", 1),
]

# Payments whose PayPal authorization may still be open.
LIVE_STATUSES = ("AUTHORIZED", "WARNED", "HELD", "CAPTURING", "VOIDING", "CAPTURE_FAILED", "VOID_FAILED")


def void_open_authorizations(db_path: Path, gateway: PaymentGateway) -> dict:
    """Void every authorization the demo left open, so resetting never strands a sandbox hold."""
    db.migrate(db_path)
    conn = db.connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT id, paypal_authorization_id FROM payments WHERE is_seed = 0 "
            f"AND paypal_authorization_id IS NOT NULL AND status IN ({','.join('?' * len(LIVE_STATUSES))})",
            LIVE_STATUSES,
        ).fetchall()
    finally:
        conn.close()
    voided, failed = [], []
    for row in rows:
        try:
            status = gateway.get_authorization(row["paypal_authorization_id"]).status
            if status in ("CREATED", "PENDING"):
                gateway.void(row["paypal_authorization_id"], request_id=f"{row['id']}-void-reset")
            voided.append(row["paypal_authorization_id"])
        except GatewayError as exc:
            failed.append(f"{row['paypal_authorization_id']}: {exc.message}")
    return {"voided": voided, "failed": failed}


class ResetBlocked(Exception):
    """Some open sandbox authorizations could not be voided, so the records of them were kept."""

    def __init__(self, failures: list[str]) -> None:
        super().__init__("; ".join(failures))
        self.failures = failures


def reset_safely(db_path: Path, gateway: PaymentGateway | None, *, force: bool = False) -> dict:
    """Void open authorizations, then reset. If a void fails, stop before deleting: the payment records are the
    only way to find those authorizations again. `force` deletes anyway (for a database of unusable records)."""
    result = {"voided": [], "failed": []}
    if gateway is not None:
        result = void_open_authorizations(db_path, gateway)
        if result["failed"] and not force:
            raise ResetBlocked(result["failed"])
    return {**reset(db_path), **result}


def reset(db_path: Path) -> dict:
    """Clear every payment, payee, assessment, event and message, then seed the demo history."""
    db.migrate(db_path)
    conn = db.connect(db_path)
    now = db.utcnow()
    try:
        with db.transaction(conn):
            for table in ("guardian_messages", "events", "assessments", "payments", "payees"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('payees', 'events', 'assessments', "
                         "'guardian_messages')")
            payee_ids = {}
            for name, trusted in SEED_PAYEES:
                cur = conn.execute(
                    "INSERT INTO payees (sender_id, name, name_key, trusted, first_seen_at) VALUES (?, ?, ?, ?, ?)",
                    (db.SENDER_ID, name, name.lower(), int(trusted), db.iso(now - timedelta(days=90))),
                )
                payee_ids[name] = cur.lastrowid
            for i, (payee, cents, note, days_ago) in enumerate(SEED_PAYMENTS, start=1):
                at = db.iso(now - timedelta(days=days_ago, hours=3))
                pid = f"seed{i:02d}"
                conn.execute(
                    """INSERT INTO payments (id, sender_id, payee_id, amount_cents, currency, note, status, risk_level,
                           risk_score, risk_mode, paypal_order_id, paypal_authorization_id, paypal_capture_id,
                           created_at, updated_at, is_seed)
                       VALUES (?, ?, ?, ?, 'USD', ?, 'CAPTURED', 'low', 0, 'rules_only', ?, ?, ?, ?, ?, 1)""",
                    (pid, db.SENDER_ID, payee_ids[payee], cents, note, f"SEED-ORDER-{i:02d}", f"SEED-AUTH-{i:02d}",
                     f"SEED-CAPTURE-{i:02d}", at, at),
                )
                db.add_event(conn, pid, "system", "seed.history",
                             {"note": "Seeded past payment for the demo; no PayPal call was made."})
    finally:
        conn.close()
    return {"payees": len(SEED_PAYEES), "past_payments": len(SEED_PAYMENTS)}
