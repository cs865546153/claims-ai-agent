"""Stage 5 参考答案与讲解。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 1. gather_with_limit
# ---------------------------------------------------------------------------
# 关键点：
#   - Semaphore 必须包住"整个 await 过程"，而不是只包创建任务
#   - 用"协程工厂"（Callable[[], Awaitable]）而不是协程对象：
#     协程对象只能 await 一次，工厂可以在每次调用时创建新的
#   - asyncio.gather 的返回顺序 = 传入顺序
#   - 先 await gather 再 list()，不要返回生成器


async def gather_with_limit(
    factories: Sequence[Callable[[], Awaitable[T]]],
    limit: int,
) -> list[T]:
    if limit < 1:
        raise ValueError(f"limit 必须 >= 1，当前为 {limit}")

    semaphore = asyncio.Semaphore(limit)

    async def run(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    return list(await asyncio.gather(*(run(f) for f in factories)))


# 如果不需要限流，直接：
# results = await asyncio.gather(*(f() for f in factories))


# ---------------------------------------------------------------------------
# 2. with_timeout
# ---------------------------------------------------------------------------
# 关键点：
#   - asyncio.wait_for 超时后会取消协程并抛 TimeoutError（3.11+ 是内置 TimeoutError）
#   - timeout<=0 会立即超时
#   - 不要用 try/except Exception 包住，否则会把 CancelledError 一起吞掉


async def with_timeout(coro: Awaitable[T], seconds: float) -> T:
    return await asyncio.wait_for(coro, timeout=seconds)


# 3.11+ 也可以写：
# async with asyncio.timeout(seconds):
#     return await coro


# ---------------------------------------------------------------------------
# 3. retry_async
# ---------------------------------------------------------------------------
# 关键点：
#   - 用 for 控制"总尝试次数"，最后一次失败直接 break，避免多睡一次
#   - 指数退避：0.5, 1, 2, 4...
#   - 只捕获指定异常；CancelledError 属于 BaseException，不会被误吞
#   - 生产环境加 jitter：delay * random.uniform(0.5, 1.5)


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    attempts: int = 3,
    base_delay: float = 0.01,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    if attempts < 1:
        raise ValueError(f"attempts 必须 >= 1，当前为 {attempts}")

    last_exc: BaseException | None = None

    for attempt in range(attempts):
        try:
            return await fn()
        except exceptions as e:
            last_exc = e
            if attempt == attempts - 1:
                break
            wait = base_delay * (2**attempt)
            if wait > 0:
                await asyncio.sleep(wait)

    assert last_exc is not None
    raise last_exc
