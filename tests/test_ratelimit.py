"""Unit tests for the client-side rate limiter."""

from __future__ import annotations

import asyncio

import pytest

from aiothreema._ratelimit import RateLimiter


class FakeClock:
    """A clock that only advances when the limiter sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Replace the limiter's clock and sleep with a fake."""
    fake = FakeClock()
    monkeypatch.setattr("aiothreema._ratelimit.monotonic", fake.monotonic)
    monkeypatch.setattr("aiothreema._ratelimit.sleep", fake.sleep)
    return fake


async def test_requests_within_limit_do_not_wait(clock: FakeClock) -> None:
    """Test requests up to the limit pass without waiting."""
    limiter = RateLimiter(3, period=1.0)
    for _ in range(3):
        await limiter.acquire()
    assert clock.sleeps == []


async def test_request_over_limit_waits_for_window(clock: FakeClock) -> None:
    """Test a request over the limit waits until the oldest one expires."""
    limiter = RateLimiter(2, period=1.0)
    await limiter.acquire()
    clock.now += 0.25
    await limiter.acquire()
    await limiter.acquire()
    assert clock.sleeps == [pytest.approx(0.75)]


async def test_window_slides(clock: FakeClock) -> None:
    """Test capacity is available again once the period has passed."""
    limiter = RateLimiter(2, period=1.0)
    await limiter.acquire()
    await limiter.acquire()
    clock.now += 1.0
    await limiter.acquire()
    await limiter.acquire()
    assert clock.sleeps == []


async def test_never_exceeds_limit_under_concurrency(clock: FakeClock) -> None:
    """Test concurrent callers are spread over multiple windows."""
    limiter = RateLimiter(5, period=1.0)
    granted: list[float] = []

    async def worker() -> None:
        await limiter.acquire()
        granted.append(clock.now)

    await asyncio.gather(*(worker() for _ in range(12)))

    assert len(granted) == 12
    for start in granted:
        assert sum(1 for t in granted if start <= t < start + 1.0) <= 5


async def test_pause_holds_back_requests(clock: FakeClock) -> None:
    """Test pause() delays the next request even if capacity is available."""
    limiter = RateLimiter(10, period=1.0)
    limiter.pause(5.0)
    await limiter.acquire()
    assert clock.sleeps == [pytest.approx(5.0)]


async def test_pause_does_not_shorten_existing_pause(clock: FakeClock) -> None:
    """Test a shorter pause does not override a longer one."""
    limiter = RateLimiter(10, period=1.0)
    limiter.pause(5.0)
    limiter.pause(1.0)
    await limiter.acquire()
    assert clock.sleeps == [pytest.approx(5.0)]


@pytest.mark.parametrize(("max_requests", "period"), [(0, 1.0), (1, 0.0)])
def test_invalid_arguments_rejected(max_requests: int, period: float) -> None:
    """Test invalid limiter settings are rejected."""
    with pytest.raises(ValueError):
        RateLimiter(max_requests, period)
