"""Stage 5 自动判分。不要修改本文件。"""

from __future__ import annotations

import asyncio

import pytest

from stage5_async_http.exercises import gather_with_limit, retry_async, with_timeout


# ---------------------------------------------------------------------------
# gather_with_limit
# ---------------------------------------------------------------------------
def test_gather_with_limit_keeps_order() -> None:
    async def make(value: int, delay: float) -> int:
        await asyncio.sleep(delay)
        return value

    factories = [
        lambda: make(0, 0.03),
        lambda: make(1, 0.01),
        lambda: make(2, 0.02),
    ]
    assert asyncio.run(gather_with_limit(factories, limit=3)) == [0, 1, 2]


def test_gather_with_limit_respects_concurrency() -> None:
    active = 0
    peak = 0

    async def make(value: int) -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return value

    factories = [lambda value=i: make(value) for i in range(12)]
    result = asyncio.run(gather_with_limit(factories, limit=3))

    assert result == list(range(12))
    assert peak <= 3
    assert peak > 1


def test_gather_with_limit_empty() -> None:
    assert asyncio.run(gather_with_limit([], limit=5)) == []


def test_gather_with_limit_invalid_limit() -> None:
    with pytest.raises(ValueError):
        asyncio.run(gather_with_limit([], limit=0))
    with pytest.raises(ValueError):
        asyncio.run(gather_with_limit([], limit=-1))


def test_gather_with_limit_limit_larger_than_tasks() -> None:
    async def make(value: int) -> int:
        return value

    factories = [lambda value=i: make(value) for i in range(3)]
    assert asyncio.run(gather_with_limit(factories, limit=100)) == [0, 1, 2]


def test_gather_with_limit_propagates_exception() -> None:
    async def boom() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        asyncio.run(gather_with_limit([boom], limit=1))


# ---------------------------------------------------------------------------
# with_timeout
# ---------------------------------------------------------------------------
def test_with_timeout_returns_result() -> None:
    async def fast() -> str:
        await asyncio.sleep(0.001)
        return "ok"

    assert asyncio.run(with_timeout(fast(), 1.0)) == "ok"


def test_with_timeout_raises_timeout_error() -> None:
    with pytest.raises(TimeoutError):
        asyncio.run(with_timeout(asyncio.sleep(1.0), 0.01))


def test_with_timeout_zero_seconds() -> None:
    with pytest.raises(TimeoutError):
        asyncio.run(with_timeout(asyncio.sleep(0), 0))


def test_with_timeout_propagates_other_exceptions() -> None:
    async def boom() -> None:
        raise ValueError("bad")

    with pytest.raises(ValueError):
        asyncio.run(with_timeout(boom(), 1.0))


# ---------------------------------------------------------------------------
# retry_async
# ---------------------------------------------------------------------------
def test_retry_async_succeeds_after_failures() -> None:
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("not yet")
        return "ok"

    assert asyncio.run(retry_async(flaky, attempts=3, base_delay=0)) == "ok"
    assert calls == 3


def test_retry_async_exhausted_raises_last() -> None:
    calls = 0

    async def always_fail() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError(f"failure {calls}")

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(retry_async(always_fail, attempts=2, base_delay=0))

    assert calls == 2
    assert "failure 2" in str(exc_info.value)


def test_retry_async_only_catches_configured_exceptions() -> None:
    calls = 0

    async def raises_type_error() -> None:
        nonlocal calls
        calls += 1
        raise TypeError("not retryable")

    with pytest.raises(TypeError):
        asyncio.run(
            retry_async(raises_type_error, attempts=3, base_delay=0, exceptions=(ValueError,))
        )
    assert calls == 1


def test_retry_async_invalid_attempts() -> None:
    async def noop() -> None:
        return None

    with pytest.raises(ValueError):
        asyncio.run(retry_async(noop, attempts=0))


def test_retry_async_returns_value() -> None:
    async def value() -> int:
        return 42

    assert asyncio.run(retry_async(value, attempts=1)) == 42
