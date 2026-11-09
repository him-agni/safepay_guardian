"""Shared fixtures: a fresh SQLite file, the fake PayPal and a fixed-level risk engine per test."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.paypal import FakePayPal
from app.risk.stub import FixedAssessor
from app.state import PaymentService


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        database_path=str(tmp_path / "test.db"),
        paypal_mode="fake",
        hold_timeout_seconds=120,
        sweeper_interval_seconds=0,
        paypal_retry_backoff_seconds=0,
        inflight_wait_seconds=5,
        void_retry_seconds=0,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@dataclass
class Env:
    client: TestClient
    service: PaymentService
    paypal: FakePayPal
    risk: FixedAssessor

    def pay(self, level: str = "high", amount: str = "500.00", payee: str = "Officer Smith", **extra) -> dict:
        self.risk.level = level
        resp = self.client.post("/payments", json={"payee_name": payee, "amount": amount, **extra})
        assert resp.status_code == 201, resp.text
        return resp.json()

    def act(self, payment_id: str, action: str, **body):
        return self.client.post(f"/payments/{payment_id}/{action}", json=body or None)

    def get(self, payment_id: str) -> dict:
        return self.client.get(f"/payments/{payment_id}").json()

    def event_types(self, payment_id: str) -> list[str]:
        return [e["type"] for e in self.get(payment_id)["events"]]


@pytest.fixture
def env(tmp_path) -> Env:
    paypal = FakePayPal()
    risk = FixedAssessor("low")
    app = create_app(make_settings(tmp_path), gateway=paypal, assessor=risk)
    with TestClient(app) as client:
        yield Env(client, app.state.service, paypal, risk)
