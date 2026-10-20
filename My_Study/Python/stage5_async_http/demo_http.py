"""离线/在线并发演示。

用法：
    .\\.venv\\Scripts\\python.exe stage5_async_http\\demo_http.py
    .\\.venv\\Scripts\\python.exe stage5_async_http\\demo_http.py --real
    .\\.venv\\Scripts\\python.exe stage5_async_http\\demo_http.py --stream https://example.com/sse
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx


async def fake_call(name: str, delay: float, semaphore: asyncio.Semaphore) -> str:
    async with semaphore:
        started = time.perf_counter()
        await asyncio.sleep(delay)
        elapsed = (time.perf_counter() - started) * 1000
        return f"{name} 完成，耗时 {elapsed:.0f} ms"


async def offline_demo(limit: int = 3) -> None:
    """不联网：对比串行与限流并发的总耗时。"""
    jobs = [(f"task-{i}", 0.2 + i * 0.05) for i in range(6)]
    semaphore = asyncio.Semaphore(limit)

    started = time.perf_counter()
    for name, delay in jobs:
        await fake_call(name, delay, semaphore)
    sequential = time.perf_counter() - started

    started = time.perf_counter()
    results = await asyncio.gather(*(fake_call(name, delay, semaphore) for name, delay in jobs))
    concurrent = time.perf_counter() - started

    print(f"串行耗时: {sequential:.2f}s")
    print(f"并发耗时（limit={limit}）: {concurrent:.2f}s")
    for line in results:
        print(" ", line)


async def fetch_one(
    client: httpx.AsyncClient,
    url: str,
    semaphore: asyncio.Semaphore,
) -> str:
    async with semaphore:
        started = time.perf_counter()
        try:
            response = await client.get(url)
            response.raise_for_status()
            elapsed = (time.perf_counter() - started) * 1000
            return (
                f"{url} -> {response.status_code}, {len(response.content)} bytes, {elapsed:.0f} ms"
            )
        except httpx.HTTPError as e:
            return f"{url} -> 失败: {type(e).__name__}: {e}"


async def real_demo(urls: list[str], limit: int = 3) -> None:
    """联网：并发请求多个 URL，注意超时与异常都被处理。"""
    semaphore = asyncio.Semaphore(limit)
    timeout = httpx.Timeout(10.0, connect=3.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        started = time.perf_counter()
        results = await asyncio.gather(*(fetch_one(client, url, semaphore) for url in urls))
        elapsed = time.perf_counter() - started

    print(f"共 {len(urls)} 个请求，总耗时 {elapsed:.2f}s")
    for line in results:
        print(" ", line)


async def stream_demo(url: str) -> None:
    """逐行读取 SSE，只打印前 20 行。"""
    timeout = httpx.Timeout(30.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            count = 0
            async for line in response.aiter_lines():
                if not line:
                    continue
                print(line[:200])
                count += 1
                if count >= 20:
                    break


def main() -> None:
    parser = argparse.ArgumentParser(description="asyncio + httpx 演示")
    parser.add_argument("--real", action="store_true", help="真实请求 httpbin")
    parser.add_argument("--stream", metavar="URL", help="读取一个 SSE 地址")
    parser.add_argument("--limit", type=int, default=3, help="最大并发数")
    args = parser.parse_args()

    if args.stream:
        asyncio.run(stream_demo(args.stream))
    elif args.real:
        urls = [
            "https://httpbin.org/delay/1",
            "https://httpbin.org/json",
            "https://httpbin.org/uuid",
        ]
        asyncio.run(real_demo(urls, limit=args.limit))
    else:
        asyncio.run(offline_demo(limit=args.limit))


if __name__ == "__main__":
    main()
