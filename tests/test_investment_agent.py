"""投资域测试：组合诊断、适当性、交易确认/审批和聊天路由。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.types import Command

from agents.investment_agent import (
    DemoInvestmentServices,
    build_investment_graph,
    investment_initial_state,
    investment_state_to_response,
)
from app import create_app
from models.investment import InvestmentRequest


def _run(graph: Any, payload: Any, thread: str) -> dict[str, Any]:
    return asyncio.run(
        graph.ainvoke(
            payload,
            config={"configurable": {"thread_id": thread}, "recursion_limit": 30},
        )
    )


def _has_interrupt(state: dict[str, Any]) -> bool:
    return bool(state.get("__interrupt__"))


def _interrupt_kind(graph: Any, config: dict[str, Any]) -> str | None:
    snapshot = graph.get_state(config)
    for task in snapshot.tasks:
        for item in task.interrupts:
            value = getattr(item, "value", None)
            if isinstance(value, dict):
                return str(value.get("kind"))
    return None


def test_portfolio_diagnosis_marks_suitability() -> None:
    request = InvestmentRequest(
        request_id="INV-TEST-001",
        question="帮我看看基金组合怎么配置",
        intent="组合诊断",
        risk_profile="稳健型",
        portfolio_id="PORT-DEMO-001",
    )
    graph = build_investment_graph(DemoInvestmentServices())
    state = _run(graph, investment_initial_state(request), request.request_id)

    assert state["decision"] == "advise"
    assert state["phase"] == "complete"
    assert state["risk_level"] == "中"
    assert state["suitability"] == "适合"
    assert state["advice"]["allocation"]
    assert "不构成投资建议" in state["advice"]["disclaimer"]


def test_product_with_lower_risk_profile_is_unsuitable() -> None:
    request = InvestmentRequest(
        request_id="INV-TEST-002",
        question="这只基金适合我吗",
        intent="产品查询",
        risk_profile="保守型",
        product_id="FUND-DEMO-002",
    )
    graph = build_investment_graph(DemoInvestmentServices())
    state = _run(graph, investment_initial_state(request), request.request_id)

    assert state["risk_level"] == "中"
    assert state["suitability"] == "不适合"
    assert any("高于" in note for note in state["risk_notes"])


def test_trade_requires_confirmation_and_human_approval() -> None:
    request = InvestmentRequest(
        request_id="INV-TRADE-001",
        question="帮我买入这只基金",
        intent="交易指令",
        risk_profile="稳健型",
        product_id="FUND-DEMO-001",
        amount="10000",
        confirmed=False,
    )
    graph = build_investment_graph(DemoInvestmentServices())
    config = {"configurable": {"thread_id": request.request_id}, "recursion_limit": 30}

    first = asyncio.run(graph.ainvoke(investment_initial_state(request), config=config))
    assert _has_interrupt(first) is False
    assert _interrupt_kind(graph, config) == "trade_confirmation"

    confirmed = asyncio.run(graph.ainvoke(Command(resume={"confirmed": True}), config=config))
    assert _has_interrupt(confirmed) is False
    assert _interrupt_kind(graph, config) == "investment_review"

    result = asyncio.run(
        graph.ainvoke(
            Command(
                resume={
                    "decision": "approve",
                    "reviewer": "test-reviewer",
                    "reason": "演示审批通过",
                }
            ),
            config=config,
        )
    )
    assert result["decision"] == "review"
    assert result["human_decision"]["decision"] == "approve"
    assert result["trade_receipt"]["outbox_id"] == "OUT-DEMO-2026-001"
    assert result["trade_receipt"]["executed"] is False
    response = investment_state_to_response(result, request, demo=True)
    assert response.executed is False
    assert response.requires_human_review is True


class FakeInvestmentModel:
    """只验证路由和提示词，不访问真实模型。"""

    model_name = "fake-investment"
    temperature = 0.2
    max_tokens = 1000

    def __init__(self, intent: str) -> None:
        self.intent = intent
        self.stream_system_prompts: list[str] = []

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        return AIMessage(
            content=json.dumps(
                {"intent": self.intent, "confidence": 0.94},
                ensure_ascii=False,
            )
        )

    async def astream(self, messages: list[Any]):
        self.stream_system_prompts.append(messages[0].content)
        yield AIMessage(content="建议先完成风险测评，再根据目标配置组合。")
        yield AIMessage(content="以上不构成投资建议。")


def _assistant_events(response: Any) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_assistant_routes_portfolio_diagnosis_to_investment_prompt() -> None:
    model = FakeInvestmentModel("组合诊断")
    with TestClient(
        create_app(
            database=":memory:",
            intent_model=model,
            general_model=model,
            assistant_model=model,
            investment_model=model,
        )
    ) as client:
        response = client.post(
            "/api/assistant/stream",
            json={"question": "帮我看看基金组合怎么配置", "documents": [], "history": []},
        )
        assert response.status_code == 200
        events = _assistant_events(response)
        traces = [event["trace"] for event in events if "trace" in event]
        route = next(item for item in traces if item.get("node") == "route")
        assert route["selected"] == "investment"
        assert any(item.get("node") == "investment" for item in traces)
        assert "投资理财顾问助手" in model.stream_system_prompts[-1]


def test_assistant_blocks_direct_trade_execution() -> None:
    model = FakeInvestmentModel("交易指令")
    with TestClient(
        create_app(
            database=":memory:",
            intent_model=model,
            general_model=model,
            assistant_model=model,
            investment_model=model,
        )
    ) as client:
        response = client.post(
            "/api/assistant/stream",
            json={"question": "帮我把基金赎回", "documents": [], "history": []},
        )
        assert response.status_code == 200
        assert "不会由模型直接执行" in response.text
        events = _assistant_events(response)
        traces = [event["trace"] for event in events if "trace" in event]
        investment = next(
            item
            for item in traces
            if item.get("node") == "investment" and item.get("status") == "done"
        )
        assert investment["output"]["executed"] is False
        assert investment["output"]["requires_human_review"] is True
        assert not model.stream_system_prompts


def test_demo_investment_endpoint_returns_advice_and_trace() -> None:
    with TestClient(create_app(database=":memory:")) as client:
        response = client.post("/api/demo/investment/process")
        assert response.status_code == 200
        payload = response.json()
        assert payload["request"]["intent"] == "组合诊断"
        assert payload["result"]["decision"] == "advise"
        assert payload["result"]["demo"] is True
        assert payload["advice"]["allocation"]
        assert [event["node"] for event in payload["trace"]] == [
            "investment_intake",
            "investment_context",
            "investment_risk",
            "investment_decision",
            "investment_review",
            "investment_execute",
        ]
