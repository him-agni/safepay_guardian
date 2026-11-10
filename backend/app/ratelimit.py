"""Per-visitor rate limits for the endpoints that create things or call the AI.

The demo has no login, so a visitor is identified by IP address. Limits are generous: a person using
the app never meets them; a script flooding uploads, payments or AI calls does. In-memory sliding
window, one process (the demo runs a single uvicorn worker).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from fastapi import Request

from .state import PaymentError

WINDOW_SECONDS = 60.0


class TooManyRequests(PaymentError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, limits: dict[str, int], *, clock: Callable[[], float] = time.monotonic) -> None:
        self.limits = limits  # bucket -> requests allowed per minute; 0 or missing = unlimited
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()
        self._checks = 0

    def check(self, bucket: str, visitor: str) -> None:
        limit = self.limits.get(bucket, 0)
        if limit <= 0:
            return
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault((bucket, visitor), deque())
            while hits and hits[0] <= now - WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(hits[0] + WINDOW_SECONDS - now) + 1)
                raise TooManyRequests(
                    f"Too many requests. Please wait {retry_after} seconds and try again.", retry_after=retry_after)
            hits.append(now)
            self._checks += 1
            if self._checks % 500 == 0:  # forget visitors who have gone quiet
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - WINDOW_SECONDS}

    def dependency(self, bucket: str):
        """A FastAPI dependency that counts one request against `bucket` for the caller's IP address."""

        def limited(request: Request) -> None:
            self.check(bucket, request.client.host if request.client else "unknown")

        return limited
