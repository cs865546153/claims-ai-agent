"""Stage 6 · Agent 核心机制 —— 练习题。

运行：
    .\\.venv\\Scripts\\python.exe -m pytest stage6_agent -q

完成后再跑：
    .\\.venv\\Scripts\\python.exe stage6_agent\\capstone_mini_agent.py
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class AgentLoopError(RuntimeError):
    """Agent 循环异常（超过最大步数、消息格式错误等）。"""


def build_tool_schema(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """生成 OpenAI / DeepSeek 的工具 schema。

    规则：
        - name 必须匹配 ^[A-Za-z0-9_-]{1,64}$，否则抛 ValueError
        - description 去空白后不能为空，否则抛 ValueError
        - parameters 必须是 dict，且：
            * parameters["type"] == "object"
            * parameters["properties"] 是 dict
          否则抛 ValueError
        - 返回：
            {"type": "function",
             "function": {"name": ..., "description": ..., "parameters": ...}}
        - **不能修改传入的 parameters**（返回副本）

    示例：
        build_tool_schema("get_claim_status", "查询理赔状态",
                          {"type": "object", "properties": {"claim_id": {"type": "string"}}})
    """
    raise NotImplementedError("TODO: 实现 build_tool_schema")


def dispatch_tool_call(
    name: str,
    arguments: str | dict[str, Any] | None,
    registry: Mapping[str, Callable[..., Any]],
) -> str:
    """执行工具，永远返回字符串（可以直接塞进 role=tool 的 content）。

    规则：
        - arguments 为 None 或 "" -> {}
        - arguments 是 str -> json.loads；解析失败返回 {"error": "..."}
        - 解析结果必须是 dict，否则返回 {"error": "..."}
        - 未知工具 -> {"error": "unknown tool: <name>"}
        - 调用工具时参数不匹配（TypeError）-> {"error": "invalid arguments ..."}
        - 工具内部抛其它异常 -> {"error": "tool <name> failed: ..."}
        - 成功 -> json.dumps(result, ensure_ascii=False)
        - **所有错误都返回 JSON 字符串，不要向上抛异常**

    示例：
        registry = {"add": lambda a, b: a + b}
        dispatch_tool_call("add", '{"a": 1, "b": 2}', registry)  -> "3"
        dispatch_tool_call("nope", "{}", registry)               -> '{"error": "unknown tool: nope"}'
    """
    raise NotImplementedError("TODO: 实现 dispatch_tool_call")


def run_agent_loop(
    llm: Callable[[list[dict[str, Any]]], dict[str, Any]],
    user_message: str,
    registry: Mapping[str, Callable[..., Any]],
    *,
    system_prompt: str = "You are a helpful assistant.",
    max_steps: int = 8,
) -> list[dict[str, Any]]:
    """手写 ReAct 风格的工具循环。

    流程：
        1. messages = [system, user]
        2. 每轮调用 reply = llm(messages)，把 reply 追加到 messages
        3. reply 没有 tool_calls（或为空）-> 返回 messages（结束）
        4. 有 tool_calls -> 逐个执行，追加：
             {"role": "tool", "tool_call_id": <call["id"]>,
              "name": <call["function"]["name"]>, "content": <dispatch 返回的字符串>}
        5. 超过 max_steps 仍未结束 -> 抛 AgentLoopError
        6. max_steps < 1 -> 抛 ValueError

    要求：
        - 不要修改 registry 或 llm
        - 工具失败不能让循环崩溃（dispatch 已经兜底）
        - 支持一轮返回多个 tool_calls
        - 返回的 messages 要能直接发给 OpenAI 兼容接口

    示例（假 LLM）：
        replies = [
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "add", "arguments": '{"a": 1, "b": 2}'}}]},
            {"role": "assistant", "content": "结果是 3"},
        ]
        messages = run_agent_loop(FakeLLM(replies), "1+2", {"add": lambda a, b: a + b})
    """
    raise NotImplementedError("TODO: 实现 run_agent_loop")


def truncate_messages(
    messages: list[dict[str, Any]],
    max_tokens: int,
    count_tokens: Callable[[dict[str, Any]], int],
    *,
    keep_system: bool = True,
) -> list[dict[str, Any]]:
    """按 token 预算裁剪上下文。

    规则：
        - max_tokens <= 0 -> 抛 ValueError
        - keep_system=True 且 messages[0]["role"] == "system"：
          永远保留 system（即使它本身超预算）
        - 其余消息：从**最新**往回逐条尝试加入，
          某条放不下就停止（不再考虑更早的消息）
        - 返回保持原始顺序，且不修改入参

    示例（count_tokens = len(content)）：
        [system(6), user(3), assistant(5), user(3)]
        max_tokens=10 -> [system, user(3)]     # 6+3=9，再放 assistant 会超
        max_tokens=20 -> 全部
    """
    raise NotImplementedError("TODO: 实现 truncate_messages")
