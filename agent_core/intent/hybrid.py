"""主备与影子模式：JEV/LLM 可组合，失败或低置信时自动兜底。"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from .contracts import (
    IntentClassificationError,
    IntentClassifier,
    IntentRequest,
    RouteDecision,
)


class HybridIntentClassifier:
    """把主路由、兜底路由和影子路由组合成一个分类器。

    - primary：实际返回结果的引擎。
    - fallback：primary 异常或低置信时接管。
    - shadow：只记录不生效，用于灰度对比。
    """

    def __init__(
        self,
        *,
        primary: IntentClassifier,
        fallback: IntentClassifier | None = None,
        shadow: IntentClassifier | None = None,
        confidence_threshold: float = 0.8,
        margin_threshold: float = 0.2,
        on_decision: Callable[[RouteDecision], None] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.shadow = shadow
        self.confidence_threshold = confidence_threshold
        self.margin_threshold = margin_threshold
        self.on_decision = on_decision

    @property
    def engine_label(self) -> str:
        """组合描述，写入 trace 便于区分 shadow / hybrid / 单引擎。"""
        def name(component: IntentClassifier | None) -> str:
            if component is None:
                return "none"
            return str(getattr(component, "engine_name", type(component).__name__))

        return f"primary={name(self.primary)},fallback={name(self.fallback)},shadow={name(self.shadow)}"

    async def classify(self, request: IntentRequest) -> RouteDecision:
        started = time.monotonic()
        shadow_result: RouteDecision | BaseException | None = None

        if self.shadow is not None:
            primary_result, shadow_result = await asyncio.gather(
                self.primary.classify(request),
                self.shadow.classify(request),
                return_exceptions=True,
            )
        else:
            try:
                primary_result = await self.primary.classify(request)
            except Exception as exc:  # noqa: BLE001 - 统一转为兜底信号
                primary_result = exc

        if isinstance(primary_result, BaseException):
            decision, fallback_error = await self._fallback(request, type(primary_result).__name__)
            if decision is None:
                raise IntentClassificationError(
                    f"主意图引擎失败，兜底不可用：{type(primary_result).__name__}"
                    f"（{fallback_error}）"
                ) from primary_result
        else:
            decision = primary_result
            if self._low_confidence(decision):
                fallback_decision, fallback_error = await self._fallback(
                    request, "low_confidence"
                )
                if fallback_decision is not None:
                    decision = fallback_decision
                elif fallback_error and fallback_error != "not_configured":
                    decision.warnings.append(f"fallback_{fallback_error}")
                    decision.needs_clarification = True

        if shadow_result is not None:
            if isinstance(shadow_result, BaseException):
                decision.warnings.append(f"shadow_failed:{type(shadow_result).__name__}")
            else:
                decision.shadow = {
                    "engine": shadow_result.engine,
                    "domain": shadow_result.domain,
                    "intent": shadow_result.intent,
                    "confidence": shadow_result.confidence,
                    "agreement": (
                        shadow_result.domain == decision.domain
                        and shadow_result.intent == decision.intent
                    ),
                }

        decision.latency_ms = int((time.monotonic() - started) * 1000)
        if self.on_decision is not None:
            try:
                self.on_decision(decision)
            except Exception:  # noqa: BLE001 - 指标回调不能影响路由
                pass
        return decision

    async def _fallback(
        self, request: IntentRequest, reason: str
    ) -> tuple[RouteDecision | None, str | None]:
        if self.fallback is None:
            return None, "not_configured"
        try:
            decision = await self.fallback.classify(request)
        except Exception as exc:  # noqa: BLE001
            return None, f"failed:{type(exc).__name__}"
        decision.fallback_used = True
        decision.fallback_reason = reason
        return decision, None

    def _low_confidence(self, decision: RouteDecision) -> bool:
        if decision.confidence < self.confidence_threshold:
            return True
        if decision.margin is not None and decision.margin < self.margin_threshold:
            return True
        return decision.needs_clarification

    async def aclose(self) -> None:
        """关闭底层引擎持有的 HTTP 客户端；LLM 引擎无需关闭。"""
        seen: set[int] = set()
        for component in (self.primary, self.fallback, self.shadow):
            if component is None or id(component) in seen:
                continue
            seen.add(id(component))
            close = getattr(component, "aclose", None)
            if close is not None:
                await close()


__all__ = ["HybridIntentClassifier"]
