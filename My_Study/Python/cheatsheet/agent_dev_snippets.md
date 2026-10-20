# Agent 开发常用 Python 片段

> 用途：写业务代码时直接抄结构，不用从零想。
> 约定：示例中的 `client` 是 `openai.OpenAI` 实例；异步版本是 `AsyncOpenAI`。

---

## 1. 配置：.env + pydantic-settings

```python
# settings.py
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: SecretStr
    llm_model: str = "deepseek-chat"
    request_timeout: float = 30.0
    max_retries: int = 3


settings = Settings()          # 缺 llm_api_key 会在启动时立刻报错，而不是运行到一半
```

```python
# 使用
from settings import settings

client = OpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key.get_secret_value(),
    timeout=settings.request_timeout,
)
```

**原则**：配置在启动时校验并失败（fail fast），不要把 `os.getenv` 散落在业务代码里。

---

## 2. 日志：带 trace_id 的结构化日志

```python
import logging
import sys
import uuid

logger = logging.getLogger("agent")


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(trace_id)s] %(message)s")
    )
    logger.handlers[:] = [handler]          # 幂等：重复调用不叠加 handler
    logger.setLevel(level)
    logger.propagate = False


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True


logger.addFilter(TraceIdFilter())
logger.info("agent start", extra={"trace_id": uuid.uuid4().hex[:8]})
```

> 生产环境更推荐 `structlog` 或 JSON formatter，便于 ELK/Loki 检索。
> 日志里**不要打印完整 prompt 和密钥**，必要时截断到 200 字符。

---

## 3. 工具参数：pydantic 校验

```python
from pydantic import BaseModel, Field, ValidationError


class QueryClaimArgs(BaseModel):
    claim_id: str = Field(min_length=3, max_length=32)
    include_history: bool = False


def query_claim(claim_id: str, include_history: bool = False) -> dict:
    ...


def run_tool(raw_args: dict) -> dict:
    try:
        args = QueryClaimArgs.model_validate(raw_args)
    except ValidationError as e:
        return {"error": "invalid_arguments", "detail": e.errors(include_url=False)}
    return query_claim(**args.model_dump())
```

---

## 4. 工具定义与分发（OpenAI / DeepSeek 格式）

```python
import json
from collections.abc import Callable, Mapping
from typing import Any

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_claim_status",
            "description": "根据理赔单号查询当前状态。只读操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string", "description": "理赔单号，例如 CLM-2024-001"},
                },
                "required": ["claim_id"],
                "additionalProperties": False,
            },
        },
    }
]

REGISTRY: dict[str, Callable[..., Any]] = {
    "get_claim_status": lambda claim_id: {"claim_id": claim_id, "status": "reviewing"},
}


def dispatch(name: str, raw_arguments: str | dict | None) -> str:
    """永远返回字符串，失败也返回结构化错误——Agent Loop 不能因为一个工具挂掉。"""
    if raw_arguments in (None, ""):
        arguments: dict[str, Any] = {}
    elif isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"arguments 不是合法 JSON: {e}"}, ensure_ascii=False)
    else:
        arguments = raw_arguments

    func = REGISTRY.get(name)
    if func is None:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)

    try:
        result = func(**arguments)
    except TypeError as e:          # 参数名/数量不对
        return json.dumps({"error": f"参数错误: {e}"}, ensure_ascii=False)
    except Exception as e:          # 工具内部异常
        return json.dumps({"error": f"工具执行失败: {e}"}, ensure_ascii=False)

    return json.dumps(result, ensure_ascii=False)
```

---

## 5. Agent Loop（最小可用版）

```python
def run_agent(llm, messages: list[dict], tools: list[dict], max_steps: int = 8) -> list[dict]:
    for _ in range(max_steps):
        reply = llm(messages, tools=tools)          # 返回 assistant message dict
        messages.append(reply)

        tool_calls = reply.get("tool_calls") or []
        if not tool_calls:
            return messages                          # 模型给出最终回答

        for call in tool_calls:
            fn = call["function"]
            content = dispatch(fn["name"], fn.get("arguments"))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": fn["name"],
                    "content": content,
                }
            )
    raise RuntimeError(f"超过最大步数 {max_steps}，可能存在工具死循环")
```

**四个必须有的保护**

1. `max_steps`：防死循环。
2. 工具异常转错误字符串：让模型有机会自我修正。
3. 参数校验：模型会给错参数名/类型。
4. 日志：每轮记录工具名、耗时、结果长度。

---

## 6. 异步并发 + 超时 + 重试

```python
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    attempts: int = 3,
    base_delay: float = 0.5,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return await fn()
        except exceptions as e:
            last = e
            if i < attempts - 1:
                await asyncio.sleep(base_delay * (2**i))
    assert last is not None
    raise last


async def call_many(urls: list[str], limit: int = 5, timeout: float = 10.0) -> list[dict]:
    sem = asyncio.Semaphore(limit)

    async def one(url: str) -> dict:
        async with sem:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async def do() -> dict:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.json()

                return await retry_async(do, exceptions=(httpx.HTTPError,))

    return await asyncio.gather(*(one(u) for u in urls))
```

