"""Stage 4 自动判分。不要修改本文件。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stage4_typing_testing.exercises import (
    ClaimInput,
    JsonExtractError,
    ToolCallError,
    extract_json,
    parse_tool_call,
    retry,
)


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        '结果如下：{"a": 1} 以上。',
        '  \n {"a": 1} \n ',
    ],
)
def test_extract_json_ok(text: str) -> None:
    assert extract_json(text) == {"a": 1}


def test_extract_json_nested_and_braces_in_string() -> None:
    text = '前缀 {"a": {"b": 2}, "s": "x } y"} 后缀'
    assert extract_json(text) == {"a": {"b": 2}, "s": "x } y"}


@pytest.mark.parametrize(
    "text",
    [
        "no json here",
        "[1, 2, 3]",
        '{"a": 1',
        "{'a': 1}",
        "",
    ],
)
def test_extract_json_invalid(text: str) -> None:
    with pytest.raises(JsonExtractError):
        extract_json(text)


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------
class Boom(RuntimeError):
    pass


def test_retry_succeeds_after_failures() -> None:
    calls = {"n": 0}

    @retry(times=3, delay=0)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise Boom("not yet")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_exhausted_raises_last_exception() -> None:
    calls = {"n": 0}

    @retry(times=2, delay=0)
    def always_fail() -> None:
        calls["n"] += 1
        raise Boom(f"failure {calls['n']}")

    with pytest.raises(Boom) as exc_info:
        always_fail()
    assert calls["n"] == 2
    assert "failure 2" in str(exc_info.value)


def test_retry_passes_arguments_and_returns_value() -> None:
    @retry(times=2, delay=0)
    def add(a: int, b: int = 0) -> int:
        return a + b

    assert add(1, b=2) == 3


def test_retry_only_catches_configured_exceptions() -> None:
    calls = {"n": 0}

    @retry(times=3, delay=0, exceptions=(ValueError,))
    def raises_type_error() -> None:
        calls["n"] += 1
        raise TypeError("not retryable")

    with pytest.raises(TypeError):
        raises_type_error()
    assert calls["n"] == 1


def test_retry_preserves_function_metadata() -> None:
    @retry(times=2)
    def documented(x: int) -> int:
        """my docstring"""
        return x

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "my docstring"


def test_retry_invalid_times() -> None:
    with pytest.raises(ValueError):
        retry(times=0)


# ---------------------------------------------------------------------------
# parse_tool_call
# ---------------------------------------------------------------------------
def test_parse_tool_call_openai_shape_string_arguments() -> None:
    payload = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "add", "arguments": '{"a": 1, "b": 2}'},
    }
    assert parse_tool_call(payload) == {
        "id": "call_1",
        "name": "add",
        "arguments": {"a": 1, "b": 2},
    }


def test_parse_tool_call_flat_shape_dict_arguments() -> None:
    payload = {"id": "call_2", "name": "add", "arguments": {"a": 1}}
    assert parse_tool_call(payload) == {
        "id": "call_2",
        "name": "add",
        "arguments": {"a": 1},
    }


@pytest.mark.parametrize("arguments", [None, "", {}])
def test_parse_tool_call_empty_arguments(arguments: object) -> None:
    payload = {"id": "c", "name": "ping", "arguments": arguments}
    assert parse_tool_call(payload)["arguments"] == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "add", "arguments": {}},
        {"id": "", "name": "add", "arguments": {}},
        {"id": 1, "name": "add", "arguments": {}},
        {"id": "c", "name": "", "arguments": {}},
        {"id": "c", "function": {"arguments": {}}},
        {"id": "c", "name": "add", "arguments": "not json"},
        {"id": "c", "name": "add", "arguments": "[1, 2]"},
        {"id": "c", "name": "add", "arguments": 123},
        {"id": "c", "function": "not a dict"},
    ],
)
def test_parse_tool_call_invalid(payload: dict) -> None:
    with pytest.raises(ToolCallError):
        parse_tool_call(payload)


# ---------------------------------------------------------------------------
# ClaimInput
# ---------------------------------------------------------------------------
def test_claim_input_valid() -> None:
    claim = ClaimInput(claim_id="  C-001  ", amount=100)
    assert claim.claim_id == "C-001"
    assert claim.amount == 100
    assert claim.reason == ""
    assert claim.tags == []


@pytest.mark.parametrize("claim_id", ["", "  ", "ab", "  ab  "])
def test_claim_input_invalid_claim_id(claim_id: str) -> None:
    with pytest.raises(ValidationError):
        ClaimInput(claim_id=claim_id, amount=100)


@pytest.mark.parametrize("amount", [0, -1, 1_000_001])
def test_claim_input_invalid_amount(amount: float) -> None:
    with pytest.raises(ValidationError):
        ClaimInput(claim_id="C-001", amount=amount)


def test_claim_input_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ClaimInput.model_validate({"claim_id": "C-001", "amount": 100, "hacker": "x"})


def test_claim_input_normalizes_tags() -> None:
    claim = ClaimInput(claim_id="C-001", amount=100, tags=[" vip ", "vip", "", "  ", "fraud"])
    assert claim.tags == ["vip", "fraud"]


def test_claim_input_too_many_tags() -> None:
    with pytest.raises(ValidationError):
        ClaimInput(claim_id="C-001", amount=100, tags=[f"t{i}" for i in range(6)])


def test_claim_input_allows_exactly_five_tags() -> None:
    claim = ClaimInput(claim_id="C-001", amount=100, tags=["a", "b", "c", "d", "e"])
    assert len(claim.tags) == 5
