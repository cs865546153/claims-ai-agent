# Stage 5 · 并发、asyncio、HTTP

> 目标：能安全地并发调用模型/外部接口，做到"快、稳、不雪崩"。
> 预计：5 天（PLAN.md Day 16~20）。

---

## 1. 先搞清楚三种并发

| 方式 | 适用 | 代价 | 典型场景 |
|---|---|---|---|
| 多线程 `threading` | IO 密集 | 线程内存、切换开销 | 阻塞 SDK、文件 IO |
| 多进程 `multiprocessing` | CPU 密集 | 进程内存、序列化 | 图像处理、批量计算 |
| 协程 `asyncio` | IO 密集、高并发 | 全链路必须 async | 调 LLM、HTTP、数据库 |

**GIL（全局解释器锁）**：同一时刻只有一个线程执行 Python 字节码。

- IO 等待时会释放 GIL，所以多线程对 IO 有效。
- CPU 计算不会释放 GIL，所以多线程做计算 ≈ 单线程。
- 大数据场景：真正的并行交给 Spark/Flink，不要用 Python 多线程硬扛。

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=8) as pool:
    results = list(pool.map(fetch_one, urls))
```

**Java 对照**：`ThreadPoolExecutor` / `CompletableFuture` 能做的事，Python 用 `asyncio` 做 IO、用 `multiprocessing` 做 CPU。

---

## 2. 协程基础

```python
import asyncio

async def fetch_one(i: int) -> int:
    await asyncio.sleep(0.1)      # 模拟 IO；注意不是 time.sleep
    return i

async def main() -> None:
    result = await fetch_one(1)   # 调用 async 函数返回协程对象，await 才执行

asyncio.run(main())               # 程序入口：创建事件循环，跑完关闭
```

**关键认知**

- `async def` 函数调用后**不会执行**，只返回协程对象。
- `await` 表示"这里可能等待，把控制权让给事件循环"。
- 事件循环是单线程的：一个协程阻塞，所有协程都停。
- **不要**在协程里调用 `time.sleep`、`requests.get`、同步数据库驱动。
  - 必须调用时：`await asyncio.to_thread(blocking_func, ...)`。

```python
# 错误：整个服务卡住 3 秒
async def bad() -> None:
    time.sleep(3)

# 正确
async def good() -> None:
    await asyncio.to_thread(time.sleep, 3)
```

---

## 3. 并发执行：gather / TaskGroup

```python
# 方式一：gather（最常用）
results = await asyncio.gather(*(fetch_one(i) for i in range(3)))

# 方式二：TaskGroup（3.11+，异常处理更清晰）
async with asyncio.TaskGroup() as tg:
    tasks = [tg.create_task(fetch_one(i)) for i in range(3)]
results = [t.result() for t in tasks]
```

**gather 的坑**

- 默认"一个失败，整体失败"，但其它任务**不会自动取消**（除非你取消）。
- 想收集全部结果（包括异常）：`await asyncio.gather(..., return_exceptions=True)`。
- 返回顺序 = 传入顺序，不是完成顺序。

### 限流：Semaphore

```python
semaphore = asyncio.Semaphore(5)

async def limited(url: str) -> dict:
    async with semaphore:
        return await fetch(url)
```

**为什么必须限流**：模型服务和下游接口都有 QPS 限制；1000 个并发请求会让对方 429，也会把自己的连接池打满。

---

## 4. 超时与取消

```python
# 方式一
try:
    result = await asyncio.wait_for(fetch(url), timeout=10)
except TimeoutError:
    ...

# 方式二（3.11+，推荐，语义更清楚）
async with asyncio.timeout(10):
    result = await fetch(url)
```

- 超时会**取消**被等待的协程（抛 `CancelledError`），要确保清理逻辑放在 `finally`。
- 取消不是异常处理：不要 `except Exception` 把 `CancelledError` 吞掉。
- 一个请求的总超时 ≠ 单次调用超时。重试 3 次、每次 10 秒，总耗时可能 30 秒+。

---

## 5. 重试与退避

```python
async def retry_async(fn, attempts=3, base_delay=0.5):
    for i in range(attempts):
        try:
            return await fn()
        except (TimeoutError, httpx.HTTPError) as e:
            if i == attempts - 1:
                raise
            await asyncio.sleep(base_delay * 2**i)
```

**原则**

- 只重试可重试错误：超时、429、500/502/503/504。
- 不要重试 400/401/403/422（重试多少次都一样）。
- 指数退避 + 抖动（jitter），避免同时重试。
- 重试要有总预算，不能无限叠加重试。

---

## 6. httpx：同步与异步

```python
import httpx

# 同步
with httpx.Client(timeout=10) as client:
    resp = client.get("https://example.com/api")
    resp.raise_for_status()
    data = resp.json()

# 异步（Agent 项目首选）
async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
    resp = await client.get(url)
    resp.raise_for_status()
    data = resp.json()
```

| 配置 | 含义 |
|---|---|
| `connect` | 建立连接超时 |
| `read` | 等待响应数据超时 |
| `write` | 发送请求体超时 |
| `pool` | 等待连接池空闲超时 |
| `limits=httpx.Limits(max_connections=20)` | 连接池上限 |

**必须做**：超时、`raise_for_status()`、异常分类、日志（URL、状态码、耗时、trace_id）。

---

## 7. 流式输出（SSE / stream）

LLM 的流式响应是"边生成边返回"，通常用 SSE（`text/event-stream`）。

```python
# OpenAI 兼容接口
stream = client.chat.completions.create(..., stream=True)
for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.content:
        print(delta.content, end="", flush=True)
```

```python
# 原始 SSE
async with client.stream("GET", url) as resp:
    async for line in resp.aiter_lines():
        if line.startswith("data: "):
            payload = line[6:]
            if payload == "[DONE]":
                break
            print(payload)
```

**注意**

- 流式响应不能重试（已经输出了一半，重试会重复内容）。
- 客户端断开要取消上游请求，否则白花钱。
- 流式过程中出错，要发一条错误事件再关闭，不能直接断连。

---

## 8. 常见坑

1. **在协程里调用阻塞函数**：整个事件循环停摆。
2. **忘记 `await`**：协程对象没执行，还可能出现 "coroutine was never awaited" 警告。
3. **`asyncio.run` 嵌套**：事件循环不能再套一个。
4. **`gather` 不限流**：1000 个请求同时打出去。
5. **超时只设了 connect**：读数据阶段可能永远挂着。
6. **重试放大了故障**：下游已经 500，你还重试 5 次。
7. **共享 `AsyncClient` 在事件循环外创建**：绑定错循环。
8. **CancelledError 被吞**：服务停止时无法及时退出。

---

## 9. 本阶段练习

| 函数 | 练什么 | Agent 场景 |
|---|---|---|
| `gather_with_limit` | gather + Semaphore | 并发调多个模型/工具 |
| `with_timeout` | 超时与取消 | 防止请求挂死 |
| `retry_async` | 异步重试 + 退避 | 调模型失败重试 |

额外：跑 `demo_http.py` 看真实并发效果（默认离线演示，`--real` 需要网络）。

验收：

```powershell
.\.venv\Scripts\python.exe -m pytest stage5_async_http -q
.\.venv\Scripts\python.exe stage5_async_http\demo_http.py
```

**自检问题**

1. GIL 对 IO 密集和 CPU 密集分别意味着什么？
2. `asyncio.gather` 的结果顺序是完成顺序吗？
3. 为什么 `Semaphore` 要放在 `await` 外层？
4. 超时后协程发生了什么？`CancelledError` 要捕获吗？
