"""Stage 5 · 并发、asyncio、HTTP —— 练习题。

运行：
    .\\.venv\\Scripts\\python.exe -m pytest stage5_async_http -q

提示：这些函数都是 async def，直接调用不会执行；测试里用 asyncio.run(...)。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


async def gather_with_limit(
    factories: Sequence[Callable[[], Awaitable[T]]],
    limit: int,
) -> list[T]:
    """并发执行多个协程工厂，最多同时运行 limit 个。

    规则：
        - limit < 1 -> 抛 ValueError
        - 空列表 -> 返回 []
        - 结果顺序必须与 factories 的顺序一致（不是完成顺序）
        - 任意一个抛异常 -> 异常向上传播（其余任务被取消也没关系）

    示例：
        async def make(i):
            await asyncio.sleep(0.01)
            return i

        await gather_with_limit([lambda: make(1), lambda: make(2)], limit=2)
        -> [1, 2]
    """
    raise NotImplementedError("TODO: 实现 gather_with_limit（Semaphore）")


async def with_timeout(coro: Awaitable[T], seconds: float) -> T:
    """在 seconds 秒内等待 coro 完成；超时抛内置 TimeoutError。

    规则：
        - seconds <= 0 -> 立即超时（抛 TimeoutError）
        - 正常完成 -> 返回 coro 的结果
        - 超时 -> 抛 TimeoutError（不要自己定义新异常）

    示例：
        await with_timeout(asyncio.sleep(0.01, result="ok"), 1.0)   -> "ok"
        await with_timeout(asyncio.sleep(1), 0.01)                -> TimeoutError
    """
    raise NotImplementedError("TODO: 实现 with_timeout")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    attempts: int = 3,
    base_delay: float = 0.01,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """异步重试。

    规则：
        - attempts 是总尝试次数，< 1 -> 抛 ValueError
        - 只捕获 exceptions 中指定的异常
        - 第 n 次失败后等待 base_delay * 2 ** (n - 1) 秒
        - base_delay <= 0 时不 sleep
        - 全部失败 -> 抛出最后一次异常
        - 其它异常直接向上抛，不重试

    示例：
        calls = 0
        async def flaky():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("not yet")
            return "ok"

        await retry_async(flaky, attempts=3, base_delay=0)   -> "ok"
    """
    raise NotImplementedError("TODO: 实现 retry_async")
