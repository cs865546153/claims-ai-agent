"""投资域 LangGraph：组合诊断、适当性校验、交易确认与人工审批。

咨询类意图直接形成教育性建议；交易指令是高风险案件模式，必须经过二次确认
和人工审批。演示环境只生成待执行事件，不连接券商或基金平台，也不真实下单。
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from adapters.investment import DemoInvestmentBackend, InvestmentBackend
from models.investment import (
    InvestmentAdvice,
    InvestmentIntent,
    InvestmentRequest,
    InvestmentResponse,
)

_PROFILE_SCORES = {"保守型": 1, "稳健型": 2, "平衡型": 2, "成长型": 3, "进取型": 3}
_RISK_SCORES = {"低": 1, "中": 2, "高": 3}
_INVESTMENT_INTENTS = {"投资咨询", "组合诊断", "风险评估", "产品查询", "交易指令"}


class InvestmentState(TypedDict, total=False):
    """投资请求在一次图运行中的状态；金额统一转为字符串便于检查点序列化。"""

    request_id: str
    question: str
    intent: InvestmentIntent
    risk_profile: str | None
    portfolio_id: str | None
    product_id: str | None
    amount: str | None
    confirmed: bool
    portfolio: dict[str, Any]
    product: dict[str, Any]
    market: dict[str, Any]
    context_errors: list[str]
    risk_level: str
    suitability: str
    risk_notes: list[str]
    advice: dict[str, Any]
    decision: str
    phase: str
    message: str
    approved: bool
    executed: bool
    human_decision: dict[str, Any]
    trade_receipt: dict[str, Any]
    demo: bool


class InvestmentServices:
    """投资业务服务；真实适配器未配置时显式失败，不伪造行情或下单结果。"""

    def __init__(self, backend: InvestmentBackend | None = None) -> None:
        self.backend = backend or InvestmentBackend()

    async def portfolio(self, portfolio_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.backend.call, "query_portfolio", portfolio_id=portfolio_id
        )

    async def product(self, product_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.backend.call, "query_product", product_id=product_id
        )

    async def market(self, product_id: str | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.backend.call, "query_market", product_id=product_id
        )

    async def execute(self, order: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self.backend.call, "submit_trade", **order)


class DemoInvestmentServices(InvestmentServices):
    """固定合成数据，用于本地演示和测试。"""

    def __init__(self) -> None:
        super().__init__(DemoInvestmentBackend())


def investment_initial_state(request: InvestmentRequest) -> dict[str, Any]:
    """把 HTTP 请求转换为可序列化的图状态。"""
    return {
        "request_id": request.request_id,
        "question": request.question,
        "intent": request.intent,
        "risk_profile": request.risk_profile,
        "portfolio_id": request.portfolio_id,
        "product_id": request.product_id,
        "amount": str(request.amount) if request.amount is not None else None,
        "confirmed": request.confirmed,
    }


def _normalize_profile(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if text in _PROFILE_SCORES:
        return text
    for name in _PROFILE_SCORES:
        if name in text or text in name:
            return name
    return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _assess_risk(state: InvestmentState) -> dict[str, Any]:
    """基于可见数据做保守的适当性判断，不把模型评分当成业务事实。"""
    product = state.get("product") or {}
    portfolio = state.get("portfolio") or {}
    notes: list[str] = []

    risk_level = str(product.get("risk_level") or "待核实")
    if risk_level not in _RISK_SCORES:
        risk_level = "待核实"

    holdings = portfolio.get("holdings") or []
    holding_levels = [
        str(item.get("risk_level"))
        for item in holdings
        if str(item.get("risk_level")) in _RISK_SCORES
    ]
    if risk_level == "待核实" and holding_levels:
        risk_level = max(holding_levels, key=lambda item: _RISK_SCORES[item])

    max_weight = max((_to_float(item.get("weight")) for item in holdings), default=0.0)
    if max_weight >= 0.8 and risk_level == "中":
        risk_level = "高"
    elif max_weight >= 0.7 and risk_level == "低":
        risk_level = "中"
    if max_weight >= 0.5:
        notes.append(f"单一持仓占比约 {max_weight:.0%}，集中度需要关注。")

    profile = _normalize_profile(state.get("risk_profile"))
    if profile and risk_level in _RISK_SCORES:
        suitable = _PROFILE_SCORES[profile] >= _RISK_SCORES[risk_level]
        suitability = "适合" if suitable else "不适合"
        if not suitable:
            notes.append(f"风险等级 {risk_level} 高于 {profile} 的承受能力。")
    else:
        suitability = "待核实"
        notes.append("缺少风险测评或产品/组合风险等级，适当性结论待核实。")

    if not product and not holdings:
        notes.append("未提供产品或组合数据，无法形成具体配置结论。")
    errors = state.get("context_errors") or []
    if errors:
        notes.append("部分业务数据不可用：" + "、".join(errors) + "。")

    return {"risk_level": risk_level, "suitability": suitability, "risk_notes": notes}


def _build_advice(state: InvestmentState) -> InvestmentAdvice:
    product = state.get("product") or {}
    portfolio = state.get("portfolio") or {}
    market = state.get("market") or {}
    risk_level = state.get("risk_level") or "待核实"
    suitability = state.get("suitability") or "待核实"
    notes = list(state.get("risk_notes") or [])

    parts: list[str] = []
    if product:
        parts.append(
            f"产品 {product.get('name', product.get('product_id', '未命名产品'))} "
            f"风险等级为 {product.get('risk_level', '待核实')}，"
            f"演示历史收益 {product.get('historical_return') or '未提供'}，"
            "历史数据不代表未来收益。"
        )
    if portfolio:
        holdings = portfolio.get("holdings") or []
        parts.append(
            f"组合 {portfolio.get('portfolio_id', '未命名组合')} 共 {len(holdings)} 项持仓，"
            f"合计约 {portfolio.get('total_value', '待核实')} {portfolio.get('currency', '')}。"
        )
    if market:
        parts.append(f"行情快照日期为 {market.get('as_of', '待核实')}。")
    if not parts:
        parts.append("当前没有可用的组合或产品数据，无法形成具体配置结论。")

    parts.append(f"风险等级判断为 {risk_level}，适当性结论为 {suitability}。")
    if suitability == "不适合":
        parts.append("当前风险承受能力与产品/组合不匹配，不建议直接交易。")
    elif suitability == "待核实":
        parts.append("请先完成风险测评或补充产品与组合信息。")

    return InvestmentAdvice(
        summary="".join(parts),
        allocation=[
            {
                "product_id": str(item.get("product_id") or ""),
                "name": str(item.get("name") or ""),
                "weight": str(item.get("weight") or ""),
            }
            for item in (portfolio.get("holdings") or [])
        ],
        risks=notes or ["当前未发现额外风险，但仍需核实数据来源。"],
        next_actions=[
            "核对产品或组合的最新数据与产品说明书",
            "如风险测评缺失，先完成风险承受能力评估",
            "如需交易，提交二次确认并等待人工审批",
        ],
    )


def investment_state_to_response(
    state: InvestmentState,
    request: InvestmentRequest,
    *,
    demo: bool = False,
    interrupted: str | None = None,
) -> InvestmentResponse:
    """把图状态转换为稳定的 HTTP 契约。"""
    receipt = state.get("trade_receipt") or {}
    decision = state.get("decision") or "pending"
    phase = state.get("phase") or "pending"
    message = state.get("message") or "投资请求已受理，等待下一步处理。"

    return InvestmentResponse(
        request_id=state.get("request_id") or request.request_id,
        intent=request.intent,
        decision=decision,  # type: ignore[arg-type]
        phase=phase,
        risk_level=state.get("risk_level") or "待核实",  # type: ignore[arg-type]
        suitability=state.get("suitability") or "待核实",  # type: ignore[arg-type]
        requires_confirmation=(
            request.intent == "交易指令"
            and interrupted == "trade_confirmation"
            and phase != "cancelled"
        ),
        requires_human_review=(
            request.intent == "交易指令"
            and (interrupted == "investment_review" or decision == "review")
        ),
        executed=bool(state.get("executed") or receipt.get("executed")),
        demo=demo,
        message=message,
    )


def investment_advice_from_state(state: InvestmentState) -> InvestmentAdvice | None:
    """仅当图实际形成建议时返回，避免把待核实状态包装成结论。"""
    raw = state.get("advice")
    return InvestmentAdvice.model_validate(raw) if raw else None


def build_demo_trace(state: InvestmentState, request: InvestmentRequest) -> list[dict[str, Any]]:
    """为本地演示生成与前端节点同名的 trace。"""
    risk_level = state.get("risk_level") or "待核实"
    suitability = state.get("suitability") or "待核实"
    decision = state.get("decision") or "pending"
    receipt = state.get("trade_receipt") or {}
    context_status = "error" if state.get("context_errors") else "done"
    return [
        {
            "node": "investment_intake",
            "status": "cancelled" if state.get("phase") == "cancelled" else "done",
            "summary": "交易指令已取消" if state.get("phase") == "cancelled" else "投资请求字段已校验",
            "input": request.model_dump(mode="json"),
            "output": {"phase": state.get("phase"), "confirmed": state.get("confirmed", False)},
        },
        {
            "node": "investment_context",
            "status": context_status,
            "summary": "组合/产品/行情数据已读取" if context_status == "done" else "部分数据不可用",
            "output": {
                "portfolio": state.get("portfolio"),
                "product": state.get("product"),
                "market": state.get("market"),
                "errors": state.get("context_errors", []),
            },
        },
        {
            "node": "investment_risk",
            "status": "done",
            "summary": f"风险等级 {risk_level} · 适当性 {suitability}",
            "output": {"risk_notes": state.get("risk_notes", [])},
        },
        {
            "node": "investment_decision",
            "status": "done",
            "summary": f"投资决策建议：{decision}",
            "output": {
                "decision": decision,
                "requires_human_review": decision == "review",
            },
        },
        {
            "node": "investment_review",
            "status": "done" if state.get("human_decision") else "skipped",
            "summary": "已记录人工审批" if state.get("human_decision") else "咨询类请求无需人工审批",
            "output": state.get("human_decision") or {},
        },
        {
            "node": "investment_execute",
            "status": "done" if receipt else "skipped",
            "summary": "已生成交易回执" if receipt else "未执行交易",
            "output": receipt,
        },
    ]


def build_investment_graph(
    services: InvestmentServices | None = None,
    checkpointer: Any = None,
) -> Any:
    """构建投资域状态机；交易指令通过 interrupt 实现二次确认与人工审批。"""
    services = services or InvestmentServices()
    graph = StateGraph(InvestmentState)

    def intake(state: InvestmentState) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        if state.get("intent") == "交易指令":
            missing = [
                field
                for field in ("product_id", "amount", "risk_profile")
                if not state.get(field)
            ]
            if missing:
                answer = interrupt(
                    {
                        "kind": "investment_information",
                        "request_id": state["request_id"],
                        "missing": missing,
                    }
                )
                if isinstance(answer, dict):
                    for field in missing:
                        value = answer.get(field)
                        if value not in (None, ""):
                            updates[field] = str(value)
                remaining = [
                    field
                    for field in ("product_id", "amount", "risk_profile")
                    if not (state.get(field) or updates.get(field))
                ]
                if remaining:
                    return {
                        **updates,
                        "phase": "needs_information",
                        "decision": "pending",
                        "message": "交易指令需要补充：" + "、".join(remaining) + "。",
                    }

            if not state.get("confirmed"):
                answer = interrupt(
                    {
                        "kind": "trade_confirmation",
                        "request_id": state["request_id"],
                        "product_id": state.get("product_id") or updates.get("product_id"),
                        "amount": state.get("amount") or updates.get("amount"),
                        "risk_profile": state.get("risk_profile") or updates.get("risk_profile"),
                    }
                )
                if not (isinstance(answer, dict) and answer.get("confirmed") is True):
                    return {
                        **updates,
                        "phase": "cancelled",
                        "decision": "cancelled",
                        "message": "已取消交易指令，未执行任何操作。",
                    }
                updates["confirmed"] = True

        return {**updates, "phase": "ready", "decision": "pending"}

    async def context(state: InvestmentState) -> dict[str, Any]:
        calls: dict[str, Any] = {}
        if state.get("portfolio_id"):
            calls["portfolio"] = services.portfolio(state["portfolio_id"])
        if state.get("product_id"):
            calls["product"] = services.product(state["product_id"])
        if state.get("intent") in {"投资咨询", "组合诊断", "风险评估", "产品查询"}:
            calls["market"] = services.market(state.get("product_id"))

        updates: dict[str, Any] = {}
        errors: list[str] = []
        if calls:
            results = await asyncio.gather(*calls.values(), return_exceptions=True)
            for key, result in zip(calls, results, strict=True):
                if isinstance(result, Exception):
                    errors.append(f"{key}:{type(result).__name__}")
                else:
                    updates[key] = result
        if errors:
            updates["context_errors"] = errors
        return updates

    def risk(state: InvestmentState) -> dict[str, Any]:
        return _assess_risk(state)

    def advise(state: InvestmentState) -> dict[str, Any]:
        advice = _build_advice(state)
        return {
            "advice": advice.model_dump(mode="json"),
            "decision": "advise",
            "phase": "complete",
            "message": advice.summary,
        }

    def review(state: InvestmentState) -> dict[str, Any]:
        answer = interrupt(
            {
                "kind": "investment_review",
                "request_id": state["request_id"],
                "intent": state.get("intent"),
                "product_id": state.get("product_id"),
                "amount": state.get("amount"),
                "risk_level": state.get("risk_level"),
                "suitability": state.get("suitability"),
                "risk_notes": state.get("risk_notes", []),
            }
        )
        if not isinstance(answer, dict) or answer.get("decision") not in (
            "approve",
            "reject",
            "review",
        ):
            raise ValueError("投资人工审核决定不合法")
        if not answer.get("reviewer") or not answer.get("reason"):
            raise ValueError("投资人工审核必须记录审核员和理由")
        approved = answer["decision"] == "approve"
        return {
            "human_decision": answer,
            "approved": approved,
            "decision": answer["decision"],
            "phase": "reviewed",
            "message": "人工审批已通过。" if approved else "人工审核未通过，未执行交易。",
        }

    async def execute(state: InvestmentState) -> dict[str, Any]:
        order = {
            "request_id": state["request_id"],
            "product_id": state.get("product_id"),
            "amount": state.get("amount"),
            "risk_profile": state.get("risk_profile"),
            "risk_level": state.get("risk_level"),
            "suitability": state.get("suitability"),
        }
        try:
            receipt = await services.execute(order)
        except Exception as exc:
            return {
                "decision": "review",
                "phase": "complete",
                "executed": False,
                "trade_receipt": {"error": type(exc).__name__},
                "message": "交易适配器未配置，未执行下单，已转人工处理。",
            }

        executed = bool(receipt.get("executed"))
        identifier = receipt.get("order_id") or receipt.get("outbox_id") or "未知回执"
        message = (
            f"交易适配器已执行，回执 {identifier}。"
            if executed
            else f"已生成待执行事件 {identifier}，演示环境未真实下单。"
        )
        return {
            "decision": "execute" if executed else "review",
            "phase": "complete",
            "executed": executed,
            "trade_receipt": receipt,
            "message": message,
        }

    def rejected(state: InvestmentState) -> dict[str, Any]:
        decision = state.get("decision") or "reject"
        if decision not in {"reject", "review"}:
            decision = "reject"
        return {
            "decision": decision,
            "phase": "complete",
            "message": state.get("message") or "人工审核未通过，未执行交易。",
        }

    def terminal(state: InvestmentState) -> dict[str, Any]:
        return {
            "decision": state.get("decision") or "pending",
            "phase": state.get("phase") or "complete",
        }

    graph.add_node("intake", intake)
    graph.add_node("context", context)
    graph.add_node("risk", risk)
    graph.add_node("advise", advise)
    graph.add_node("review", review)
    graph.add_node("execute", execute)
    graph.add_node("rejected", rejected)
    graph.add_node("terminal", terminal)
    graph.add_edge(START, "intake")
    graph.add_conditional_edges(
        "intake",
        lambda state: "context" if state.get("phase") == "ready" else "terminal",
        {"context": "context", "terminal": "terminal"},
    )
    graph.add_edge("context", "risk")
    graph.add_conditional_edges(
        "risk",
        lambda state: "review" if state.get("intent") == "交易指令" else "advise",
        {"review": "review", "advise": "advise"},
    )
    graph.add_conditional_edges(
        "review",
        lambda state: "execute" if state.get("approved") else "rejected",
        {"execute": "execute", "rejected": "rejected"},
    )
    for node in ("advise", "execute", "rejected", "terminal"):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())


async def run_demo_investment() -> tuple[InvestmentRequest, dict[str, Any], InvestmentResponse]:
    """运行一次组合诊断演示，返回请求、图状态和稳定响应。"""
    request = InvestmentRequest(
        request_id="INV-DEMO-2026-001",
        question="帮我看看基金组合怎么配置，风险是否匹配？",
        intent="组合诊断",
        risk_profile="稳健型",
        portfolio_id="PORT-DEMO-001",
        product_id="FUND-DEMO-001",
    )
    graph = build_investment_graph(DemoInvestmentServices())
    state = await graph.ainvoke(
        investment_initial_state(request),
        config={
            "configurable": {"thread_id": request.request_id},
            "recursion_limit": 30,
        },
    )
    response = investment_state_to_response(state, request, demo=True)
    return request, state, response


__all__ = [
    "DemoInvestmentServices",
    "InvestmentServices",
    "InvestmentState",
    "build_demo_trace",
    "build_investment_graph",
    "investment_advice_from_state",
    "investment_initial_state",
    "investment_state_to_response",
    "run_demo_investment",
]
