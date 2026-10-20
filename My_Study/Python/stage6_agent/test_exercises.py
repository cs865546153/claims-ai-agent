"""Stage 6 自动判分。不要修改本文件。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from stage6_agent.exercises import (
    AgentLoopError,
    build_tool_schema,
    dispatch_tool_call,
    run_agent_loop,
    truncate_messages,
)


# ---------------------------------------------------------------------------
# build_tool_schema
# ---------------------------------------------------------------------------
def test_build_tool_schema_valid() -> None:
    parameters = {
        "type": "object",
        "properties": {"claim_id": {"type": "string"}},
        "required": ["claim_id"],
    }
    schema = build_tool_schema("get_claim_status", " 查询理赔状态 ", parameters)

    assert schema == {
        "type": "function",
        "function": {
            "name": "get_claim_status",
            "description": "查询理赔状态",
            "parameters": parameters,
        },
    }
    assert schema["function"]["parameters"] is not parameters


def test_build_tool_schema_does_not_mutate_parameters() -> None:
    parameters = {"type": "object", "properties": {"x": {"type": "integer"}}}
    build_tool_schema("tool", "desc", parameters)
    assert parameters == {"type": "object", "properties": {"x": {"type": "integer"}}}


@pytest.mark.parametrize("name", ["", "bad name", "工具", "a" * 65, "a.b"])
def test_build_tool_schema_invalid_name(name: str) -> None:
    with pytest.raises(ValueError):
        build_tool_schema(name, "desc", {"type": "object", "properties": {}})


@pytest.mark.parametrize("description", ["", "   "])
def test_build_tool_schema_invalid_description(description: str) -> None:
    with pytest.raises(ValueError):
        build_tool_schema("tool", description, {"type": "object", "properties": {}})


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"type": "array", "properties": {}},
        {"type": "object"},
        {"type": "object", "properties": []},
    ],
)
def test_build_tool_schema_invalid_parameters(parameters: dict) -> None:
    with pytest.raises(ValueError):
        build_tool_schema("tool", "desc", parameters)


# ---------------------------------------------------------------------------
# dispatch_tool_call
# ---------------------------------------------------------------------------
def add(a: int, b: int) -> int:
    return a + b


def ping() -> str:
    return "pong"


def boom() -> None:
    raise RuntimeError("db down")


def echo(message: str) -> dict[str, str]:
    return {"message": message}


REGISTRY: dict[str, Callable[..., Any]] = {"add": add, "ping": ping, "boom": boom, "echo": echo}


def test_dispatch_success_with_string_arguments() -> None:
    result = dispatch_tool_call("add", '{"a": 1, "b": 2}', REGISTRY)
    assert isinstance(result, str)
    assert json.loads(result) == 3


def test_dispatch_success_with_dict_arguments() -> None:
    assert json.loads(dispatch_tool_call("add", {"a": 5, "b": 6}, REGISTRY)) == 11


def test_dispatch_no_arguments() -> None:
    assert json.loads(dispatch_tool_call("ping", None, REGISTRY)) == "pong"
    assert json.loads(dispatch_tool_call("ping", "", REGISTRY)) == "pong"


def test_dispatch_keeps_chinese_readable() -> None:
    result = dispatch_tool_call("echo", {"message": "理赔"}, REGISTRY)
    assert "理赔" in result


def test_dispatch_invalid_json_returns_error() -> None:
    payload = json.loads(dispatch_tool_call("add", "{not json", REGISTRY))
    assert "error" in payload
    assert "JSON" in payload["error"]


def test_dispatch_non_object_arguments_returns_error() -> None:
    payload = json.loads(dispatch_tool_call("add", "[1, 2]", REGISTRY))
    assert "error" in payload


def test_dispatch_unknown_tool() -> None:
    payload = json.loads(dispatch_tool_call("nope", "{}", REGISTRY))
    assert payload == {"error": "unknown tool: nope"}


def test_dispatch_invalid_arguments_returns_error() -> None:
    payload = json.loads(dispatch_tool_call("add", {"a": 1}, REGISTRY))
    assert "error" in payload
    assert "invalid arguments" in payload["error"]


def test_dispatch_tool_exception_returns_error() -> None:
    payload = json.loads(dispatch_tool_call("boom", "{}", REGISTRY))
    assert "error" in payload
    assert "db down" in payload["error"]


# ---------------------------------------------------------------------------
# run_agent_loop
# ---------------------------------------------------------------------------
class FakeLLM:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    def __call__(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append([dict(message) for message in messages])
        if not self.replies:
            raise AssertionError("没有更多预设回复")
        return self.replies.pop(0)


def tool_call(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def test_loop_returns_immediately_without_tools() -> None:
    fake = FakeLLM([{"role": "assistant", "content": "你好"}])
    messages = run_agent_loop(fake, "hi", REGISTRY)

    assert [m["role"] for m in messages] == ["system", "user", "assistant"]
    assert messages[-1]["content"] == "你好"
    assert fake.calls[0][0]["role"] == "system"
    assert fake.calls[0][0]["content"]


def test_loop_calls_tool_then_answers() -> None:
    fake = FakeLLM(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call("call_1", "add", '{"a": 1, "b": 2}')],
            },
            {"role": "assistant", "content": "结果是 3"},
        ]
    )

    messages = run_agent_loop(fake, "1+2 等于几", {"add": add}, max_steps=4)

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "assistant"]
    tool_message = messages[3]
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["name"] == "add"
    assert json.loads(tool_message["content"]) == 3
    assert messages[-1]["content"] == "结果是 3"

    # 第二次调用模型时，应该能看到工具结果
    assert [m["role"] for m in fake.calls[1]] == ["system", "user", "assistant", "tool"]
    assert len(fake.calls) == 2


def test_loop_supports_multiple_tool_calls() -> None:
    fake = FakeLLM(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call("c1", "add", '{"a": 1, "b": 1}'),
                    tool_call("c2", "ping", "{}"),
                ],
            },
            {"role": "assistant", "content": "完成"},
        ]
    )

    messages = run_agent_loop(fake, "do it", REGISTRY)

    tool_messages = [m for m in messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c1", "c2"]
    assert json.loads(tool_messages[0]["content"]) == 2
    assert json.loads(tool_messages[1]["content"]) == "pong"


def test_loop_unknown_tool_does_not_crash() -> None:
    fake = FakeLLM(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call("c1", "missing", "{}")],
            },
            {"role": "assistant", "content": "工具不可用"},
        ]
    )

    messages = run_agent_loop(fake, "try", REGISTRY)
    tool_message = next(m for m in messages if m["role"] == "tool")
    assert "error" in json.loads(tool_message["content"])


def test_loop_max_steps() -> None:
    def always_tool(messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [tool_call("c1", "ping", "{}")],
        }

    with pytest.raises(AgentLoopError):
        run_agent_loop(always_tool, "loop", REGISTRY, max_steps=3)


def test_loop_invalid_max_steps() -> None:
    with pytest.raises(ValueError):
        run_agent_loop(FakeLLM([]), "x", REGISTRY, max_steps=0)


def test_loop_custom_system_prompt() -> None:
    fake = FakeLLM([{"role": "assistant", "content": "ok"}])
    messages = run_agent_loop(fake, "hi", REGISTRY, system_prompt="你是理赔助手")
    assert messages[0] == {"role": "system", "content": "你是理赔助手"}


def test_loop_does_not_mutate_registry() -> None:
    registry = {"add": add}
    run_agent_loop(FakeLLM([{"role": "assistant", "content": "ok"}]), "hi", registry)
    assert registry == {"add": add}


# ---------------------------------------------------------------------------
# truncate_messages
# ---------------------------------------------------------------------------
def count_by_content(message: dict[str, Any]) -> int:
    return len(message.get("content") or "")


MESSAGES = [
    {"role": "system", "content": "SYSTEM"},
    {"role": "user", "content": "old"},
    {"role": "assistant", "content": "reply"},
    {"role": "user", "content": "new"},
]


def test_truncate_keeps_system_and_latest() -> None:
    result = truncate_messages(MESSAGES, max_tokens=10, count_tokens=count_by_content)
    assert result == [MESSAGES[0], MESSAGES[3]]


def test_truncate_keeps_all_when_budget_allows() -> None:
    result = truncate_messages(MESSAGES, max_tokens=20, count_tokens=count_by_content)
    assert result == MESSAGES


def test_truncate_keeps_system_even_if_it_exceeds_budget() -> None:
    result = truncate_messages(MESSAGES, max_tokens=1, count_tokens=count_by_content)
    assert result == [MESSAGES[0]]


def test_truncate_without_keep_system() -> None:
    result = truncate_messages(
        MESSAGES,
        max_tokens=8,
        count_tokens=count_by_content,
        keep_system=False,
    )
    assert result == [MESSAGES[2], MESSAGES[3]]


def test_truncate_preserves_order() -> None:
    result = truncate_messages(MESSAGES, max_tokens=14, count_tokens=count_by_content)
    assert [m["content"] for m in result] == ["SYSTEM", "reply", "new"]


def test_truncate_does_not_mutate_input() -> None:
    snapshot = [dict(m) for m in MESSAGES]
    truncate_messages(MESSAGES, max_tokens=10, count_tokens=count_by_content)
    assert MESSAGES == snapshot


def test_truncate_invalid_budget() -> None:
    with pytest.raises(ValueError):
        truncate_messages(MESSAGES, max_tokens=0, count_tokens=count_by_content)
    with pytest.raises(ValueError):
        truncate_messages(MESSAGES, max_tokens=-5, count_tokens=count_by_content)
