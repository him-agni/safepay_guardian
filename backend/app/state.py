"""Payment state machine.

Rules this module enforces:
  * A payment is claimed (moved to CAPTURING or VOIDING) inside one SQLite write transaction
    before any PayPal call, so concurrent decisions cannot both act: the first valid change wins.
  * The authorization is read from PayPal before every capture and void. If PayPal already shows
    it captured, voided or expired, we record that instead of calling again.
  * PayPal-Request-Ids are deterministic ({payment_id}-capture-{attempt}). Network and 5xx retries
    reuse the id; only a definite 4xx rejection moves to the next attempt number.
  * Silence fails safe: WARNED, HELD and CAPTURE_FAILED payments are voided when the hold expires. The
    deadline is also checked inside the same transaction that claims a capture, so an approval that
    arrives after it cannot capture even if the sweeper has not run yet.
  * A payment is CAPTURED only when PayPal says the capture is settled (COMPLETED). A PENDING capture is
    CAPTURE_PENDING and is re-read until it settles; DECLINED or FAILED goes to CAPTURE_FAILED.
  * An authorization PayPal never answered (timeout, 5xx) is not a failure: PayPal may have authorized it.
    The payment stays CREATED and the sweeper retries with the same request id, which returns the same
    order, until auth_give_up_seconds. Only a definite refusal (4xx) fails it straight away.
  * Every state change and every PayPal call writes a row to `events` (the audit log).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from . import db
from .config import Settings
from .paypal import (CAPTURE_DONE, CAPTURE_REJECTED, USABLE_AUTH_STATUSES, GatewayError, PaymentGateway,
                     format_amount, request_id)
from .risk import ai as ai_mod
from .risk.types import Assessor, PaymentContext, RiskResult

T = TypeVar("T")


class Status(str, Enum):
    CREATED = "CREATED"
    AUTH_FAILED = "AUTH_FAILED"
    AUTHORIZED = "AUTHORIZED"
    WARNED = "WARNED"
    HELD = "HELD"
    CAPTURING = "CAPTURING"
    VOIDING = "VOIDING"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    CAPTURE_PENDING = "CAPTURE_PENDING"
    VOID_FAILED = "VOID_FAILED"


S = Status
TERMINAL = frozenset({S.CAPTURED, S.VOIDED, S.EXPIRED, S.AUTH_FAILED})
TIMEOUT_VOIDABLE = frozenset({S.WARNED, S.HELD, S.CAPTURE_FAILED})
GUARDIAN_QUEUE = (S.HELD, S.CAPTURE_FAILED, S.CAPTURE_PENDING, S.VOID_FAILED, S.CAPTURING, S.VOIDING)


class PaymentError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, payment: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.payment = payment


class NotFound(PaymentError):
    status_code = 404
    code = "not_found"


class Conflict(PaymentError):
    status_code = 409
    code = "conflict"


class Invalid(PaymentError):
    status_code = 422
    code = "invalid"


# Screenshots are stored under a content fingerprint, so a name can never point outside the upload folder.
SCREENSHOT_ID = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp)$")
SCREENSHOT_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
SCREENSHOT_MEDIA = {ext: mime for mime, ext in SCREENSHOT_TYPES.items()}


def _looks_like(ext: str, data: bytes) -> bool:
    if ext == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == "jpg":
        return data.startswith(b"\xff\xd8\xff")
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


SCREENSHOT_HELP = {
    "not_configured": "We can't read screenshots right now. Please type or paste the message instead.",
    "no_messages": "We couldn't find any messages in that picture. Please check it is a screenshot of the "
                   "conversation, or type the message instead.",
}
SCREENSHOT_RETRY = ("We couldn't read the screenshot just now. Please type or paste the message instead, "
                    "or try again in a moment.")


@dataclass(frozen=True)
class Action:
    name: str
    actor: str  # default actor: system, sender or guardian
    kind: str  # "capture" or "void"
    allowed_from: frozenset
    void_reason: str | None = None
    records_decision: bool = True
    enforces_deadline: bool = False  # a capture that comes after the hold deadline is refused


ACTIONS = {
    a.name: a
    for a in (
        Action("auto_capture", "system", "capture", frozenset({S.AUTHORIZED}), records_decision=False),
        Action("confirm", "sender", "capture", frozenset({S.WARNED}), enforces_deadline=True),
        Action("approve", "guardian", "capture", frozenset({S.HELD}), enforces_deadline=True),
        Action("retry_capture", "guardian", "capture", frozenset({S.CAPTURE_FAILED}), records_decision=False,
               enforces_deadline=True),
        Action("cancel", "sender", "void", frozenset({S.WARNED, S.HELD}), void_reason="sender_cancel"),
        Action("decline", "guardian", "void", frozenset({S.HELD, S.CAPTURE_FAILED}),
               void_reason="guardian_decline"),
        Action("timeout", "system", "void", TIMEOUT_VOIDABLE, void_reason="timeout"),
        Action("retry_void", "guardian", "void", frozenset({S.VOID_FAILED}), records_decision=False),
    )
}

VERB = {
    "confirm": "confirm", "approve": "approve", "retry_capture": "retry", "cancel": "cancel",
    "decline": "decline", "timeout": "expire", "retry_void": "retry", "auto_capture": "capture",
}


# --------------------------------------------------------------------------------------
# Plain-language status text (sender wording and guardian wording differ on purpose)
# --------------------------------------------------------------------------------------

def status_text(status: str, void_reason: str | None) -> dict:
    sender = {
        S.CREATED: "Starting your payment...",
        S.AUTHORIZED: "Checking your payment...",
        S.CAPTURING: "Sending your payment...",
        S.CAPTURED: "Payment completed.",
        S.WARNED: "Please check this payment before it is sent.",
        S.HELD: "This payment is on hold. Your guardian was asked to review it.",
        S.VOIDING: "Stopping this payment. It will not be sent.",
        S.VOID_FAILED: "This payment is stopped and will not be sent.",
        S.CAPTURE_FAILED: "Your guardian approved this payment, but it has not gone through yet.",
        S.CAPTURE_PENDING: "Your payment was sent and PayPal is still confirming it. This page will update.",
        S.AUTH_FAILED: "The payment could not be started. No payment was taken.",
        S.EXPIRED: "Not sent. Nobody reviewed it in time, so it was declined. No payment was taken.",
        S.VOIDED: {
            "sender_cancel": "You cancelled this payment. No payment was taken.",
            "guardian_decline": "Declined by your guardian. No payment was taken.",
        }.get(void_reason or "", "Declined. No payment was taken."),
    }
    guardian = {
        S.CREATED: "Starting authorization.",
        S.AUTHORIZED: "Authorized, deciding the next step.",
        S.CAPTURING: "Capturing the payment.",
        S.CAPTURED: "Payment captured.",
        S.WARNED: "The sender was warned and has not confirmed yet.",
        S.HELD: "On hold: waiting for your decision.",
        S.VOIDING: "Voiding the authorization.",
        S.VOID_FAILED: "The void failed and will be retried. The payment will not be captured.",
        S.CAPTURE_FAILED: "Capture failed. You can retry or decline.",
        S.CAPTURE_PENDING: "Capture requested. PayPal still shows it as pending, so it is not final yet.",
        S.AUTH_FAILED: "Card authorization failed. Nothing to capture or void.",
        S.EXPIRED: "No decision before the hold timed out. Payment not captured, authorization voided.",
        S.VOIDED: "Payment not captured, authorization voided."
        + {"sender_cancel": " The sender cancelled it.", "guardian_decline": " You declined it."}.get(
            void_reason or "", ""),
    }
    st = S(status)
    return {"sender": sender[st], "guardian": guardian[st]}


def _fingerprint(payee_name: str, amount_cents: int, currency: str, note: str, message_text: str,
                 screenshot_id: str | None, payee_email: str | None) -> str:
    """What makes two submissions 'the same payment': every field the sender chose."""
    parts = {"payee": " ".join(payee_name.split()).lower(), "amount_cents": amount_cents, "currency": currency,
             "note": note, "message": message_text, "screenshot": screenshot_id, "email": payee_email}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def _status_text_for(status: Status, row: sqlite3.Row) -> dict:
    text = status_text(status.value, row["void_reason"])
    if status == S.CREATED and row["last_error"]:
        text["sender"] = ("PayPal is taking longer than usual to answer. We are still trying. "
                          "Nothing has been sent.")
        text["guardian"] = "PayPal has not answered the authorization yet. It is retried with the same request id."
    return text


def _hold_expired(row: sqlite3.Row) -> bool:
    """True once a hold has run past its deadline (the sweeper may not have voided it yet)."""
    expires = row["hold_expires_at"]
    return bool(expires) and db.parse_iso(expires) <= db.utcnow()


def _conflict_reason(row: sqlite3.Row) -> str:
    status = S(row["status"])
    if status == S.VOIDED:
        return {
            "sender_cancel": "it was already cancelled by the sender",
            "guardian_decline": "it was already declined by the guardian",
        }.get(row["void_reason"] or "", "it was already voided")
    return {
        S.CAPTURED: "it was already approved and captured",
        S.EXPIRED: "the hold already expired and the authorization was voided",
        S.AUTH_FAILED: "the card authorization failed, so there is nothing to decide",
        S.WARNED: "it is waiting for the sender to confirm a warning",
        S.HELD: "it is on hold for the guardian, and only the guardian can approve it",
        S.CAPTURING: "it is being captured right now",
        S.VOIDING: "it is being voided right now",
        S.VOID_FAILED: "it is being voided (the last void attempt failed and will be retried)",
        S.CAPTURE_FAILED: "the guardian approved it and the capture can only be retried or declined",
        S.CAPTURE_PENDING: "PayPal is still confirming the capture, so it can no longer be changed",
        S.CREATED: "it is still being authorized",
        S.AUTHORIZED: "it is still being routed",
    }[status]


# --------------------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------------------

class PaymentService:
    def __init__(self, settings: Settings, gateway: PaymentGateway, assessor: Assessor) -> None:
        self.settings = settings
        self.gateway = gateway
        self.assessor = assessor
        self.db_path = settings.database_file
        self._sweep_lock = threading.Lock()
        db.migrate(self.db_path)
        from .risk.patterns import PATTERNS

        db.sync_scam_patterns(self.db_path, [(p.category, p.title, p.text) for p in PATTERNS])

    # ---------------------------------------------------------------- db helpers

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = db.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _row(self, conn: sqlite3.Connection, payment_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if row is None:
            raise NotFound(f"Payment {payment_id} not found.")
        return row

    def _event(self, payment_id: str | None, actor: str, type_: str, detail: dict | None = None) -> None:
        with self._conn() as conn:
            db.add_event(conn, payment_id, actor, type_, detail)

    def _transition(
        self,
        payment_id: str,
        from_statuses: frozenset | set | tuple,
        to: Status,
        actor: str,
        fields: dict | None = None,
        event: tuple[str, dict] | None = None,
        guard: Callable[[sqlite3.Row], bool] | None = None,
    ) -> tuple[bool, sqlite3.Row]:
        """Atomically move a payment from one of `from_statuses` to `to`.

        `guard`, if given, is checked on the row inside the same transaction; if it says no, nothing changes.
        Returns (True, row_before) if this call made the change, or (False, current_row).
        """
        with self._conn() as conn, db.transaction(conn):
            row = self._row(conn, payment_id)
            if S(row["status"]) not in from_statuses:
                return False, row
            if guard is not None and not guard(row):
                return False, row
            values = {"status": to.value, "updated_at": db.iso(db.utcnow()), **(fields or {})}
            assignments = ", ".join(f"{k} = ?" for k in values)
            conn.execute(f"UPDATE payments SET {assignments} WHERE id = ?", (*values.values(), payment_id))
            db.add_event(conn, payment_id, actor, "status.changed", {"from": row["status"], "to": to.value})
            if event:
                db.add_event(conn, payment_id, actor, event[0], event[1])
            return True, row

    def _with_retry(self, fn: Callable[[], T]) -> T:
        """Retry network and 5xx failures with the same request id; never retry a 4xx."""
        attempts = 3
        for i in range(attempts):
            try:
                return fn()
            except GatewayError as exc:
                if not exc.retry_same_id or i == attempts - 1:
                    raise
                time.sleep(self.settings.paypal_retry_backoff_seconds * (2**i))
        raise AssertionError("unreachable")  # pragma: no cover

    # ---------------------------------------------------------------- create

    def create_payment(self, **kwargs) -> dict:
        return self.create_or_replay(**kwargs)[0]

    def create_or_replay(
        self, *, payee_name: str, amount_cents: int, note: str = "", message_text: str = "",
        payee_email: str | None = None, currency: str = "USD", screenshot_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict, bool]:
        """Create a payment, or, if this submission key was already used for the same details, return the first
        payment again. Returns (payment, replayed).

        The browser sends one key per intended payment. If the answer is lost and the sender presses Send
        again, the second request finds the first payment instead of creating and authorizing another.
        The same key with different details is refused: it is a mistake, not a retry.
        """
        fingerprint = _fingerprint(payee_name, amount_cents, currency, note, message_text, screenshot_id,
                                   payee_email)
        if idempotency_key:
            existing = self._find_by_key(idempotency_key)
            if existing is not None:
                return self._replay(existing, fingerprint, idempotency_key), True
        if screenshot_id is not None:
            self.screenshot_file(screenshot_id, invalid=True)
        payee, ctx = self._build_context(payee_name, amount_cents, note, message_text, currency=currency,
                                         payee_email=payee_email, create_payee=True)
        name = ctx.payee_name
        risk = self.assessor.assess(ctx)  # outside any transaction: the AI call can take seconds

        payment_id = uuid.uuid4().hex
        try:
            with self._conn() as conn, db.transaction(conn):
                ts = db.iso(db.utcnow())
                conn.execute(
                    """INSERT INTO payments (id, sender_id, payee_id, amount_cents, currency, note, message_text,
                           screenshot_path, status, risk_level, risk_score, risk_mode, created_at, updated_at,
                           idempotency_key, request_fingerprint)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (payment_id, db.SENDER_ID, payee["id"], amount_cents, currency, note, message_text,
                     screenshot_id, S.CREATED.value, risk.level, risk.score, risk.mode, ts, ts,
                     idempotency_key or None, fingerprint),
                )
                self._insert_assessment(conn, payment_id, risk)
                db.add_event(conn, payment_id, "sender", "payment.created", {
                    "amount": format_amount(amount_cents), "currency": currency, "payee": name,
                    "payee_is_new": ctx.payee_is_new, "payee_trusted": ctx.payee_trusted,
                    "screenshot": screenshot_id is not None, "idempotent": bool(idempotency_key),
                })
                db.add_event(conn, payment_id, "system", "risk.assessed", {
                    "level": risk.level, "score": risk.score, "mode": risk.mode,
                    "indicators": [i["type"] for i in risk.indicators],
                    "dropped_evidence": risk.dropped_evidence,  # AI quotes not found in the input: logged only
                    "patterns": [p["id"] for p in risk.patterns],
                    "ai_error": risk.ai_error, "model": risk.model, "latency_ms": risk.latency_ms,
                })
        except sqlite3.IntegrityError:
            # two requests with the same key raced: the other one inserted first, so this one is the retry
            existing = self._find_by_key(idempotency_key) if idempotency_key else None
            if existing is None:
                raise
            return self._replay(existing, fingerprint, idempotency_key), True

        self._authorize_and_route(payment_id)
        return self.get_payment(payment_id), False

    def _find_by_key(self, key: str) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute(
                "SELECT id, request_fingerprint FROM payments WHERE sender_id = ? AND idempotency_key = ?",
                (db.SENDER_ID, key),
            ).fetchone()

    def _replay(self, existing: sqlite3.Row, fingerprint: str, key: str) -> dict:
        if existing["request_fingerprint"] != fingerprint:
            raise Conflict("That submission was already used for a different payment. "
                           "Please check the details and send again.")
        self._event(existing["id"], "sender", "payment.create_replayed", {"idempotency_key": key})
        return self.get_payment(existing["id"])

    def _build_context(
        self, payee_name: str, amount_cents: int, note: str, message_text: str, *, currency: str = "USD",
        payee_email: str | None = None, create_payee: bool,
    ) -> tuple[sqlite3.Row | None, PaymentContext]:
        """Look up the payee and the sender's history, creating the payee row only for real payments."""
        name = " ".join(payee_name.split())
        with self._conn() as conn:
            payee = None
            if name:
                with db.transaction(conn):
                    payee = conn.execute(
                        "SELECT * FROM payees WHERE sender_id = ? AND name_key = ?", (db.SENDER_ID, name.lower())
                    ).fetchone()
                    if payee is None and create_payee:
                        cur = conn.execute(
                            "INSERT INTO payees (sender_id, name, name_key, email, first_seen_at) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (db.SENDER_ID, name, name.lower(), payee_email, db.iso(db.utcnow())),
                        )
                        payee = conn.execute("SELECT * FROM payees WHERE id = ?", (cur.lastrowid,)).fetchone()
            history = [
                r["amount_cents"]
                for r in conn.execute(
                    "SELECT amount_cents FROM payments WHERE sender_id = ? AND status = 'CAPTURED'", (db.SENDER_ID,)
                )
            ]
            payee_count = 0
            if payee is not None:
                payee_count = conn.execute(
                    "SELECT COUNT(*) FROM payments WHERE payee_id = ? AND status = 'CAPTURED'", (payee["id"],)
                ).fetchone()[0]
        trusted = bool(payee["trusted"]) if payee is not None else False
        ctx = PaymentContext(
            amount_cents=amount_cents, currency=currency, payee_name=name,
            payee_is_new=bool(name) and payee_count == 0 and not trusted, payee_trusted=trusted,
            note=note, message_text=message_text, history_amounts_cents=history,
            payee_history_count=payee_count,
            payee_spending_limit_cents=payee["spending_limit_cents"] if payee is not None else None,
        )
        return payee, ctx

    def assess_only(self, *, message_text: str, note: str = "", amount_cents: int = 0,
                    payee_name: str = "") -> dict:
        """Run the risk engine without creating a payment (demo box and evaluation)."""
        _, ctx = self._build_context(payee_name, amount_cents, note, message_text, create_payee=False)
        risk = self.assessor.assess(ctx)
        self._event(None, "system", "risk.assessed_text_only", {
            "level": risk.level, "mode": risk.mode, "dropped_evidence": risk.dropped_evidence,
        })
        return _serialize_risk(risk)

    @staticmethod
    def _insert_assessment(conn: sqlite3.Connection, payment_id: str | None, risk: RiskResult) -> None:
        conn.execute(
            """INSERT INTO assessments (payment_id, mode, final_level, score, summary, rules_json, ai_json,
                   dropped_evidence_json, patterns_json, evidence_json, ai_error, components_json, model,
                   latency_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (payment_id, risk.mode, risk.level, risk.score, risk.summary, json.dumps(risk.rules),
             json.dumps(risk.ai) if risk.ai is not None else None, json.dumps(risk.dropped_evidence),
             json.dumps(risk.patterns), json.dumps({"indicators": risk.indicators, "spans": risk.evidence_spans}),
             risk.ai_error, json.dumps(risk.components), risk.model, risk.latency_ms, db.iso(db.utcnow())),
        )

    def _authorize_and_route(self, payment_id: str) -> None:
        with self._conn() as conn:
            row = self._row(conn, payment_id)
            payee = conn.execute("SELECT name FROM payees WHERE id = ?", (row["payee_id"],)).fetchone()
        try:
            order = self._with_retry(lambda: self.gateway.create_authorized_order(
                payment_id=payment_id, amount_cents=row["amount_cents"], currency=row["currency"],
                description=f"SafePay Guardian payment to {payee['name']}",
            ))
        except GatewayError as exc:
            if exc.kind == "client":  # PayPal said no: a definite answer
                self._transition(payment_id, {S.CREATED}, S.AUTH_FAILED, "system",
                                 {"last_error": exc.message}, ("paypal.authorization_failed", exc.as_detail()))
            else:  # no answer: PayPal may or may not have authorized it
                self._authorization_unsure(payment_id, row, exc)
            return
        claimed, _ = self._transition(
            payment_id, {S.CREATED}, S.AUTHORIZED, "system",
            {"paypal_order_id": order.order_id, "paypal_authorization_id": order.authorization_id,
             "hold_expires_at": db.iso_in(self.settings.hold_timeout_seconds)},
            ("paypal.authorized", {"order_id": order.order_id, "authorization_id": order.authorization_id,
                                   "authorization_status": order.authorization_status,
                                   "request_id": request_id(payment_id, "create"),
                                   "paypal_debug_id": order.debug_id}),
        )
        if claimed:  # a second resume of the same payment must not route it again
            self._route(payment_id)

    def _authorization_unsure(self, payment_id: str, row: sqlite3.Row, exc: GatewayError) -> None:
        """PayPal did not answer. Keep the payment CREATED so the same request id is tried again; give up late."""
        age = (db.utcnow() - db.parse_iso(row["created_at"])).total_seconds()
        if age >= self.settings.auth_give_up_seconds:
            self._transition(
                payment_id, {S.CREATED}, S.AUTH_FAILED, "system",
                {"last_error": f"PayPal did not answer in time ({exc.message}). If it reserved an amount, "
                               "that reservation expires by itself."},
                ("paypal.authorization_gave_up", {**exc.as_detail(), "seconds": int(age)}))
            return
        with self._conn() as conn, db.transaction(conn):
            conn.execute("UPDATE payments SET updated_at = ?, last_error = ? WHERE id = ? AND status = 'CREATED'",
                         (db.iso(db.utcnow()), exc.message, payment_id))
            db.add_event(conn, payment_id, "system", "paypal.authorization_uncertain",
                         {**exc.as_detail(), "retry_with_same_request_id": request_id(payment_id, "create")})

    def _route(self, payment_id: str) -> None:
        with self._conn() as conn:
            level = self._row(conn, payment_id)["risk_level"]
        if level == "low":
            self._decide(payment_id, ACTIONS["auto_capture"])
        elif level == "medium":
            self._transition(payment_id, {S.AUTHORIZED}, S.WARNED, "system",
                             event=("hold.warned", {"reason": "medium risk: sender must confirm"}))
        else:
            self._transition(payment_id, {S.AUTHORIZED}, S.HELD, "system",
                             event=("hold.placed", {"reason": "high risk: guardian must decide"}))

    # ---------------------------------------------------------------- decisions

    def act(self, payment_id: str, action_name: str, *, note: str | None = None) -> dict:
        """Public entry for sender and guardian actions (confirm, cancel, approve, decline, retry)."""
        if action_name == "retry":
            with self._conn() as conn:
                status = S(self._row(conn, payment_id)["status"])
            action_name = "retry_void" if status in (S.VOID_FAILED, S.VOIDING) else "retry_capture"
        return self._decide(payment_id, ACTIONS[action_name], note=note)

    def _decide(self, payment_id: str, action: Action, *, actor: str | None = None,
                note: str | None = None) -> dict:
        actor = actor or action.actor
        in_flight = S.CAPTURING if action.kind == "capture" else S.VOIDING
        fields: dict = {}
        if action.records_decision:
            fields.update(decided_by=actor, decided_at=db.iso(db.utcnow()), decision_note=note)
        if action.void_reason:
            fields["void_reason"] = action.void_reason

        claimed, row = self._transition(
            payment_id, action.allowed_from, in_flight, actor, fields,
            ("decision.accepted", {"action": action.name, "note": note}),
            guard=(lambda r: not _hold_expired(r)) if action.enforces_deadline else None,
        )
        if not claimed and action.enforces_deadline and S(row["status"]) in action.allowed_from:
            # The hold ran out before this decision arrived and the sweeper has not got to it yet: void it now.
            self._event(payment_id, actor, "decision.too_late", {"action": action.name})
            try:
                self._decide(payment_id, ACTIONS["timeout"])
            except Conflict:
                pass
            with self._conn() as conn:
                row = self._row(conn, payment_id)
        if not claimed:
            return self._unclaimed(payment_id, action, actor, row)
        if action.kind == "capture":
            self._run_capture(payment_id)
        else:
            self._run_void(payment_id)
        return self.get_payment(payment_id)

    def _unclaimed(self, payment_id: str, action: Action, actor: str, row: sqlite3.Row) -> dict:
        """Someone else already changed the payment. Same direction: return that result. Otherwise: 409."""
        in_flight = S.CAPTURING if action.kind == "capture" else S.VOIDING
        done = {S.CAPTURED, S.CAPTURE_PENDING} if action.kind == "capture" else {S.VOIDED, S.EXPIRED, S.VOID_FAILED}
        status = S(row["status"])
        waited = False
        if status == in_flight:
            row, waited = self._wait_until_not(payment_id, in_flight), True
            status = S(row["status"])
        if waited or status in done:
            self._event(payment_id, actor, "decision.repeated", {"action": action.name, "status": status.value})
            return self.get_payment(payment_id)
        self._event(payment_id, actor, "decision.rejected", {"action": action.name, "status": status.value})
        raise Conflict(f"Cannot {VERB[action.name]} this payment: {_conflict_reason(row)}.",
                       payment=self.get_payment(payment_id))

    def _wait_until_not(self, payment_id: str, status: Status) -> sqlite3.Row:
        deadline = time.monotonic() + self.settings.inflight_wait_seconds
        while True:
            with self._conn() as conn:
                row = self._row(conn, payment_id)
            if row["status"] != status.value or time.monotonic() >= deadline:
                return row
            time.sleep(0.05)

    # ---------------------------------------------------------------- PayPal capture / void

    def _read_authorization(self, payment_id: str, auth_id: str) -> str:
        info = self._with_retry(lambda: self.gateway.get_authorization(auth_id))
        self._event(payment_id, "system", "paypal.authorization_read",
                    {"status": info.status, "paypal_debug_id": info.debug_id})
        return info.status

    def _settle_from_paypal(self, payment_id: str, from_status: Status, paypal_status: str, during: str) -> bool:
        """PayPal already shows a final state: record it instead of calling capture or void."""
        with self._conn() as conn:
            reason = self._row(conn, payment_id)["void_reason"]
        target, message = {
            "CAPTURED": (S.CAPTURED, "PayPal shows this authorization was already captured."),
            "VOIDED": (S.EXPIRED if reason == "timeout" else S.VOIDED,
                       "PayPal shows this authorization was already voided. Nothing was captured."),
            "EXPIRED": (S.EXPIRED, "The PayPal authorization expired. Nothing was captured."),
        }.get(paypal_status, (None, ""))
        if target is None:
            return False
        last_error = None if (target == S.CAPTURED and during == "capture") or (
            target != S.CAPTURED and during == "void") else message
        self._transition(payment_id, {from_status}, target, "system", {"last_error": last_error},
                         (f"paypal.{during}_skipped", {"paypal_status": paypal_status, "message": message}))
        return True

    def _safe_auth_status(self, payment_id: str, auth_id: str) -> str | None:
        try:
            return self._read_authorization(payment_id, auth_id)
        except GatewayError:
            return None

    def _run_capture(self, payment_id: str) -> None:
        with self._conn() as conn:
            row = self._row(conn, payment_id)
        auth_id, attempt = row["paypal_authorization_id"], row["capture_attempt"]

        try:
            paypal_status = self._read_authorization(payment_id, auth_id)
        except GatewayError as exc:
            self._transition(payment_id, {S.CAPTURING}, S.CAPTURE_FAILED, "system",
                             {"last_error": f"Could not check the authorization: {exc.message}"},
                             ("paypal.capture_failed", {**exc.as_detail(), "stage": "read"}))
            return
        if paypal_status == "CAPTURED" and row["paypal_capture_id"]:
            # PayPal shows a capture and we know which one: its own status decides, not the authorization's
            try:
                info = self._with_retry(lambda: self.gateway.get_capture(row["paypal_capture_id"]))
            except GatewayError as exc:
                self._transition(payment_id, {S.CAPTURING}, S.CAPTURE_FAILED, "system",
                                 {"last_error": f"Could not check the capture: {exc.message}"},
                                 ("paypal.capture_failed", {**exc.as_detail(), "stage": "read_capture"}))
                return
            self._apply_capture_status(payment_id, S.CAPTURING, row["paypal_capture_id"], info.status, attempt,
                                       {"paypal_debug_id": info.debug_id, "reconciled": True})
            return
        if paypal_status not in USABLE_AUTH_STATUSES:
            if not self._settle_from_paypal(payment_id, S.CAPTURING, paypal_status, "capture"):
                self._transition(payment_id, {S.CAPTURING}, S.CAPTURE_FAILED, "system",
                                 {"last_error": f"PayPal authorization status is {paypal_status}."},
                                 ("paypal.capture_failed", {"paypal_status": paypal_status, "stage": "read"}))
            return

        rid = request_id(payment_id, "capture", attempt)
        self._event(payment_id, "system", "paypal.capture_requested", {"request_id": rid})
        try:
            capture = self._with_retry(lambda: self.gateway.capture(auth_id, request_id=rid))
        except GatewayError as exc:
            fields = {"last_error": exc.message}
            if exc.kind == "client":
                current = self._safe_auth_status(payment_id, auth_id)
                if current and self._settle_from_paypal(payment_id, S.CAPTURING, current, "capture"):
                    return
                fields["capture_attempt"] = attempt + 1  # definite rejection: a retry needs a new id
            self._transition(payment_id, {S.CAPTURING}, S.CAPTURE_FAILED, "system", fields,
                             ("paypal.capture_failed", {**exc.as_detail(), "request_id": rid,
                                                         "retry_reuses_request_id": exc.retry_same_id}))
            return
        self._apply_capture_status(payment_id, S.CAPTURING, capture.capture_id, capture.status, attempt,
                                   {"request_id": rid, "paypal_debug_id": capture.debug_id})

    def _apply_capture_status(self, payment_id: str, from_status: Status, capture_id: str, capture_status: str,
                              attempt: int, detail: dict) -> None:
        """Record what PayPal says about a capture. Only a settled capture is a completed payment."""
        status = (capture_status or "").upper()
        detail = {"capture_id": capture_id, "capture_status": status or "MISSING", **detail}
        if status in CAPTURE_DONE:
            self._transition(payment_id, {from_status}, S.CAPTURED, "system",
                             {"paypal_capture_id": capture_id, "last_error": None}, ("paypal.captured", detail))
        elif status in CAPTURE_REJECTED:
            # a definite refusal: a retry is a new capture and needs a new request id
            self._transition(payment_id, {from_status}, S.CAPTURE_FAILED, "system",
                             {"paypal_capture_id": capture_id, "capture_attempt": attempt + 1,
                              "last_error": f"PayPal reported the capture as {status.lower()}."},
                             ("paypal.capture_failed", {**detail, "stage": "settle"}))
        else:  # PENDING, or a status we do not know: not confirmed, so we keep asking
            self._transition(payment_id, {from_status}, S.CAPTURE_PENDING, "system",
                             {"paypal_capture_id": capture_id, "last_error": None},
                             ("paypal.capture_pending", detail))

    def _reconcile_capture(self, payment_id: str) -> None:
        """Re-read a pending capture from PayPal and settle it. A failed read just tries again later."""
        with self._conn() as conn:
            row = self._row(conn, payment_id)
        capture_id, attempt = row["paypal_capture_id"], row["capture_attempt"]
        try:
            info = self._with_retry(lambda: self.gateway.get_capture(capture_id))
        except GatewayError as exc:
            self._touch(payment_id, S.CAPTURE_PENDING)
            self._event(payment_id, "system", "paypal.capture_check_failed", exc.as_detail())
            return
        if (info.status or "").upper() in CAPTURE_DONE | CAPTURE_REJECTED:
            self._apply_capture_status(payment_id, S.CAPTURE_PENDING, capture_id, info.status, attempt,
                                       {"paypal_debug_id": info.debug_id, "reconciled": True})
        else:
            self._touch(payment_id, S.CAPTURE_PENDING)
            self._event(payment_id, "system", "paypal.capture_still_pending",
                        {"capture_id": capture_id, "capture_status": info.status or "MISSING"})

    def _touch(self, payment_id: str, expected: Status) -> None:
        """Mark the payment as just checked, so the sweeper waits before reading it again."""
        with self._conn() as conn, db.transaction(conn):
            conn.execute("UPDATE payments SET updated_at = ? WHERE id = ? AND status = ?",
                         (db.iso(db.utcnow()), payment_id, expected.value))

    def _run_void(self, payment_id: str) -> None:
        with self._conn() as conn:
            row = self._row(conn, payment_id)
        auth_id, attempt, reason = row["paypal_authorization_id"], row["void_attempt"], row["void_reason"]

        try:
            paypal_status = self._read_authorization(payment_id, auth_id)
        except GatewayError as exc:
            self._transition(payment_id, {S.VOIDING}, S.VOID_FAILED, "system",
                             {"last_error": f"Could not check the authorization: {exc.message}"},
                             ("paypal.void_failed", {**exc.as_detail(), "stage": "read"}))
            return
        if paypal_status not in USABLE_AUTH_STATUSES:
            if not self._settle_from_paypal(payment_id, S.VOIDING, paypal_status, "void"):
                self._transition(payment_id, {S.VOIDING}, S.VOID_FAILED, "system",
                                 {"last_error": f"PayPal authorization status is {paypal_status}."},
                                 ("paypal.void_failed", {"paypal_status": paypal_status, "stage": "read"}))
            return

        rid = request_id(payment_id, "void", attempt)
        self._event(payment_id, "system", "paypal.void_requested", {"request_id": rid})
        try:
            debug_id = self._with_retry(lambda: self.gateway.void(auth_id, request_id=rid))
        except GatewayError as exc:
            fields = {"last_error": exc.message}
            if exc.kind == "client":
                current = self._safe_auth_status(payment_id, auth_id)
                if current and self._settle_from_paypal(payment_id, S.VOIDING, current, "void"):
                    return
                fields["void_attempt"] = attempt + 1
            self._transition(payment_id, {S.VOIDING}, S.VOID_FAILED, "system", fields,
                             ("paypal.void_failed", {**exc.as_detail(), "request_id": rid,
                                                      "retry_reuses_request_id": exc.retry_same_id}))
            return
        final = S.EXPIRED if reason == "timeout" else S.VOIDED
        self._transition(payment_id, {S.VOIDING}, final, "system", {"last_error": None},
                         ("paypal.voided", {"request_id": rid, "paypal_debug_id": debug_id}))

    # ---------------------------------------------------------------- timeouts and recovery

    def sweep(self, now: datetime | None = None) -> dict:
        """Void expired holds, retry failed voids, resume stuck in-flight payments.

        Runs from the background task every few seconds and at startup.
        """
        if not self._sweep_lock.acquire(blocking=False):
            return {"skipped": True}
        try:
            now = now or db.utcnow()
            with self._conn() as conn:
                expired = [r["id"] for r in conn.execute(
                    f"SELECT id FROM payments WHERE status IN ({','.join('?' * len(TIMEOUT_VOIDABLE))}) "
                    "AND hold_expires_at IS NOT NULL AND hold_expires_at <= ?",
                    (*[s.value for s in TIMEOUT_VOIDABLE], db.iso(now)),
                )]
                void_failed = [r["id"] for r in conn.execute(
                    "SELECT id FROM payments WHERE status = 'VOID_FAILED' AND updated_at <= ?",
                    (db.iso(now - timedelta(seconds=self.settings.void_retry_seconds)),),
                )]
                unanswered = [r["id"] for r in conn.execute(
                    "SELECT id FROM payments WHERE status = 'CREATED' AND last_error IS NOT NULL "
                    "AND updated_at <= ?",
                    (db.iso(now - timedelta(seconds=self.settings.auth_retry_seconds)),),
                )]
                pending = [r["id"] for r in conn.execute(
                    "SELECT id FROM payments WHERE status = 'CAPTURE_PENDING' AND updated_at <= ?",
                    (db.iso(now - timedelta(seconds=self.settings.capture_recheck_seconds)),),
                )]
                stuck = [(r["id"], r["status"]) for r in conn.execute(
                    "SELECT id, status FROM payments WHERE status IN ('CAPTURING', 'VOIDING', 'CREATED', "
                    "'AUTHORIZED') AND updated_at <= ?",
                    (db.iso(now - timedelta(seconds=self.settings.stuck_after_seconds)),),
                )]
            for pid in expired:
                try:
                    self._decide(pid, ACTIONS["timeout"])
                except Conflict:
                    pass
            for pid in void_failed:
                try:
                    self._decide(pid, ACTIONS["retry_void"], actor="system")
                except Conflict:
                    pass
            for pid in unanswered:
                self._resume(pid, S.CREATED)
            for pid in pending:
                self._reconcile_capture(pid)
            for pid, status in stuck:
                self._resume(pid, S(status))
            return {"expired": len(expired), "void_retried": len(void_failed), "resumed": len(stuck),
                    "capture_checked": len(pending), "authorization_retried": len(unanswered)}
        finally:
            self._sweep_lock.release()

    def recover(self) -> dict:
        """At startup nothing is in flight, so resume every unfinished payment immediately."""
        with self._conn() as conn:
            rows = [(r["id"], r["status"]) for r in conn.execute(
                "SELECT id, status FROM payments WHERE status IN ('CAPTURING', 'VOIDING', 'CREATED', 'AUTHORIZED')"
            )]
        for pid, status in rows:
            self._event(pid, "system", "recovery.resumed", {"status": status})
            self._resume(pid, S(status))
        return {"resumed": len(rows), **self.sweep()}

    def _resume(self, payment_id: str, status: Status) -> None:
        if status == S.CAPTURING:
            self._run_capture(payment_id)  # same attempt number, so the same request id
        elif status == S.VOIDING:
            self._run_void(payment_id)
        elif status == S.CREATED:
            self._authorize_and_route(payment_id)  # same create request id: PayPal returns the same order
        elif status == S.AUTHORIZED:
            self._route(payment_id)

    # ---------------------------------------------------------------- screenshots

    def read_screenshot(self, image_base64: str, mime_type: str) -> dict:
        """Save the screenshot and transcribe the conversation in it. The sender confirms the text before it is
        checked; if the AI cannot read it, the screenshot is still kept and shown to the guardian."""
        ext = SCREENSHOT_TYPES.get(mime_type)
        if ext is None:
            raise Invalid("Please choose a PNG, JPEG or WebP image.")
        payload = image_base64.split(",", 1)[1] if image_base64.startswith("data:") else image_base64
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise Invalid("That file could not be read as an image.") from None
        if len(data) > self.settings.max_screenshot_bytes:
            raise Invalid(f"Please choose an image smaller than {self.settings.max_screenshot_bytes // 1_000_000} MB.")
        if not _looks_like(ext, data):
            raise Invalid("That file is not a PNG, JPEG or WebP image.")

        screenshot_id = f"{hashlib.sha256(data).hexdigest()[:32]}.{ext}"
        folder = self.settings.upload_path
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / screenshot_id
        if not path.exists():
            path.write_bytes(data)

        provider = getattr(self.assessor, "provider", None)
        if provider is None:
            outcome = ai_mod.TranscriptOutcome(error="AI check not configured", error_kind="not_configured")
        else:
            outcome = ai_mod.transcribe_screenshot(provider, base64.b64encode(data).decode(), mime_type)
        self._event(None, "sender", "screenshot.read", {
            "screenshot_id": screenshot_id, "read": outcome.ok, "messages": outcome.message_count,
            "own_messages_skipped": outcome.own_messages_skipped, "error_kind": outcome.error_kind,
            "model": outcome.model, "cached": outcome.cached, "latency_ms": outcome.latency_ms,
        })
        return {
            "screenshot_id": screenshot_id,
            "url": f"/screenshots/{screenshot_id}",
            "read": outcome.ok,
            "text": outcome.text,
            "sender": outcome.sender,
            "messages_found": outcome.message_count,
            "own_messages_skipped": outcome.own_messages_skipped,
            "error": None if outcome.ok else SCREENSHOT_HELP.get(outcome.error_kind or "", SCREENSHOT_RETRY),
            "model": outcome.model,
            "cached": outcome.cached,
            "latency_ms": outcome.latency_ms,
        }

    def screenshot_file(self, screenshot_id: str, *, invalid: bool = False) -> Path:
        path = self.settings.upload_path / screenshot_id
        if not SCREENSHOT_ID.match(screenshot_id) or not path.is_file():
            if invalid:
                raise Invalid("That screenshot was not found. Please add it again.")
            raise NotFound("Screenshot not found.")
        return path

    # ---------------------------------------------------------------- messages

    def add_message(self, payment_id: str, from_role: str, body: str) -> dict:
        with self._conn() as conn, db.transaction(conn):
            row = self._row(conn, payment_id)
            if S(row["status"]) in TERMINAL:
                # The conversation is about a decision that is still open; once the payment is final the
                # thread is closed on both screens, and the server agrees.
                raise Conflict("This payment is already final, so new messages cannot be added.")
            conn.execute(
                "INSERT INTO guardian_messages (payment_id, from_role, body, at) VALUES (?, ?, ?, ?)",
                (payment_id, from_role, body, db.iso(db.utcnow())),
            )
            db.add_event(conn, payment_id, from_role, "message.added", {"length": len(body)})
        return self.get_payment(payment_id)

    # ---------------------------------------------------------------- reads

    def get_payment(self, payment_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(_SELECT_PAYMENT + " WHERE p.id = ?", (payment_id,)).fetchone()
            if row is None:
                raise NotFound(f"Payment {payment_id} not found.")
            assessment = conn.execute(
                "SELECT * FROM assessments WHERE payment_id = ? ORDER BY id DESC LIMIT 1", (payment_id,)
            ).fetchone()
            events = conn.execute(
                "SELECT at, actor, type, detail_json FROM events WHERE payment_id = ? ORDER BY id", (payment_id,)
            ).fetchall()
            messages = conn.execute(
                "SELECT from_role, body, at FROM guardian_messages WHERE payment_id = ? ORDER BY id", (payment_id,)
            ).fetchall()
            payee_history = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS total FROM payments "
                "WHERE payee_id = ? AND status = 'CAPTURED' AND id != ?", (row["payee_id"], payment_id)
            ).fetchone()
        out = _serialize(row)
        out["risk"] = _serialize_assessment(assessment)
        out["payee"]["captured_payments"] = payee_history["n"]
        out["payee"]["captured_total"] = format_amount(payee_history["total"]) if payee_history["total"] else "0.00"
        out["events"] = [
            {"at": e["at"], "actor": e["actor"], "type": e["type"], "detail": json.loads(e["detail_json"])}
            for e in events
        ]
        out["messages"] = [dict(m) for m in messages]
        return out

    def list_payments(self, *, statuses: list[str] | None = None, queue: str | None = None,
                      limit: int = 200) -> list[dict]:
        where, params = [], []
        if queue == "guardian":
            statuses = [s.value for s in GUARDIAN_QUEUE]
        if statuses:
            where.append(f"p.status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        sql = _SELECT_PAYMENT + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY p.created_at DESC LIMIT ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
            briefs = self._risk_briefs(conn, [r["id"] for r in rows])
        out = []
        for r in rows:
            item = _serialize(r)
            item["risk_brief"] = briefs.get(r["id"])
            out.append(item)
        return out

    @staticmethod
    def _risk_briefs(conn: sqlite3.Connection, payment_ids: list[str]) -> dict[str, dict]:
        """A short, list-friendly view of each payment's latest assessment (one query for all rows)."""
        if not payment_ids:
            return {}
        marks = ",".join("?" * len(payment_ids))
        rows = conn.execute(
            f"""SELECT a.payment_id, a.summary, a.mode, a.evidence_json, a.components_json
                FROM assessments a
                JOIN (SELECT payment_id, MAX(id) AS last FROM assessments WHERE payment_id IN ({marks})
                      GROUP BY payment_id) t ON a.id = t.last""",
            payment_ids,
        ).fetchall()
        briefs = {}
        for a in rows:
            evidence = json.loads(a["evidence_json"] or "{}")
            indicators = evidence.get("indicators", []) if isinstance(evidence, dict) else evidence
            components = json.loads(a["components_json"] or "{}")
            # Quoted evidence only: words that appear in the message or note (rule matches or grounded AI quotes).
            quotes = [
                {"type": i["type"], "evidence": i["evidence"], "source": i["source"], "label": i["label"]}
                for i in indicators if i.get("evidence") and i.get("spans")
            ]
            checked_by = "rules"
            if a["mode"] == "hybrid":
                checked_by = "stored_reply" if components.get("ai_cached") else "ai"
            briefs[a["payment_id"]] = {
                "summary": a["summary"],
                "checked_by": checked_by,
                "ai_flagged": any(i["source"] == "ai" for i in indicators),
                "top_evidence": quotes[:3],
            }
        return briefs

    def stats(self) -> dict:
        """Counts and totals for the Insights cards. Seeded history is excluded.

        Wording matters: these are attempted payments held from capture, not "money saved" — we cannot
        prove any of them was fraud.
        """
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT p.id, p.status, p.amount_cents, p.risk_level, p.risk_mode, p.void_reason, p.decided_by,
                       {_CATEGORY_SQL} AS category,
                       EXISTS (SELECT 1 FROM events e WHERE e.payment_id = p.id AND e.type = 'status.changed'
                               AND json_extract(e.detail_json, '$.to') = 'HELD') AS was_held,
                       EXISTS (SELECT 1 FROM events e WHERE e.payment_id = p.id AND e.type = 'status.changed'
                               AND json_extract(e.detail_json, '$.to') = 'WARNED') AS was_warned
                FROM payments p WHERE p.is_seed = 0
                """
            ).fetchall()
            since = db.iso(db.utcnow() - timedelta(days=RECENT_DAYS))
            recent = conn.execute(
                "SELECT created_at, status, is_seed FROM payments WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
            payee_rows = conn.execute(
                f"""
                SELECT y.name AS payee, p.status, p.amount_cents
                FROM payments p JOIN payees y ON y.id = p.payee_id
                WHERE p.is_seed = 0 AND EXISTS (
                    SELECT 1 FROM events e WHERE e.payment_id = p.id AND e.type = 'status.changed'
                    AND json_extract(e.detail_json, '$.to') IN ('HELD', 'WARNED'))
                """
            ).fetchall()

        def bucket(selected: list[sqlite3.Row]) -> dict:
            total = sum(r["amount_cents"] for r in selected)
            return {"count": len(selected), "total": format_amount(total), "total_cents": total}

        not_captured = {S.VOIDED.value, S.EXPIRED.value, S.VOID_FAILED.value}
        reviewed = [r for r in rows if r["was_held"] or r["was_warned"]]
        categories: dict[str, list[sqlite3.Row]] = {}
        for r in reviewed:
            categories.setdefault(r["category"] or "uncategorised", []).append(r)
        top = sorted(categories.items(), key=lambda kv: (kv[0] == "uncategorised", -len(kv[1]),
                                                          -sum(r["amount_cents"] for r in kv[1])))

        payees: dict[str, list[sqlite3.Row]] = {}
        for r in payee_rows:
            payees.setdefault(r["payee"], []).append(r)
        flagged = sorted(payees.items(), key=lambda kv: (-len(kv[1]), -sum(r["amount_cents"] for r in kv[1]), kv[0]))

        return {
            "payments": len(rows),
            "on_hold_now": sum(r["status"] == S.HELD.value for r in rows),
            "held_for_guardian": bucket([r for r in rows if r["was_held"]]),
            "warned_sender": bucket([r for r in rows if r["was_warned"]]),
            "held_from_capture": bucket([r for r in reviewed if r["status"] in not_captured]),
            "declined_by_guardian": bucket([r for r in rows if r["void_reason"] == "guardian_decline"]),
            "cancelled_by_sender": bucket([r for r in rows if r["void_reason"] == "sender_cancel"]),
            "expired_no_answer": bucket([r for r in rows if r["status"] == S.EXPIRED.value]),
            "approved_by_guardian": bucket([r for r in rows if r["status"] == S.CAPTURED.value
                                            and r["decided_by"] == "guardian"]),
            "confirmed_by_sender": bucket([r for r in rows if r["status"] == S.CAPTURED.value
                                           and r["decided_by"] == "sender"]),
            "auto_captured": bucket([r for r in rows if r["status"] == S.CAPTURED.value and not r["decided_by"]]),
            "by_level": {lv: sum(r["risk_level"] == lv for r in rows) for lv in ("low", "medium", "high")},
            "rules_only_checks": sum(r["risk_mode"] == "rules_only" for r in rows),
            "top_categories": [
                {"category": cat, **bucket(items)} for cat, items in top[:6]
            ],
            # Every payment of the last RECENT_DAYS days, seeded history included, so the browser can
            # group them by its own local day. AUTH_FAILED never reached a decision and is left out.
            "recent": [
                {"at": r["created_at"], "outcome": _outcome(r["status"]), "past": bool(r["is_seed"])}
                for r in recent if r["status"] != S.AUTH_FAILED.value
            ],
            "recent_days": RECENT_DAYS,
            "flagged_payees": [
                {"payee": name, **bucket(items),
                 "not_captured": sum(r["status"] in not_captured for r in items)}
                for name, items in flagged[:5]
            ],
        }


RECENT_DAYS = 30


def _outcome(status: str) -> str:
    """Where a payment ended up, for the Insights timeline: captured, stopped (never captured) or still open."""
    if status == S.CAPTURED.value:
        return "captured"
    if status in (S.VOIDED.value, S.EXPIRED.value):
        return "stopped"
    return "open"


# The scam category shown in lists: the AI's category, or (when the AI said "none" or did not run) the
# family of the best-matching known scam pattern.
_CATEGORY_SQL = """(
    SELECT COALESCE(NULLIF(json_extract(a.ai_json, '$.category'), 'none'),
                    json_extract(a.patterns_json, '$[0].category'))
    FROM assessments a WHERE a.payment_id = p.id ORDER BY a.id DESC LIMIT 1
)"""

_SELECT_PAYMENT = f"""
SELECT p.*, y.name AS payee_name, y.email AS payee_email, y.trusted AS payee_trusted,
       {_CATEGORY_SQL} AS category
FROM payments p JOIN payees y ON y.id = p.payee_id
"""


def _serialize(row: sqlite3.Row) -> dict:
    status = S(row["status"])
    seconds_left = None
    if status in TIMEOUT_VOIDABLE and row["hold_expires_at"]:
        seconds_left = max(0, int((db.parse_iso(row["hold_expires_at"]) - db.utcnow()).total_seconds()))
    return {
        "id": row["id"],
        "status": status.value,
        "amount": format_amount(row["amount_cents"]),
        "amount_cents": row["amount_cents"],
        "currency": row["currency"],
        "payee": {"id": row["payee_id"], "name": row["payee_name"], "email": row["payee_email"],
                  "trusted": bool(row["payee_trusted"])},
        "note": row["note"],
        "message_text": row["message_text"],
        "risk_level": row["risk_level"],
        "risk_score": row["risk_score"],
        "risk_mode": row["risk_mode"],
        "paypal": {"order_id": row["paypal_order_id"], "authorization_id": row["paypal_authorization_id"],
                   "capture_id": row["paypal_capture_id"]},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "hold_expires_at": row["hold_expires_at"],
        "hold_seconds_left": seconds_left,
        "decided_by": row["decided_by"],
        "decided_at": row["decided_at"],
        "decision_note": row["decision_note"],
        "void_reason": row["void_reason"],
        "last_error": row["last_error"],
        "is_seed": bool(row["is_seed"]),
        "category": row["category"] if "category" in row.keys() else None,
        "screenshot_url": f"/screenshots/{row['screenshot_path']}" if row["screenshot_path"] else None,
        "final": status in TERMINAL,
        "text": _status_text_for(status, row),
        "can": {
            "confirm": status in ACTIONS["confirm"].allowed_from,
            "cancel": status in ACTIONS["cancel"].allowed_from,
            "approve": status in ACTIONS["approve"].allowed_from,
            "decline": status in ACTIONS["decline"].allowed_from,
            "retry": status in (S.CAPTURE_FAILED, S.VOID_FAILED),
        },
    }


def _risk_dict(level, score, mode, summary, indicators, spans, ai, ai_error, dropped, patterns, components,
               model, latency_ms) -> dict:
    return {
        "level": level,
        "score": score,
        "score_label": "heuristic score (not a probability)",
        "mode": mode,
        "ai_unavailable": mode == "rules_only",
        "ai_unavailable_text": "AI check unavailable, rules only" if mode == "rules_only" else None,
        "summary": summary,
        "category": (ai or {}).get("category"),
        "indicators": indicators,
        "evidence_spans": spans,
        "ai": ai,
        "ai_error": ai_error,
        "dropped_evidence": dropped,
        "patterns": patterns,
        "components": components,
        "model": model,
        "latency_ms": latency_ms,
    }


def _serialize_risk(risk: RiskResult) -> dict:
    return _risk_dict(risk.level, risk.score, risk.mode, risk.summary, risk.indicators, risk.evidence_spans,
                      risk.ai, risk.ai_error, risk.dropped_evidence, risk.patterns, risk.components, risk.model,
                      risk.latency_ms)


def _serialize_assessment(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    evidence = json.loads(row["evidence_json"] or "{}")
    if isinstance(evidence, list):
        evidence = {"indicators": evidence, "spans": []}
    return _risk_dict(
        row["final_level"], row["score"], row["mode"], row["summary"], evidence.get("indicators", []),
        evidence.get("spans", []), json.loads(row["ai_json"]) if row["ai_json"] else None, row["ai_error"],
        json.loads(row["dropped_evidence_json"] or "[]"), json.loads(row["patterns_json"] or "[]"),
        json.loads(row["components_json"] or "{}"), row["model"], row["latency_ms"],
    )
