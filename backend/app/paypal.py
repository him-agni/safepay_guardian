"""PayPal gateway: the real sandbox client and an in-process fake with the same interface.

Only this module talks to PayPal. It never logs or raises with the card number or the token.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol, Union

import httpx

from .config import Settings


def request_id(payment_id: str, action: str, attempt: int | None = None) -> str:
    """Deterministic PayPal-Request-Id, e.g. "{payment_id}-capture-1".

    A network retry reuses the same id, so PayPal returns the stored result instead of
    capturing twice. A new attempt number is used only after a definite PayPal rejection.
    """
    return f"{payment_id}-{action}" if attempt is None else f"{payment_id}-{action}-{attempt}"


def format_amount(amount_cents: int) -> str:
    return f"{amount_cents // 100}.{amount_cents % 100:02d}"


class GatewayError(Exception):
    """A PayPal call failed.

    kind:
      "network": no usable response (timeout, connection error). The call may or may not
                 have reached PayPal, so a retry must reuse the same request id.
      "server":  PayPal returned 5xx. Retry with the same request id.
      "client":  PayPal returned 4xx: a definite rejection.
    """

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status_code: int | None = None,
        issue: str | None = None,
        debug_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status_code = status_code
        self.issue = issue
        self.debug_id = debug_id

    @property
    def retry_same_id(self) -> bool:
        return self.kind in ("network", "server")

    def as_detail(self) -> dict:
        return {
            "kind": self.kind,
            "message": self.message,
            "status_code": self.status_code,
            "issue": self.issue,
            "paypal_debug_id": self.debug_id,
        }


@dataclass
class AuthorizedOrder:
    order_id: str
    authorization_id: str
    authorization_status: str
    debug_id: str | None = None


@dataclass
class AuthorizationInfo:
    status: str
    debug_id: str | None = None


@dataclass
class CaptureResult:
    capture_id: str
    status: str
    debug_id: str | None = None


class PaymentGateway(Protocol):
    def create_authorized_order(
        self, *, payment_id: str, amount_cents: int, currency: str, description: str
    ) -> AuthorizedOrder: ...

    def get_authorization(self, authorization_id: str) -> AuthorizationInfo: ...

    def capture(self, authorization_id: str, *, request_id: str) -> CaptureResult: ...

    def void(self, authorization_id: str, *, request_id: str) -> str | None: ...

    def check(self) -> bool: ...


USABLE_AUTH_STATUSES = {"CREATED", "PENDING"}


# --------------------------------------------------------------------------------------
# Real PayPal sandbox client
# --------------------------------------------------------------------------------------


def _error_from_response(resp: httpx.Response, what: str) -> GatewayError:
    kind = "server" if resp.status_code >= 500 else "client"
    name = message = issue = None
    try:
        body = resp.json()
        name = body.get("name") or body.get("error")
        message = body.get("message") or body.get("error_description")
        details = body.get("details") or []
        if details:
            issue = details[0].get("issue")
            message = details[0].get("description") or message
    except ValueError:
        pass
    text = f"{what} failed: HTTP {resp.status_code}"
    if name:
        text += f" {name}"
    if message:
        text += f": {message}"
    return GatewayError(
        kind,
        text,
        status_code=resp.status_code,
        issue=issue or name,
        debug_id=resp.headers.get("paypal-debug-id"),
    )


class PayPalClient:
    """PayPal Orders v2 + Payments v2 client for the sandbox, paying with the sandbox test card."""

    def __init__(
        self,
        settings: Settings,
        *,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._s = settings
        self._http = httpx.Client(base_url=settings.paypal_base_url, timeout=timeout, transport=transport)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def _get_token(self, *, force: bool = False) -> str:
        with self._token_lock:
            if not force and self._token and time.monotonic() < self._token_expires_at:
                return self._token
            try:
                resp = self._http.post(
                    "/v1/oauth2/token",
                    auth=(self._s.paypal_client_id, self._s.paypal_client_secret.get_secret_value()),
                    data={"grant_type": "client_credentials"},
                )
            except httpx.HTTPError as exc:
                raise GatewayError("network", f"token request failed: {type(exc).__name__}") from None
            if resp.status_code != 200:
                raise _error_from_response(resp, "token request")
            body = resp.json()
            self._token = body["access_token"]
            # Refresh two minutes early.
            self._token_expires_at = time.monotonic() + max(60, int(body.get("expires_in", 300)) - 120)
            return self._token

    def _request(
        self, method: str, path: str, *, what: str, json: dict | None = None, request_id: str | None = None
    ) -> httpx.Response:
        for attempt in (1, 2):
            headers = {
                "Authorization": f"Bearer {self._get_token(force=attempt == 2)}",
                "Prefer": "return=representation",
            }
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            try:
                resp = self._http.request(method, path, json=json, headers=headers)
            except httpx.HTTPError as exc:
                raise GatewayError("network", f"{what} failed: {type(exc).__name__}") from None
            if resp.status_code == 401 and attempt == 1:
                continue  # token expired early: refresh once
            if resp.status_code >= 400:
                raise _error_from_response(resp, what)
            return resp
        raise GatewayError("client", f"{what} failed: unauthorized")  # pragma: no cover

    def create_authorized_order(
        self, *, payment_id: str, amount_cents: int, currency: str, description: str
    ) -> AuthorizedOrder:
        card = {
            "number": self._s.sandbox_card_number.get_secret_value(),
            "expiry": self._s.sandbox_card_expiry,
            "security_code": self._s.sandbox_card_security_code.get_secret_value(),
        }
        if self._s.sandbox_card_name:
            card["name"] = self._s.sandbox_card_name
        body = {
            "intent": "AUTHORIZE",
            "purchase_units": [
                {
                    "reference_id": payment_id,
                    "custom_id": payment_id,
                    "description": description[:127],
                    "amount": {"currency_code": currency, "value": format_amount(amount_cents)},
                }
            ],
            "payment_source": {"card": card},
        }
        resp = self._request(
            "POST", "/v2/checkout/orders", what="create order", json=body,
            request_id=request_id(payment_id, "create"),
        )
        order = resp.json()
        debug_id = resp.headers.get("paypal-debug-id")
        if order.get("status") == "PAYER_ACTION_REQUIRED":
            raise GatewayError("client", "card needs payer action (3-D Secure)", issue="PAYER_ACTION_REQUIRED",
                               debug_id=debug_id)
        auths = _authorizations(order)
        if not auths:
            resp = self._request(
                "POST", f"/v2/checkout/orders/{order['id']}/authorize", what="authorize order", json={},
                request_id=request_id(payment_id, "authorize"),
            )
            auths = _authorizations(resp.json())
            debug_id = resp.headers.get("paypal-debug-id")
        if not auths:
            raise GatewayError("client", "PayPal returned no authorization", issue="NO_AUTHORIZATION",
                               debug_id=debug_id)
        auth = auths[0]
        status = auth.get("status", "")
        if status not in USABLE_AUTH_STATUSES:
            raise GatewayError("client", f"authorization {status.lower() or 'missing'}",
                               issue=f"AUTHORIZATION_{status or 'MISSING'}", debug_id=debug_id)
        return AuthorizedOrder(order["id"], auth["id"], status, debug_id)

    def get_authorization(self, authorization_id: str) -> AuthorizationInfo:
        resp = self._request("GET", f"/v2/payments/authorizations/{authorization_id}", what="read authorization")
        return AuthorizationInfo(resp.json()["status"], resp.headers.get("paypal-debug-id"))

    def capture(self, authorization_id: str, *, request_id: str) -> CaptureResult:
        resp = self._request(
            "POST", f"/v2/payments/authorizations/{authorization_id}/capture", what="capture", json={},
            request_id=request_id,
        )
        body = resp.json()
        return CaptureResult(body["id"], body.get("status", ""), resp.headers.get("paypal-debug-id"))

    def void(self, authorization_id: str, *, request_id: str) -> str | None:
        resp = self._request(
            "POST", f"/v2/payments/authorizations/{authorization_id}/void", what="void", request_id=request_id
        )
        return resp.headers.get("paypal-debug-id")

    def check(self) -> bool:
        try:
            self._get_token()
            return True
        except GatewayError:
            return False


def _authorizations(order: dict) -> list[dict]:
    units = order.get("purchase_units") or [{}]
    return (units[0].get("payments") or {}).get("authorizations") or []


# --------------------------------------------------------------------------------------
# Fake PayPal for tests and for running without credentials (PAYPAL_MODE=fake)
# --------------------------------------------------------------------------------------

LOSE_RESPONSE = "lose_response"  # perform the call, then fail as if the response was lost
Fault = Union[GatewayError, str, Callable[[], None]]


@dataclass
class FakePayPal:
    """In-process PayPal with the same idempotency rules as the real one.

    Faults are queued per operation ("create", "get", "capture", "void"):
      - a GatewayError: raised before the call has any effect
      - LOSE_RESPONSE: the call takes effect, then a network error is raised
      - a callable: run first (e.g. to void the authorization behind our back), then the call proceeds
    """

    capture_delay: float = 0.0
    authorizations: dict = field(default_factory=dict)  # authorization id -> status
    captures: list = field(default_factory=list)  # (authorization id, capture id)
    voids: list = field(default_factory=list)  # authorization ids
    calls: list = field(default_factory=list)  # (operation, request id or authorization id)
    _faults: dict = field(default_factory=dict)
    _idem: dict = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def inject(self, op: str, fault: Fault) -> None:
        with self._lock:
            self._faults.setdefault(op, []).append(fault)

    def set_status(self, authorization_id: str, status: str) -> None:
        with self._lock:
            self.authorizations[authorization_id] = status

    def _next_fault(self, op: str) -> Fault | None:
        with self._lock:
            queue = self._faults.get(op) or []
            return queue.pop(0) if queue else None

    def _run(self, op: str, rid: str | None, fn: Callable[[], object]) -> object:
        with self._lock:
            self.calls.append((op, rid))
            if rid and rid in self._idem:
                stored = self._idem[rid]
                if isinstance(stored, GatewayError):
                    raise stored
                return stored
        fault = self._next_fault(op)
        if isinstance(fault, GatewayError):
            raise fault
        if callable(fault):
            fault()
        if op == "capture" and self.capture_delay:
            time.sleep(self.capture_delay)
        with self._lock:
            if rid and rid in self._idem:  # a concurrent call with the same id finished first
                stored = self._idem[rid]
                if isinstance(stored, GatewayError):
                    raise stored
                return stored
            try:
                result: object = fn()
            except GatewayError as exc:
                if rid and exc.kind == "client":
                    self._idem[rid] = exc
                raise
            if rid:
                self._idem[rid] = result
        if fault == LOSE_RESPONSE:
            raise GatewayError("network", f"{op} failed: ReadTimeout")
        return result

    def create_authorized_order(
        self, *, payment_id: str, amount_cents: int, currency: str, description: str
    ) -> AuthorizedOrder:
        def go() -> AuthorizedOrder:
            auth_id = "FAKEAUTH" + uuid.uuid4().hex[:10].upper()
            self.authorizations[auth_id] = "CREATED"
            return AuthorizedOrder("FAKEORDER" + uuid.uuid4().hex[:10].upper(), auth_id, "CREATED", "fake-debug")

        return self._run("create", request_id(payment_id, "create"), go)  # type: ignore[return-value]

    def get_authorization(self, authorization_id: str) -> AuthorizationInfo:
        def go() -> AuthorizationInfo:
            if authorization_id not in self.authorizations:
                raise GatewayError("client", "read authorization failed: HTTP 404", status_code=404,
                                   issue="RESOURCE_NOT_FOUND")
            return AuthorizationInfo(self.authorizations[authorization_id], "fake-debug")

        return self._run("get", None, go)  # type: ignore[return-value]

    def capture(self, authorization_id: str, *, request_id: str) -> CaptureResult:
        def go() -> CaptureResult:
            status = self.authorizations.get(authorization_id)
            if status in USABLE_AUTH_STATUSES:
                self.authorizations[authorization_id] = "CAPTURED"
                capture_id = "FAKECAP" + uuid.uuid4().hex[:10].upper()
                self.captures.append((authorization_id, capture_id))
                return CaptureResult(capture_id, "COMPLETED", "fake-debug")
            issue = {"CAPTURED": "AUTHORIZATION_ALREADY_CAPTURED", "VOIDED": "AUTHORIZATION_VOIDED",
                     "EXPIRED": "AUTHORIZATION_EXPIRED"}.get(status or "", "RESOURCE_NOT_FOUND")
            raise GatewayError("client", f"capture failed: HTTP 422 {issue}", status_code=422, issue=issue)

        return self._run("capture", request_id, go)  # type: ignore[return-value]

    def void(self, authorization_id: str, *, request_id: str) -> str | None:
        def go() -> str:
            status = self.authorizations.get(authorization_id)
            if status in USABLE_AUTH_STATUSES:
                self.authorizations[authorization_id] = "VOIDED"
                self.voids.append(authorization_id)
                return "fake-debug"
            issue = {"CAPTURED": "PREVIOUSLY_CAPTURED", "VOIDED": "PREVIOUSLY_VOIDED",
                     "EXPIRED": "AUTHORIZATION_EXPIRED"}.get(status or "", "RESOURCE_NOT_FOUND")
            raise GatewayError("client", f"void failed: HTTP 422 {issue}", status_code=422, issue=issue)

        return self._run("void", request_id, go)  # type: ignore[return-value]

    def check(self) -> bool:
        return True


def build_gateway(settings: Settings) -> PaymentGateway:
    if settings.paypal_mode == "sandbox":
        return PayPalClient(settings)
    return FakePayPal()
