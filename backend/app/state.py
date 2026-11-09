"""Payment state machine.

Rules this module enforces:
  * A payment is claimed (moved to CAPTURING or VOIDING) inside one SQLite write transaction
    before any PayPal call, so concurrent decisions cannot both act: the first valid change wins.
  * The authorization is read from PayPal before every capture and void. If PayPal already shows
    it captured, voided or expired, we record that instead of calling again.
  * PayPal-Request-Ids are deterministic ({payment_id}-capture-{attempt}). Network and 5xx retries
    reuse the id; only a definite 4xx rejection moves to the next attempt number.
  * Silence fails safe: WARNED, HELD and CAPTURE_FAILED payments are voided when the hold expires.
  * Every state change and every PayPal call writes a row to `events` (the audit log).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Iterator, TypeVar

from . import db
from .config import Settings
from .paypal import USABLE_AUTH_STATUSES, GatewayError, PaymentGateway, format_amount, request_id
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
    VOID_FAILED = "VOID_FAILED"


S = Status
TERMINAL = frozenset({S.CAPTURED, S.VOIDED, S.EXPIRED, S.AUTH_FAILED})
TIMEOUT_VOIDABLE = frozenset({S.WARNED, S.HELD, S.CAPTURE_FAILED})
GUARDIAN_QUEUE = (S.HELD, S.CAPTURE_FAILED, S.VOID_FAILED, S.CAPTURING, S.VOIDING)


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


@dataclass(frozen=True)
class Action:
    name: str
    actor: str  # default actor: system, sender or guardian
    kind: str  # "capture" or "void"
    allowed_from: frozenset
    void_reason: str | None = None
    records_decision: bool = True


ACTIONS = {
    a.name: a
    for a in (
        Action("auto_capture", "system", "capture", frozenset({S.AUTHORIZED}), records_decision=False),
        Action("confirm", "sender", "capture", frozenset({S.WARNED})),
        Action("approve", "guardian", "capture", frozenset({S.HELD})),
        Action("retry_capture", "guardian", "capture", frozenset({S.CAPTURE_FAILED}), records_decision=False),
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
        S.AUTH_FAILED: "Card authorization failed. Nothing to capture or void.",
        S.EXPIRED: "No decision before the hold timed out. Payment not captured, authorization voided.",
        S.VOIDED: "Payment not captured, authorization voided."
        + {"sender_cancel": " The sender cancelled it.", "guardian_decline": " You declined it."}.get(
            void_reason or "", ""),
    }
    st = S(status)
    return {"sender": sender[st], "guardian": guardian[st]}


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
    ) -> tuple[bool, sqlite3.Row]:
        """Atomically move a payment from one of `from_statuses` to `to`.

        Returns (True, row_before) if this call made the change, or (False, current_row).
        """
        with self._conn() as conn, db.transaction(conn):
            row = self._row(conn, payment_id)
            if S(row["status"]) not in from_statuses:
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

    def create_payment(
        self, *, payee_name: str, amount_cents: int, note: str = "", message_text: str = "",
        payee_email: str | None = None, currency: str = "USD",
    ) -> dict:
        name = " ".join(payee_name.split())
        now = db.utcnow()
        with self._conn() as conn:
            with db.transaction(conn):
                payee = conn.execute(
                    "SELECT * FROM payees WHERE sender_id = ? AND name_key = ?", (db.SENDER_ID, name.lower())
                ).fetchone()
                if payee is None:
                    cur = conn.execute(
                        "INSERT INTO payees (sender_id, name, name_key, email, first_seen_at) VALUES (?, ?, ?, ?, ?)",
                        (db.SENDER_ID, name, name.lower(), payee_email, db.iso(now)),
                    )
                    payee = conn.execute("SELECT * FROM payees WHERE id = ?", (cur.lastrowid,)).fetchone()
            history = [
                r["amount_cents"]
                for r in conn.execute(
                    "SELECT amount_cents FROM payments WHERE sender_id = ? AND status = 'CAPTURED'", (db.SENDER_ID,)
                )
            ]
            payee_count = conn.execute(
                "SELECT COUNT(*) FROM payments WHERE payee_id = ? AND status = 'CAPTURED'", (payee["id"],)
            ).fetchone()[0]

        ctx = PaymentContext(
            amount_cents=amount_cents, currency=currency, payee_name=name,
            payee_is_new=payee_count == 0 and not payee["trusted"], payee_trusted=bool(payee["trusted"]),
            note=note, message_text=message_text, history_amounts_cents=history,
            payee_history_count=payee_count, payee_spending_limit_cents=payee["spending_limit_cents"],
        )
        risk = self.assessor.assess(ctx)  # outside any transaction: the AI call can take seconds

        payment_id = uuid.uuid4().hex
        with self._conn() as conn, db.transaction(conn):
            ts = db.iso(db.utcnow())
            conn.execute(
                """INSERT INTO payments (id, sender_id, payee_id, amount_cents, currency, note, message_text,
                       status, risk_level, risk_score, risk_mode, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (payment_id, db.SENDER_ID, payee["id"], amount_cents, currency, note, message_text,
                 S.CREATED.value, risk.level, risk.score, risk.mode, ts, ts),
            )
            self._insert_assessment(conn, payment_id, risk)
            db.add_event(conn, payment_id, "sender", "payment.created", {
                "amount": format_amount(amount_cents), "currency": currency, "payee": name,
                "payee_is_new": ctx.payee_is_new, "payee_trusted": ctx.payee_trusted,
            })
            db.add_event(conn, payment_id, "system", "risk.assessed", {
                "level": risk.level, "score": risk.score, "mode": risk.mode,
                "indicators": len(risk.indicators), "dropped_evidence": len(risk.dropped_evidence),
                "ai_error": risk.ai_error,
            })

        self._authorize_and_route(payment_id)
        return self.get_payment(payment_id)

    @staticmethod
    def _insert_assessment(conn: sqlite3.Connection, payment_id: str | None, risk: RiskResult) -> None:
        conn.execute(
            """INSERT INTO assessments (payment_id, mode, final_level, score, summary, rules_json, ai_json,
                   dropped_evidence_json, patterns_json, evidence_json, ai_error, model, latency_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (payment_id, risk.mode, risk.level, risk.score, risk.summary, json.dumps(risk.rules),
             json.dumps(risk.ai) if risk.ai is not None else None, json.dumps(risk.dropped_evidence),
             json.dumps(risk.patterns), json.dumps({"indicators": risk.indicators, "spans": risk.evidence_spans}),
             risk.ai_error, risk.model, risk.latency_ms, db.iso(db.utcnow())),
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
            self._transition(payment_id, {S.CREATED}, S.AUTH_FAILED, "system",
                             {"last_error": exc.message}, ("paypal.authorization_failed", exc.as_detail()))
            return
        self._transition(
            payment_id, {S.CREATED}, S.AUTHORIZED, "system",
            {"paypal_order_id": order.order_id, "paypal_authorization_id": order.authorization_id,
             "hold_expires_at": db.iso_in(self.settings.hold_timeout_seconds)},
            ("paypal.authorized", {"order_id": order.order_id, "authorization_id": order.authorization_id,
                                   "authorization_status": order.authorization_status,
                                   "request_id": request_id(payment_id, "create"),
                                   "paypal_debug_id": order.debug_id}),
        )
        self._route(payment_id)

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

        claimed, row = self._transition(payment_id, action.allowed_from, in_flight, actor, fields,
                                        ("decision.accepted", {"action": action.name, "note": note}))
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
        done = {S.CAPTURED} if action.kind == "capture" else {S.VOIDED, S.EXPIRED, S.VOID_FAILED}
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
        self._transition(payment_id, {S.CAPTURING}, S.CAPTURED, "system",
                         {"paypal_capture_id": capture.capture_id, "last_error": None},
                         ("paypal.captured", {"capture_id": capture.capture_id, "capture_status": capture.status,
                                              "request_id": rid, "paypal_debug_id": capture.debug_id}))

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
            for pid, status in stuck:
                self._resume(pid, S(status))
            return {"expired": len(expired), "void_retried": len(void_failed), "resumed": len(stuck)}
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

    # ---------------------------------------------------------------- messages

    def add_message(self, payment_id: str, from_role: str, body: str) -> dict:
        with self._conn() as conn, db.transaction(conn):
            self._row(conn, payment_id)
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
        return [_serialize(r) for r in rows]


_SELECT_PAYMENT = """
SELECT p.*, y.name AS payee_name, y.email AS payee_email, y.trusted AS payee_trusted
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
        "final": status in TERMINAL,
        "text": status_text(status.value, row["void_reason"]),
        "can": {
            "confirm": status in ACTIONS["confirm"].allowed_from,
            "cancel": status in ACTIONS["cancel"].allowed_from,
            "approve": status in ACTIONS["approve"].allowed_from,
            "decline": status in ACTIONS["decline"].allowed_from,
            "retry": status in (S.CAPTURE_FAILED, S.VOID_FAILED),
        },
    }


def _serialize_assessment(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    evidence = json.loads(row["evidence_json"] or "{}")
    if isinstance(evidence, list):
        evidence = {"indicators": evidence, "spans": []}
    return {
        "level": row["final_level"],
        "score": row["score"],
        "mode": row["mode"],
        "summary": row["summary"],
        "indicators": evidence.get("indicators", []),
        "evidence_spans": evidence.get("spans", []),
        "rules": json.loads(row["rules_json"] or "[]"),
        "ai": json.loads(row["ai_json"]) if row["ai_json"] else None,
        "ai_error": row["ai_error"],
        "dropped_evidence": json.loads(row["dropped_evidence_json"] or "[]"),
        "patterns": json.loads(row["patterns_json"] or "[]"),
        "model": row["model"],
        "latency_ms": row["latency_ms"],
    }
