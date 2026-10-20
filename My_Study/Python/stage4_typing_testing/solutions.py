"""Stage 4 参考答案与讲解。"""

from __future__ import annotations

import functools
import json
import re
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypedDict, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

P = ParamSpec("P")
T = TypeVar("T")


# ---------------------------------------------------------------------------
# 1. extract_json
# ---------------------------------------------------------------------------
# 关键点：
#   - 模型的输出不可控：可能带 ```json 围栏、前后解释、甚至中文冒号
#   - 只做"提取"，不做"修复"：单引号/尾逗号属于非法 JSON，应该报错重试
#   - find("{") + rfind("}") 能覆盖绝大多数情况；字符串里的花括号也不怕，
#     因为我们要的是最外层的一对
#   - 不要用贪婪正则 r"\{.*\}" 配 re.DOTALL，遇到多个 JSON 会一次吞掉


class JsonExtractError(ValueError):
    """无法从文本中提取出合法 JSON object。"""


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()

    fence = re.match(r"^```[a-zA-Z]*\s*", cleaned)
    if fence:
        cleaned = cleaned[fence.end() :]
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise JsonExtractError(f"没有找到 JSON object: {text[:120]!r}")

    candidate = cleaned[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise JsonExtractError(f"JSON 解析失败: {e}") from e

    if not isinstance(data, dict):
        raise JsonExtractError("JSON 顶层必须是 object")
    return data


# ---------------------------------------------------------------------------
# 2. retry
# ---------------------------------------------------------------------------
# 关键点：
#   - 装饰器工厂模式：retry(...) 返回 decorator，decorator 返回 wrapper
#   - functools.wraps 保留 __name__/__doc__/__wrapped__，日志和调试都依赖它
#   - 用 for + 下标判断"是否最后一次"，比 while True 清晰
#   - 只捕获指定异常：把 400/401 也重试只会放大故障
#   - 生产环境要加 jitter，避免大量客户端同时重试（惊群）


def retry(
    times: int = 3,
    delay: float = 0.0,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    if times < 1:
        raise ValueError(f"times 必须 >= 1，当前为 {times}")

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            wait = delay
            last_exc: BaseException | None = None

            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == times - 1:
                        break
                    if wait > 0:
                        time.sleep(wait)
                    wait *= backoff

            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


# 生产环境更推荐 tenacity：
# from tenacity import retry, stop_after_attempt, wait_exponential
#
# @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5))
# def call_llm() -> str:
#     ...


# ---------------------------------------------------------------------------
# 3. parse_tool_call
# ---------------------------------------------------------------------------
# 关键点：
#   - 兼容两种形状，调用方就不用关心是 OpenAI 原生还是内部事件
#   - arguments 经常是"字符串里的 JSON"，空串代表无参数（不是错误）
#   - 所有校验失败统一抛 ToolCallError，上层只需捕获一种异常


class ToolCall(TypedDict):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolCallError(ValueError):
    """工具调用格式非法。"""


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolCallError(f"{field} 必须是非空字符串，当前为 {value!r}")
    return value.strip()


def parse_tool_call(payload: dict[str, Any]) -> ToolCall:
    if not isinstance(payload, dict):
        raise ToolCallError(f"payload 必须是 dict，当前为 {type(payload).__name__}")

    function = payload.get("function")
    if function is not None and not isinstance(function, dict):
        raise ToolCallError("function 必须是 object")

    if isinstance(function, dict):
        name = _require_non_empty_str(function.get("name"), "function.name")
        raw_arguments = function.get("arguments", {})
    else:
        name = _require_non_empty_str(payload.get("name"), "name")
        raw_arguments = payload.get("arguments", {})

    call_id = _require_non_empty_str(payload.get("id"), "id")

    if raw_arguments is None or raw_arguments == "":
        arguments: dict[str, Any] = {}
    elif isinstance(raw_arguments, str):
        try:
            decoded = json.loads(raw_arguments)
        except json.JSONDecodeError as e:
            raise ToolCallError(f"arguments 不是合法 JSON: {e}") from e
        if not isinstance(decoded, dict):
            raise ToolCallError("arguments 解析后必须是 object")
        arguments = decoded
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments
    else:
        raise ToolCallError(f"arguments 类型不支持: {type(raw_arguments).__name__}")

    return {"id": call_id, "name": name, "arguments": arguments}


# ---------------------------------------------------------------------------
# 4. ClaimInput
# ---------------------------------------------------------------------------
# 关键点：
#   - extra="forbid"：防止前端悄悄多传字段，把问题暴露在边界
#   - field_validator 里抛 ValueError，pydantic 会自动包装成 ValidationError
#   - validator 返回值会替换原值（这里用来做 strip）
#   - 先校验类型/范围（Field），再在 validator 里做业务规则


class ClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    amount: float = Field(gt=0, le=1_000_000)
    reason: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("claim_id")
    @classmethod
    def validate_claim_id(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("claim_id 至少 3 个字符")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        result: list[str] = []
        for tag in tags:
            tag = tag.strip()
            if tag and tag not in result:
                result.append(tag)
        if len(result) > 5:
            raise ValueError("tags 最多 5 个")
        return result
