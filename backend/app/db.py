"""SQLite access: schema, connections and transactions.

All writes that decide a payment's fate go through `transaction()`, which takes SQLite's
write lock up front (BEGIN IMMEDIATE), so a status check and its update are atomic.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    role  TEXT NOT NULL CHECK (role IN ('sender', 'guardian'))
);

CREATE TABLE IF NOT EXISTS payees (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id      INTEGER NOT NULL REFERENCES users(id),
    name           TEXT NOT NULL,
    name_key       TEXT NOT NULL,
    email          TEXT,
    trusted        INTEGER NOT NULL DEFAULT 0,
    spending_limit_cents INTEGER,
    first_seen_at  TEXT NOT NULL,
    UNIQUE (sender_id, name_key)
);

CREATE TABLE IF NOT EXISTS payments (
    id                       TEXT PRIMARY KEY,
    sender_id                INTEGER NOT NULL REFERENCES users(id),
    payee_id                 INTEGER NOT NULL REFERENCES payees(id),
    amount_cents             INTEGER NOT NULL CHECK (amount_cents > 0),
    currency                 TEXT NOT NULL DEFAULT 'USD',
    note                     TEXT NOT NULL DEFAULT '',
    message_text             TEXT NOT NULL DEFAULT '',
    screenshot_path          TEXT,
    status                   TEXT NOT NULL,
    risk_level               TEXT,
    risk_score               INTEGER,
    risk_mode                TEXT,
    paypal_order_id          TEXT,
    paypal_authorization_id  TEXT,
    paypal_capture_id        TEXT,
    capture_attempt          INTEGER NOT NULL DEFAULT 1,
    void_attempt             INTEGER NOT NULL DEFAULT 1,
    last_error               TEXT,
    void_reason              TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    hold_expires_at          TEXT,
    decided_by               TEXT,
    decided_at               TEXT,
    decision_note            TEXT,
    is_seed                  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_created ON payments(created_at);

CREATE TABLE IF NOT EXISTS assessments (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id             TEXT REFERENCES payments(id),
    mode                   TEXT NOT NULL,
    final_level            TEXT NOT NULL,
    score                  INTEGER NOT NULL,
    summary                TEXT NOT NULL DEFAULT '',
    rules_json             TEXT NOT NULL DEFAULT '[]',
    ai_json                TEXT,
    dropped_evidence_json  TEXT NOT NULL DEFAULT '[]',
    patterns_json          TEXT NOT NULL DEFAULT '[]',
    evidence_json          TEXT NOT NULL DEFAULT '[]',
    ai_error               TEXT,
    components_json        TEXT NOT NULL DEFAULT '{}',
    model                  TEXT,
    latency_ms             INTEGER,
    created_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assessments_payment ON assessments(payment_id);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id   TEXT REFERENCES payments(id),
    at           TEXT NOT NULL,
    actor        TEXT NOT NULL CHECK (actor IN ('system', 'sender', 'guardian')),
    type         TEXT NOT NULL,
    detail_json  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_payment ON events(payment_id);

CREATE TABLE IF NOT EXISTS guardian_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id  TEXT NOT NULL REFERENCES payments(id),
    from_role   TEXT NOT NULL CHECK (from_role IN ('sender', 'guardian')),
    body        TEXT NOT NULL,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_payment ON guardian_messages(payment_id);

CREATE TABLE IF NOT EXISTS scam_patterns (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    category       TEXT NOT NULL,
    title          TEXT NOT NULL DEFAULT '',
    template_text  TEXT NOT NULL
);
"""

SENDER_ID = 1
GUARDIAN_ID = 2

SEED_USERS = [(SENDER_ID, "Margaret", "sender"), (GUARDIAN_ID, "Daniel", "guardian")]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """One timestamp format everywhere, so string comparison in SQL matches time order."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def iso_in(seconds: float, *, now: datetime | None = None) -> str:
    return iso((now or utcnow()) + timedelta(seconds=seconds))


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# Columns added after a table was first created: (table, column, definition).
ADDED_COLUMNS = [
    ("assessments", "components_json", "TEXT NOT NULL DEFAULT '{}'"),
]


def migrate(path: Path) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        for table, column, definition in ADDED_COLUMNS:
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.executemany("INSERT OR IGNORE INTO users (id, name, role) VALUES (?, ?, ?)", SEED_USERS)
    finally:
        conn.close()


def sync_scam_patterns(path: Path, patterns: list[tuple[str, str, str]]) -> None:
    """Mirror the in-code pattern library into the scam_patterns table (category, title, text)."""
    conn = connect(path)
    try:
        with transaction(conn):
            conn.execute("DELETE FROM scam_patterns")
            conn.executemany("INSERT INTO scam_patterns (category, title, template_text) VALUES (?, ?, ?)", patterns)
    finally:
        conn.close()


def add_event(
    conn: sqlite3.Connection, payment_id: str | None, actor: str, type_: str, detail: dict | None = None
) -> None:
    conn.execute(
        "INSERT INTO events (payment_id, at, actor, type, detail_json) VALUES (?, ?, ?, ?, ?)",
        (payment_id, iso(utcnow()), actor, type_, json.dumps(detail or {}, default=str)),
    )
