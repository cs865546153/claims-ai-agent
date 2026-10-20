"""Stage 6 参考答案与讲解。"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Mapping
from typing import Any

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AgentLoopError(RuntimeError):
    """Agent 循环异常（超过最大步数、消息格式错误等）。"""


# ---------------------------------------------------------------------------
# 1. build_tool_schema
# ---------------------------------------------------------------------------
# 关键点：
#   - 工具名限制是 OpenAI 的硬性要求：字母/数字/下划线/连字符，最长 64
#   - parameters 必须是 JSON Schema 的 object；否则模型无法正确填参数
#   - deepcopy 防止调用方后续修改 parameters 影响已注册的 schema
#   - 真实项目里可以直接用 pydantic：Model.model_json_schema()


def build_tool_schema(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name):
        raise ValueError(f"工具名非法: {name!r}（只允许字母/数字/下划线/连字符，1~64 位）")

    normalized_description = description.strip() if isinstance(description, str) else ""
    if not normalized_description:
        raise ValueError("工具描述不能为空")

    if not isinstance(parameters, dict):
        raise ValueError("parameters 必须是 dict")
    if parameters.get("type") != "object":
        raise ValueError('parameters["type"] 必须是 "object"')
    if not isinstance(parameters.get("properties"), dict):
        raise ValueError('parameters["properties"] 必须是 dict')

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": normalized_description,
            "parameters": copy.deepcopy(parameters),
        },
    }


# ---------------------------------------------------------------------------
# 2. dispatch_tool_call
# ---------------------------------------------------------------------------
# 关键点：
#   - 模型给的 arguments 是字符串，可能是空串、坏 JSON、数组
#   - 任何错误都返回 JSON 字符串，让模型看到错误并自我修正
#   - TypeError 单独处理：通常是模型给错参数名/漏参数，错误信息要清楚
#   - json.dumps(result) 也可能失败（工具返回了 datetime/自定义对象），要兜住
#   - ensure_ascii=False：中文不转义，日志和前端都更好读


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def dispatch_tool_call(
    name: str,
    arguments: str | dict[str, Any] | None,
    registry: Mapping[str, Callable[..., Any]],
) -> str:
    if arguments is None:
        parsed: dict[str, Any] = {}
    elif isinstance(arguments, dict):
        parsed = arguments
    elif isinstance(arguments, str):
        raw = arguments.strip()
        if not raw:
            parsed = {}
        else:
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError as e:
                return _error(f"arguments 不是合法 JSON: {e}")
            if not isinstance(decoded, dict):
                return _error("arguments 解析后必须是 JSON object")
            parsed = decoded
    else:
        return _error(f"不支持的 arguments 类型: {type(arguments).__name__}")

    func = registry.get(name)
    if func is None:
        return _error(f"unknown tool: {name}")

    try:
        result = func(**parsed)
    except TypeError as e:
        return _error(f"invalid arguments for {name}: {e}")
    except Exception as e:  # 工具内部错误不能拖垮整个 Agent
        return _error(f"tool {name} failed: {e}")

    try:
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        return _error(f"tool {name} 返回值无法序列化: {e}")


# ---------------------------------------------------------------------------
# 3. run_agent_loop
# ---------------------------------------------------------------------------
# 关键点：
#   - 终止条件是"没有 tool_calls"，不是 content 为空
#   - 每轮把 assistant 原样放回 messages，tool 结果必须带 tool_call_id
#   - max_steps 防死循环：模型可能反复调同一个失败的工具
#   - 工具错误已经被 dispatch 转成字符串，循环本身不需要 try/except
#   - 生产代码还要加：日志、trace_id、每轮耗时、token 统计、预算控制


def run_agent_loop(
    llm: Callable[[list[dict[str, Any]]], dict[str, Any]],
    user_message: str,
    registry: Mapping[str, Callable[..., Any]],
    *,
    system_prompt: str = "You are a helpful assistant.",
    max_steps: int = 8,
) -> list[dict[str, Any]]:
    if max_steps < 1:
        raise ValueError(f"max_steps 必须 >= 1，当前为 {max_steps}")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    for _ in range(max_steps):
        reply = llm(messages)
        if not isinstance(reply, dict):
            raise AgentLoopError(f"llm 必须返回 dict，当前为 {type(reply).__name__}")
        messages.append(reply)

        tool_calls = reply.get("tool_calls") or []
        if not tool_calls:
            return messages

        for call in tool_calls:
            try:
                call_id = call["id"]
                function = call["function"]
                tool_name = function["name"]
                raw_arguments = function.get("arguments")
            except (KeyError, TypeError) as e:
                raise AgentLoopError(f"非法的 tool_call: {call!r}") from e

            content = dispatch_tool_call(tool_name, raw_arguments, registry)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": content,
                }
            )

    raise AgentLoopError(f"超过最大步数 {max_steps} 仍未得到最终回答")


# ---------------------------------------------------------------------------
# 4. truncate_messages
# ---------------------------------------------------------------------------
# 关键点：
#   - system 始终保留：它是"行为约束"，丢了会导致输出跑偏
#   - 从后往前加：最新的上下文最重要
#   - 一旦某条放不下就停止，而不是跳过去拿更早的（否则会得到破碎上下文）
#   - 返回保持原顺序，否则模型看到的对话时序会乱
#   - 真实场景还要保证 assistant(tool_calls) 与 tool 消息成对，不能拆散


def truncate_messages(
    messages: list[dict[str, Any]],
    max_tokens: int,
    count_tokens: Callable[[dict[str, Any]], int],
    *,
    keep_system: bool = True,
) -> list[dict[str, Any]]:
    if max_tokens <= 0:
        raise ValueError(f"max_tokens 必须 > 0，当前为 {max_tokens}")

    system: list[dict[str, Any]] = []
    rest = messages

    if keep_system and messages and messages[0].get("role") == "system":
        system = [messages[0]]
        rest = messages[1:]

    used = sum(count_tokens(message) for message in system)
    kept: list[dict[str, Any]] = []

    for message in reversed(rest):
        cost = count_tokens(message)
        if used + cost > max_tokens:
            break
        kept.append(message)
        used += cost

    return system + list(reversed(kept))
