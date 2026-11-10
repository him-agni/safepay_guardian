"""Request models for the API."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

MAX_AMOUNT = Decimal("10000.00")


class CreatePaymentRequest(BaseModel):
    payee_name: str = Field(min_length=1, max_length=80)
    payee_email: Optional[str] = Field(default=None, max_length=120)
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, description="US dollars, at most 2 decimal places")
    note: str = Field(default="", max_length=500)
    message_text: str = Field(default="", max_length=5000)
    screenshot_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{32}\.(png|jpg|webp)$")

    @field_validator("payee_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("payee name is required")
        return v.strip()

    @field_validator("amount")
    @classmethod
    def _two_decimals(cls, v: Decimal) -> Decimal:
        if v.as_tuple().exponent < -2:  # type: ignore[operator]
            raise ValueError("amount can have at most 2 decimal places")
        return v

    @property
    def amount_cents(self) -> int:
        return int((self.amount * 100).to_integral_value())


class AssessRequest(BaseModel):
    message_text: str = Field(default="", max_length=5000)
    note: str = Field(default="", max_length=500)
    amount: Optional[Decimal] = Field(default=None, ge=0, le=MAX_AMOUNT)
    payee_name: str = Field(default="", max_length=80)

    @property
    def amount_cents(self) -> int:
        return int((self.amount * 100).to_integral_value()) if self.amount is not None else 0


class ScreenshotRequest(BaseModel):
    image_base64: str = Field(min_length=8, max_length=6_000_000, description="base64 or a data: URL")
    mime_type: str = Field(max_length=40)


class DecisionRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class MessageRequest(BaseModel):
    from_role: Literal["sender", "guardian"]
    body: str = Field(min_length=1, max_length=1000)
