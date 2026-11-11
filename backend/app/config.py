"""App settings, read from environment variables and the repo-root .env file."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_HOSTS = {"api-m.sandbox.paypal.com", "api.sandbox.paypal.com"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PayPal
    paypal_mode: Literal["fake", "sandbox"] = "fake"
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_client_id: str = ""
    paypal_client_secret: SecretStr = SecretStr("")

    # Sandbox test card (payment_source.card)
    sandbox_card_number: SecretStr = SecretStr("")
    sandbox_card_expiry: str = ""  # YYYY-MM
    sandbox_card_security_code: SecretStr = SecretStr("")
    sandbox_card_name: str = ""

    # AI
    ai_provider: Literal["gemini", "replay", "none"] = "none"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.1-flash-lite"
    ai_timeout_seconds: float = Field(12.0, gt=0)
    ai_cache_dir: str = ""  # e.g. "eval/cache": reuse stored AI replies for identical prompts

    # Holds and background work
    hold_timeout_seconds: int = Field(86400, ge=1)
    sweeper_interval_seconds: float = Field(5.0, ge=0)  # 0 disables the background sweeper (tests)
    void_retry_seconds: float = Field(30.0, ge=0)  # wait before the sweeper retries a failed void
    stuck_after_seconds: float = Field(180.0, gt=0)  # in-flight payments older than this are resumed
    inflight_wait_seconds: float = Field(15.0, ge=0)  # a repeated decision waits this long for the first one
    capture_recheck_seconds: float = Field(20.0, ge=0)  # wait before the sweeper re-reads a pending capture
    # When the AI check did not run, a payment that rules alone call Low still asks the sender to confirm if the
    # payee is new or the amount is much larger than usual. Rules alone caught about half the held-out scams.
    confirm_when_ai_unavailable: bool = True
    auth_retry_seconds: float = Field(15.0, gt=0)  # wait before retrying an authorization PayPal never answered
    auth_give_up_seconds: float = Field(300.0, gt=0)  # then stop trying and report that the payment could not be started
    paypal_retry_backoff_seconds: float = Field(0.5, ge=0)

    # App
    database_path: str = "data/safepay.db"
    upload_dir: str = "data/uploads"  # screenshots the sender adds (git-ignored)
    max_screenshot_bytes: int = Field(4_000_000, gt=0)
    cors_origins: str = "http://localhost:5173"

    # Requests per minute per visitor (IP address); 0 turns a limit off. Generous for people, not for scripts.
    rate_limit_payments: int = Field(20, ge=0)  # POST /payments
    rate_limit_screenshots: int = Field(10, ge=0)  # POST /screenshots (uploads plus an AI call each)
    rate_limit_ai_checks: int = Field(20, ge=0)  # POST /assess and POST /activity/ask
    rate_limit_messages: int = Field(30, ge=0)  # POST /payments/{id}/messages

    @field_validator("sandbox_card_expiry")
    @classmethod
    def _normalise_expiry(cls, value: str) -> str:
        """Accept YYYY-MM, MM/YYYY or MM/YY; PayPal wants YYYY-MM."""
        value = value.strip()
        if not value:
            return value
        if m := re.fullmatch(r"(\d{4})-(\d{2})", value):
            year, month = m.groups()
        elif m := re.fullmatch(r"(\d{1,2})\s*/\s*(\d{2}|\d{4})", value):
            month, year = m.groups()
            year = year if len(year) == 4 else "20" + year
        else:
            raise ValueError("SANDBOX_CARD_EXPIRY must look like YYYY-MM, MM/YYYY or MM/YY")
        if not 1 <= int(month) <= 12:
            raise ValueError("SANDBOX_CARD_EXPIRY month must be 01 to 12")
        return f"{year}-{int(month):02d}"

    @model_validator(mode="after")
    def _sandbox_only(self) -> "Settings":
        """This app moves test money only: in sandbox mode the PayPal address must be a PayPal sandbox host."""
        if self.paypal_mode == "sandbox" and not self.sandbox_host_ok:
            raise ValueError(
                "PAYPAL_BASE_URL must be the PayPal sandbox (https://api-m.sandbox.paypal.com). "
                "This app only moves test money, so it refuses to talk to any other PayPal address."
            )
        return self

    @property
    def sandbox_host_ok(self) -> bool:
        url = urlparse(self.paypal_base_url)
        return url.scheme == "https" and url.hostname in SANDBOX_HOSTS and not url.username

    @property
    def sandbox_only(self) -> bool:
        """True when no real money can move: the fake PayPal, or a checked PayPal sandbox address."""
        return self.paypal_mode == "fake" or self.sandbox_host_ok

    @property
    def paypal_configured(self) -> bool:
        if self.paypal_mode == "fake":
            return True
        return bool(
            self.paypal_client_id
            and self.paypal_client_secret.get_secret_value()
            and self.sandbox_card_number.get_secret_value()
            and self.sandbox_card_expiry
        )

    @property
    def ai_configured(self) -> bool:
        if self.ai_provider == "replay":
            return bool(self.ai_cache_dir)
        return self.ai_provider == "gemini" and bool(self.gemini_api_key.get_secret_value())

    @property
    def database_file(self) -> Path:
        path = Path(self.database_path)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
