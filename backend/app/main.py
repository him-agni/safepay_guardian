"""SafePay Guardian FastAPI app.

Only this backend talks to PayPal and the AI model. The React screens poll it every 3 seconds.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import activity_query
from .config import Settings, get_settings
from .models import AssessRequest, CreatePaymentRequest, DecisionRequest, MessageRequest, ScreenshotRequest
from .paypal import PaymentGateway, build_gateway
from .risk.engine import build_assessor
from .risk.types import Assessor
from .state import SCREENSHOT_MEDIA, PaymentError, PaymentService

log = logging.getLogger("safepay")


def create_app(
    settings: Settings | None = None,
    *,
    gateway: PaymentGateway | None = None,
    assessor: Assessor | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    gateway = gateway or build_gateway(settings)
    assessor = assessor or build_assessor(settings)
    service = PaymentService(settings, gateway, assessor)
    health_cache: dict = {"at": 0.0, "paypal_reachable": None, "ai_reachable": None}
    ai_provider = getattr(assessor, "provider", None)

    async def sweeper() -> None:
        while True:
            await asyncio.sleep(settings.sweeper_interval_seconds)
            try:
                await asyncio.to_thread(service.sweep)
            except Exception:  # keep the loop alive; the next tick retries
                log.exception("sweep failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(service.recover)
        task = asyncio.create_task(sweeper()) if settings.sweeper_interval_seconds > 0 else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="SafePay Guardian", version="0.2.0", lifespan=lifespan)
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(PaymentError)
    async def payment_error(_: Request, exc: PaymentError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message, "payment": exc.payment},
        )

    @app.get("/health")
    def health() -> dict:
        """Configuration state plus cached PayPal and AI reachability checks. Never returns secret values."""
        if time.monotonic() - health_cache["at"] > 60:
            health_cache["paypal_reachable"] = gateway.check()
            health_cache["ai_reachable"] = ai_provider.check() if ai_provider is not None else False
            health_cache["at"] = time.monotonic()
        return {
            "status": "ok",
            "sandbox_only": True,
            "paypal": {
                "mode": settings.paypal_mode,
                "configured": settings.paypal_configured,
                "reachable": health_cache["paypal_reachable"],
            },
            "ai": {
                "provider": settings.ai_provider,
                "configured": ai_provider is not None,
                "model": getattr(ai_provider, "model", None),
                "reachable": health_cache["ai_reachable"],
                "mode": ("replay" if settings.ai_provider == "replay" else "hybrid")
                if ai_provider is not None and health_cache["ai_reachable"] else "rules_only",
            },
            "hold_timeout_seconds": settings.hold_timeout_seconds,
        }

    @app.post("/payments", status_code=201)
    def create_payment(body: CreatePaymentRequest) -> dict:
        """Run the risk engine, authorize on PayPal, then capture, warn or hold by risk level."""
        return service.create_payment(
            payee_name=body.payee_name, payee_email=body.payee_email, amount_cents=body.amount_cents,
            note=body.note, message_text=body.message_text, screenshot_id=body.screenshot_id,
        )

    @app.get("/payments")
    def list_payments(status: Optional[str] = None, queue: Optional[str] = None, limit: int = 200) -> dict:
        statuses = [s.strip().upper() for s in status.split(",")] if status else None
        return {"payments": service.list_payments(statuses=statuses, queue=queue, limit=min(limit, 500))}

    @app.post("/activity/ask")
    def ask_activity(body: activity_query.AskRequest) -> dict:
        """Turn a plain-English question into validated filters for the activity grid (read-only)."""
        result = activity_query.ask(ai_provider, body, date.today())
        service._event(None, "guardian", "activity.asked", {
            "question": body.question, "filters": len(result.filters), "ignored": len(result.ignored),
            "error": result.error is not None, "cached": result.cached, "latency_ms": result.latency_ms,
        })
        return result.as_dict()

    @app.post("/screenshots")
    def read_screenshot(body: ScreenshotRequest) -> dict:
        """Save a screenshot of the conversation and transcribe it for the sender to confirm."""
        return service.read_screenshot(body.image_base64, body.mime_type)

    @app.get("/screenshots/{screenshot_id}")
    def get_screenshot(screenshot_id: str) -> FileResponse:
        path = service.screenshot_file(screenshot_id)
        return FileResponse(path, media_type=SCREENSHOT_MEDIA[path.suffix.lstrip(".")],
                            headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/stats")
    def stats() -> dict:
        """Counts and totals for the guardian's Insights cards (seeded history excluded)."""
        return service.stats()

    @app.get("/payments/{payment_id}")
    def get_payment(payment_id: str) -> dict:
        return service.get_payment(payment_id)

    def _action(name: str, doc: str):
        def handler(payment_id: str, body: Optional[DecisionRequest] = None) -> dict:
            return service.act(payment_id, name, note=body.note if body else None)

        handler.__doc__ = doc
        handler.__name__ = f"{name}_payment"
        app.post(f"/payments/{{payment_id}}/{name}")(handler)

    _action("confirm", "Sender confirms a medium-risk warning, which captures.")
    _action("cancel", "Sender cancels a warned or held payment, which voids.")
    _action("approve", "Guardian approves a held payment, which captures (idempotent).")
    _action("decline", "Guardian declines a held payment, which voids (idempotent).")
    _action("retry", "Guardian retries a failed capture or void.")

    @app.post("/assess")
    def assess(body: AssessRequest) -> dict:
        """Run the risk engine on a message (and optional payment details) without creating a payment."""
        return service.assess_only(message_text=body.message_text, note=body.note,
                                   amount_cents=body.amount_cents, payee_name=body.payee_name)

    @app.post("/payments/{payment_id}/messages", status_code=201)
    def add_message(payment_id: str, body: MessageRequest) -> dict:
        return service.add_message(payment_id, body.from_role, body.body)

    return app


# Run with: uvicorn app.main:create_app --factory --port 8000
# (a factory, so importing this module in tests never touches the real database or PayPal)