**注意**

- `AsyncClient` 应该在循环外创建并复用（连接池），上面的写法是演示；生产代码放到 `async with` 外层。
- 只重试**可重试**错误：超时、429、5xx；不要重试 400/401。
- 加抖动（jitter）避免惊群：`delay * (0.5 + random.random())`。

---

## 7. 从 LLM 输出里抠 JSON

```python
import json
import re


class JsonExtractError(ValueError):
    pass


def extract_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise JsonExtractError("没有找到 JSON 对象")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as e:
        raise JsonExtractError(f"JSON 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise JsonExtractError("顶层不是 object")
    return data
```

> 更稳的做法：让模型走 **structured outputs / JSON mode**，再用 pydantic 校验。
> 不要用正则去"修复" JSON（单引号、尾逗号），失败的输入应该重试或降级。

---

## 8. 上下文裁剪（token 预算）

```python
def truncate_messages(
    messages: list[dict],
    max_tokens: int,
    count_tokens,
    keep_system: bool = True,
) -> list[dict]:
    """保留 system + 最近的若干条，保证总 token <= max_tokens。"""
    system = []
    rest = messages
    if keep_system and messages and messages[0].get("role") == "system":
        system, rest = [messages[0]], messages[1:]

    kept: list[dict] = []
    used = sum(count_tokens(m) for m in system)
    for msg in reversed(rest):
        cost = count_tokens(msg)
        if used + cost > max_tokens:
            break
        kept.append(msg)
        used += cost
    return system + list(reversed(kept))
```

**坑**

- 不要拆散 `assistant(tool_calls)` 和对应的 `tool` 消息，否则 API 会报 400。
- system prompt 通常必须保留。
- 估算 token 可以用 `tiktoken`，或用 `len(text) / 2` 粗估（中文约 1 字 ≈ 1 token）。

---

## 9. 流式输出

```python
stream = client.chat.completions.create(
    model=settings.llm_model,
    messages=messages,
    stream=True,
    temperature=0.2,
)
for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.content:
        print(delta.content, end="", flush=True)
```

FastAPI SSE：

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()


@app.post("/chat")
async def chat(payload: dict):
    async def event_stream():
        async for chunk in async_llm_stream(payload["message"]):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

**流式注意**：前端断开要能取消上游请求；流式过程中出错要发一条 `data: {"error": ...}`，不能直接断连。

---

## 10. 用假 LLM 测试（不花钱、不联网）

```python
class FakeLLM:
    def __init__(self, replies: list[dict]):
        self._replies = list(replies)
        self.calls: list[list[dict]] = []

    def __call__(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        return self._replies.pop(0)


def test_agent_calls_tool_then_answers():
    fake = FakeLLM(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "add", "arguments": '{"a": 1, "b": 2}'},
                    }
                ],
            },
            {"role": "assistant", "content": "结果是 3"},
        ]
    )

    messages = run_agent(fake, [{"role": "user", "content": "1+2?"}], tools=[], max_steps=3)

    assert messages[-1]["content"] == "结果是 3"
    assert messages[-2]["role"] == "tool"
    assert json.loads(messages[-2]["content"]) == 3
    assert len(fake.calls) == 2
```

**原则**：业务逻辑与模型客户端解耦（传入 callable），测试只验证"消息如何流转"，不验证模型聪不聪明。

---

## 11. 错误分类（决定是否重试）

| 错误 | 典型状态码 | 处理 |
|---|---|---|
| 参数错误 | 400 / 422 | 不重试，修代码或让模型修正 |
| 认证失败 | 401 / 403 | 不重试，告警 |
| 限流 | 429 | 退避重试 + 降低并发 |
| 服务端错误 | 500 / 502 / 503 | 重试 2~3 次 |
| 超时 | - | 重试，必要时降级到小模型 |
| 上下文超长 | 400 | 裁剪历史 / 摘要 |
| 内容过滤 | 400 | 不重试，走人工/兜底话术 |

```python
RETRYABLE = {429, 500, 502, 503, 504}
```

---

## 12. 推荐的单文件结构

```
agent/
├── settings.py        # 配置
├── schemas.py         # pydantic 请求/响应/工具参数
├── tools.py           # 工具函数 + schema + registry
├── llm.py             # 模型客户端封装（超时/重试/日志）
├── loop.py            # Agent Loop
├── prompts/           # prompt 模板（不要硬编码在业务里）
└── api.py             # FastAPI 路由
```

> 先写单文件跑通，再按上面拆。**不要一开始就上框架。**

---

## 13. 成本与可观测性

```python
import time

start = time.perf_counter()
reply = client.chat.completions.create(...)
elapsed = time.perf_counter() - start

logger.info(
    "llm call done",
    extra={
        "trace_id": trace_id,
        "model": reply.model,
        "prompt_tokens": reply.usage.prompt_tokens,
        "completion_tokens": reply.usage.completion_tokens,
        "elapsed_ms": round(elapsed * 1000),
    },
)
```

必须记录的指标：**耗时、token 数、工具调用次数、失败率、每轮步数**。
出现"Agent 变慢/变贵"时，先看这四个数，不要先改 prompt。
