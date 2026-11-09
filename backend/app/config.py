"""App settings, read from environment variables and the repo-root .env file."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    ai_provider: Literal["gemini", "none"] = "none"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"
    ai_timeout_seconds: float = 8.0

    # Holds
    hold_timeout_seconds: int = 86400

    # App
    database_path: str = "data/safepay.db"
    cors_origins: str = "http://localhost:5173"

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
        return self.ai_provider == "gemini" and bool(self.gemini_api_key.get_secret_value())

    @property
    def database_file(self) -> Path:
        path = Path(self.database_path)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
