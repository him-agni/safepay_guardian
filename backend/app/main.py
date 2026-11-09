"""SafePay Guardian FastAPI app."""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings

app = FastAPI(title="SafePay Guardian", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Report configuration state. Never returns secret values.

    Phase 1 adds a live PayPal token check; Phase 2 adds an AI reachability check.
    """
    return {
        "status": "ok",
        "sandbox_only": True,
        "paypal": {"mode": settings.paypal_mode, "configured": settings.paypal_configured},
        "ai": {
            "provider": settings.ai_provider,
            "configured": settings.ai_configured,
            "mode": "hybrid" if settings.ai_configured else "rules_only",
        },
        "hold_timeout_seconds": settings.hold_timeout_seconds,
    }
