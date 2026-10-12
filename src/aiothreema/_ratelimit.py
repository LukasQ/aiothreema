"""Client-side rate limiting for Gateway requests."""

from __future__ import annotations

import asyncio
from asyncio import sleep
from collections import deque
from time import monotonic


class RateLimiter:
    """Sliding-window limiter allowing `max_requests` per `period` seconds.

    Waiters are served in FIFO order. `pause()` additionally holds back all
    requests for a while, e.g. after the Gateway answered with HTTP 429.
    """

    def __init__(self, max_requests: int, period: float = 1.0) -> None:
        """Initialize the rate limiter."""
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1")
        if period <= 0:
            raise ValueError("period must be positive")
        self._max_requests = max_requests
        self._period = period
        self._timestamps: deque[float] = deque()
        self._paused_until = 0.0
        self._lock = asyncio.Lock()

    def pause(self, delay: float) -> None:
        """Hold back all requests for at least `delay` seconds."""
        self._paused_until = max(self._paused_until, monotonic() + delay)

    async def acquire(self) -> None:
        """Wait until a request may be sent, and account for it."""
        async with self._lock:
            while True:
                now = monotonic()
                while self._timestamps and now - self._timestamps[0] >= self._period:
                    self._timestamps.popleft()

                wait = self._paused_until - now
                if len(self._timestamps) >= self._max_requests:
                    wait = max(wait, self._timestamps[0] + self._period - now)
                if wait <= 0:
                    self._timestamps.append(now)
                    return
                await sleep(wait)
