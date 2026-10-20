"""综合示例：一个最小可用的理赔助手 Agent。

它把第 6 周的四个练习串起来：
    build_tool_schema  -> 定义工具
    dispatch_tool_call -> 执行工具（错误兜底）
    run_agent_loop     -> 多轮工具调用
    （truncate_messages 在长对话里使用，本示例消息很短，暂不裁剪）

用法：
    # 离线演示（假 LLM，不花钱、不联网）—— 先完成 exercises.py
    .\\.venv\\Scripts\\python.exe stage6_agent\\capstone_mini_agent.py

    # 真实调用（读取项目根目录 .env 里的 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL）
    .\\.venv\\Scripts\\python.exe stage6_agent\\capstone_mini_agent.py --real

    # 自定义问题
    .\\.venv\\Scripts\\python.exe stage6_agent\\capstone_mini_agent.py --real --question "帮我查一下 CLM-2024-002"
"""

from __future__ import annotations

import argparse
import ast
import json
import operator
import os
import sys
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

# 允许从任意目录运行：把 My_Study/Python 加入模块搜索路径
PYTHON_STUDY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_STUDY_ROOT))

from stage6_agent.exercises import (  # noqa: E402
    AgentLoopError,
    build_tool_schema,
    run_agent_loop,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PYTHON_STUDY_ROOT / ".env")

SYSTEM_PROMPT = (
    "你是保险公司理赔助手。回答必须基于工具返回的数据，不要编造。"
    "涉及金额时保留两位小数。工具报错时，向用户说明原因并给出下一步建议。"
)

QUESTION = "请帮我算一下 39 + 3 等于多少，再查一下理赔单 CLM-2024-001 的状态，最后用一句话总结。"


# ---------------------------------------------------------------------------
# 工具实现（真实项目里这里会调用数据库/内部 API）
# ---------------------------------------------------------------------------
_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def calculate(expression: str) -> float:
    """安全地计算四则运算，不使用 eval。"""
    tree = ast.parse(expression, mode="eval")

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Pow) and right > 12:
                raise ValueError("指数过大")
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -evaluate(node.operand)
        raise ValueError(f"不支持的表达式片段: {ast.dump(node)}")

    return evaluate(tree.body)


def get_claim_status(claim_id: str) -> dict[str, Any]:
    """模拟查询理赔状态（真实项目接数据库/核心系统）。"""
    mock_status = {
        "CLM-2024-001": "reviewing",
        "CLM-2024-002": "approved",
        "CLM-2024-003": "rejected",
    }
    status = mock_status.get(claim_id.upper())
    if status is None:
        raise ValueError(f"未找到理赔单 {claim_id}")
    return {"claim_id": claim_id.upper(), "status": status, "updated_at": "2026-10-20"}


def get_policy_clause(policy_id: str) -> dict[str, Any]:
    """模拟查询保单条款。"""
    return {
        "policy_id": policy_id.upper(),
        "clause": "单次理赔金额超过 1 万元需人工复核。",
        "deductible": 500,
    }


REGISTRY = {
    "calculate": calculate,
    "get_claim_status": get_claim_status,
    "get_policy_clause": get_policy_clause,
}


def tool_schemas() -> list[dict[str, Any]]:
    """工具定义。注意 description 要写清楚"什么时候用"。"""
    return [
        build_tool_schema(
            "calculate",
            "计算数学表达式，支持 + - * / % ** 和括号。用于金额、比例等算术。",
            {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如 39 + 3 或 (1000 * 0.8) / 2",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        ),
        build_tool_schema(
            "get_claim_status",
            "根据理赔单号查询当前状态。只读操作，不会修改数据。",
            {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "理赔单号，例如 CLM-2024-001",
                    }
                },
                "required": ["claim_id"],
                "additionalProperties": False,
            },
        ),
        build_tool_schema(
            "get_policy_clause",
            "查询保单的理赔条款和免赔额。遇到赔付规则问题时使用。",
            {
                "type": "object",
                "properties": {
                    "policy_id": {
                        "type": "string",
                        "description": "保单号，例如 POL-2024-888",
                    }
                },
                "required": ["policy_id"],
                "additionalProperties": False,
            },
        ),
    ]


# ---------------------------------------------------------------------------
# LLM 适配器
# ---------------------------------------------------------------------------
def make_openai_llm(model: str):
    """把 OpenAI 兼容客户端包装成 run_agent_loop 需要的 llm(messages) 函数。"""
    from openai import OpenAI

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = (
        os.getenv("DEEPSEEK_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.deepseek.com"
    )
    if not api_key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY（在项目根目录 .env 里配置）")

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=30.0, max_retries=2)

    def llm(messages: list[dict[str, Any]]) -> dict[str, Any]:
        response = client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            tools=cast(Any, tool_schemas()),
            temperature=0.2,
        )
        message = response.choices[0].message
        data = message.model_dump(exclude_none=True)
        data.setdefault("role", "assistant")
        return data

    return llm


class ScriptedLLM:
    """离线演示用的假 LLM：按脚本返回消息，便于观察 Loop 的每一步。"""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self._replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    def __call__(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append([dict(message) for message in messages])
        return self._replies.pop(0)


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def dry_run(question: str) -> None:
    replies: list[dict[str, Any]] = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("call_1", "calculate", {"expression": "39 + 3"})],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("call_2", "get_claim_status", {"claim_id": "CLM-2024-001"})],
        },
        {
            "role": "assistant",
            "content": "39 + 3 = 42；理赔单 CLM-2024-001 当前状态为 reviewing（审核中），建议关注后续补件通知。",
        },
    ]
    fake = ScriptedLLM(replies)
    messages = run_agent_loop(
        fake,
        question,
        REGISTRY,
        system_prompt=SYSTEM_PROMPT,
        max_steps=6,
    )
    print("=" * 70)
    print("离线演示（假 LLM）：共调用模型", len(fake.calls), "次")
    print("=" * 70)
    print_trace(messages)


def real_run(question: str, model: str) -> None:
    llm = make_openai_llm(model)
    messages = run_agent_loop(
        llm,
        question,
        REGISTRY,
        system_prompt=SYSTEM_PROMPT,
        max_steps=6,
    )
    print("=" * 70)
    print(f"真实调用完成：model={model}")
    print("=" * 70)
    print_trace(messages)


def print_trace(messages: list[dict[str, Any]]) -> None:
    for index, message in enumerate(messages, start=1):
        role = message.get("role", "?")
        content = message.get("content")
        print(f"\n[{index}] {role}")
        if content:
            text = str(content)
            print("    " + (text[:300] + "..." if len(text) > 300 else text))
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            print(f"    -> 调用工具 {function.get('name')}，参数 {function.get('arguments')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="最小理赔 Agent")
    parser.add_argument("--real", action="store_true", help="真实调用模型（默认离线演示）")
    parser.add_argument("--question", default=QUESTION, help="用户问题")
    parser.add_argument(
        "--model",
        default=os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-chat"),
        help="模型名称",
    )
    args = parser.parse_args()

    try:
        if args.real:
            real_run(args.question, args.model)
        else:
            dry_run(args.question)
    except NotImplementedError as e:
        raise SystemExit(f"请先完成 stage6_agent/exercises.py 中的练习：{e}") from e
    except AgentLoopError as e:
        raise SystemExit(f"Agent 循环失败：{e}") from e


if __name__ == "__main__":
    main()
