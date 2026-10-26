"""对话图适配层：把工作台请求映射为 IntentRequest，并把 RouteDecision 收敛成工作台意图。

`agent_core/intent` 只依赖公共契约，不认识 FastAPI 或工作台的请求模型；
本模块是主程序（`agents/assistant_agent.py`）接入 IntentRouter 的唯一粘合层。
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .contracts import IntentClassifier, IntentRequest, RouteDecision, Turn

HISTORY_LIMIT = 12
ATTACHMENT_LIMIT = 6
# 保单号形态：字母前缀 + 数字（POL-2024-001 / POL2024001）；仅在「保单查询」意图下兜底抽取。
# JEV 只输出领域与意图，不返回槽位，因此保单号仍需本地正则补齐。
POLICY_ID_PATTERN = re.compile(r"\b[A-Za-z]{2,6}[-_]?\d{2,6}[-_]?\d{2,6}\b")
POLICY_SLOT_KEYS = ("policy_id", "policyid", "保单号", "保单编号")


@dataclass(frozen=True)
class AssistantRoute:
    """主程序视角的路由结果：意图、置信度、保单号与完整决策。"""

    intent: str
    confidence: float
    policy_id: str | None
    decision: RouteDecision


class AssistantIntentRouter:
    """把 HybridIntentClassifier 适配到无状态对话图；只做协议转换，不参与业务决策。"""

    def __init__(self, classifier: IntentClassifier) -> None:
        self.classifier = classifier

    @property
    def engine_label(self) -> str:
        """给 trace 用的引擎描述，例如 router(primary=jev,fallback=llm)。"""
        return f"router({getattr(self.classifier, 'engine_label', type(self.classifier).__name__)})"

    @property
    def model_label(self) -> str:
        """主引擎实际使用的模型名；避免把 LLM 分类模型误写成 JEV。"""
        primary = getattr(self.classifier, "primary", self.classifier)
        model = getattr(primary, "model", None)
        name = getattr(model, "model_name", None)
        if name is None and isinstance(model, str):
            name = model
        if name is None:
            name = getattr(primary, "engine_name", None) or type(primary).__name__
        return str(name)

    async def classify(
        self,
        *,
        question: str,
        history: Iterable[Any] = (),
        attachments: Iterable[Any] = (),
        active_domain: str | None = None,
    ) -> AssistantRoute:
        """执行一次意图路由；输入已脱敏，输出直接可用于工作台 IntentResult。"""
        turns = [
            Turn(role=turn.role, content=turn.content[:4000])
            for turn in list(history)[-HISTORY_LIMIT:]
        ]
        file_names = [self._attachment_name(item) for item in list(attachments)[:ATTACHMENT_LIMIT]]
        request = IntentRequest(
            message=question,
            history=turns,
            active_domain=active_domain,
            attachments=file_names,
        )
        decision = await self.classifier.classify(request)
        return AssistantRoute(
            intent=decision.intent,
            confidence=decision.confidence,
            policy_id=self._policy_id(decision, question, turns),
            decision=decision,
        )

    @staticmethod
    def _attachment_name(item: Any) -> str:
        name = getattr(item, "file_name", None)
        return str(name or "attachment")[:255]

    @staticmethod
    def _policy_id(decision: RouteDecision, question: str, turns: list[Turn]) -> str | None:
        """优先用路由槽位，其次在「保单查询」意图下从当前问题与用户历史中兜底抽取。"""
        for key in POLICY_SLOT_KEYS:
            value = decision.slots.get(key)
            if value:
                return str(value)[:64]
        if decision.intent != "保单查询":
            return None
        recent_user_text = "\n".join(
            [question, *(turn.content for turn in reversed(turns) if turn.role == "user")]
        )
        match = POLICY_ID_PATTERN.search(recent_user_text)
        return match.group(0)[:64] if match else None

    async def aclose(self) -> None:
        """关闭底层引擎持有的 HTTP 客户端（JEV 使用 httpx.AsyncClient）。"""
        close = getattr(self.classifier, "aclose", None)
        if close is not None:
            await close()


__all__ = ["AssistantIntentRouter", "AssistantRoute"]
