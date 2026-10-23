"""混合路由测试：兜底、影子、失败传播与工厂组装。"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from agent_core.intent.contracts import (
    IntentClassificationError,
    IntentRequest,
    RouteDecision,
)
from agent_core.intent.factory import IntentConfig, build_intent_classifier
from agent_core.intent.hybrid import HybridIntentClassifier
from agent_core.intent.registry import DomainRegistry


class FakeClassifier:
    """可注入成功结果或异常的分类器。"""

    def __init__(self, *, decision: RouteDecision | None = None, error: Exception | None = None) -> None:
        self.decision = decision
        self.error = error
        self.calls = 0

    async def classify(self, request: IntentRequest) -> RouteDecision:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.decision is not None
        return self.decision.model_copy(deep=True)


def _decision(
    *,
    domain: str = "claims",
    intent: str = "理赔报案",
    confidence: float = 0.9,
    needs_clarification: bool = False,
) -> RouteDecision:
    return RouteDecision(
        domain=domain,
        intent=intent,
        confidence=confidence,
        needs_clarification=needs_clarification,
        engine="fake",
    )


def _request() -> IntentRequest:
    return IntentRequest(message="我的车被追尾了")


def test_primary_high_confidence_skips_fallback() -> None:
    fallback = FakeClassifier(decision=_decision(confidence=0.99))
    hybrid = HybridIntentClassifier(
        primary=FakeClassifier(decision=_decision()),
        fallback=fallback,
    )
    decision = asyncio.run(hybrid.classify(_request()))
    assert decision.engine == "fake"
    assert decision.fallback_used is False
    assert fallback.calls == 0


def test_low_confidence_uses_fallback() -> None:
    fallback = FakeClassifier(decision=_decision(confidence=0.95))
    hybrid = HybridIntentClassifier(
        primary=FakeClassifier(decision=_decision(confidence=0.55, needs_clarification=True)),
        fallback=fallback,
    )
    decision = asyncio.run(hybrid.classify(_request()))
    assert decision.confidence == pytest.approx(0.95)
    assert decision.fallback_used is True
    assert decision.fallback_reason == "low_confidence"
    assert fallback.calls == 1


def test_primary_error_uses_fallback() -> None:
    hybrid = HybridIntentClassifier(
        primary=FakeClassifier(error=RuntimeError("boom")),
        fallback=FakeClassifier(decision=_decision(confidence=0.92)),
    )
    decision = asyncio.run(hybrid.classify(_request()))
    assert decision.fallback_used is True
    assert decision.fallback_reason == "RuntimeError"


def test_both_fail_raises() -> None:
    hybrid = HybridIntentClassifier(
        primary=FakeClassifier(error=RuntimeError("primary")),
        fallback=FakeClassifier(error=ValueError("fallback")),
    )
    with pytest.raises(IntentClassificationError):
        asyncio.run(hybrid.classify(_request()))


def test_shadow_is_recorded_but_not_returned() -> None:
    hybrid = HybridIntentClassifier(
        primary=FakeClassifier(decision=_decision(domain="claims", intent="理赔报案")),
        shadow=FakeClassifier(decision=_decision(domain="investment", intent="组合诊断")),
    )
    decision = asyncio.run(hybrid.classify(_request()))
    assert decision.domain == "claims"
    assert decision.intent == "理赔报案"
    assert decision.shadow is not None
    assert decision.shadow["domain"] == "investment"
    assert decision.shadow["agreement"] is False


def test_shadow_failure_does_not_break_primary() -> None:
    hybrid = HybridIntentClassifier(
        primary=FakeClassifier(decision=_decision()),
        shadow=FakeClassifier(error=RuntimeError("shadow")),
    )
    decision = asyncio.run(hybrid.classify(_request()))
    assert decision.domain == "claims"
    assert any(item.startswith("shadow_failed") for item in decision.warnings)


class FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def ainvoke(self, messages):  # noqa: ANN001 - 测试替身
        self.calls += 1
        return AIMessage(content=self.content)


class FakeSettings:
    intent_engine = "shadow"
    intent_primary = None
    intent_fallback = None
    intent_shadow = None
    intent_confidence_threshold = 0.8
    intent_margin_threshold = 0.2
    intent_translate_to_english = False
    jev_base_url = "https://example.test/jev"
    jev_api_key = SecretStr("test-key")
    jev_model = "ateve-jev-v1"
    jev_timeout_s = 5.0


def _jev_response() -> dict:
    return {
        "model": "ateve-jev-v1",
        "answers": {
            "domain": {
                "type": "choice",
                "choice": "claims",
                "probabilities": {"claims": 0.96, "investment": 0.03, "general": 0.01},
                "confidence": 0.96,
            },
            "intent": {
                "type": "choice",
                "choice": "claims:理赔报案",
                "probabilities": {"claims:理赔报案": 0.93, "claims:保单查询": 0.05},
                "confidence": 0.93,
            },
        },
    }


def test_factory_builds_shadow_preset() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_jev_response())

        config = IntentConfig.from_settings(FakeSettings())
        assert config.primary == "llm"
        assert config.shadow == "jev"

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            classifier = build_intent_classifier(
                config,
                registry=DomainRegistry.default(),
                llm_model=FakeLLM(
                    json.dumps(
                        {"domain": "claims", "intent": "理赔报案", "confidence": 0.91},
                        ensure_ascii=False,
                    )
                ),
                jev_client=client,
            )
            decision = await classifier.classify(_request())
            assert decision.engine == "llm"
            assert decision.shadow is not None
            assert decision.shadow["agreement"] is True
            await classifier.aclose()

    asyncio.run(scenario())


def test_factory_drops_jev_shadow_without_key() -> None:
    class NoKeySettings(FakeSettings):
        jev_api_key = SecretStr("")

    config = IntentConfig.from_settings(NoKeySettings())
    classifier = build_intent_classifier(
        config,
        registry=DomainRegistry.default(),
        llm_model=FakeLLM(
            json.dumps(
                {"domain": "claims", "intent": "理赔报案", "confidence": 0.91},
                ensure_ascii=False,
            )
        ),
    )
    assert classifier.shadow is None


def test_factory_requires_key_for_jev_primary() -> None:
    with pytest.raises(ValueError):
        build_intent_classifier(
            IntentConfig(primary="jev", fallback=None, shadow=None, jev_api_key=""),
            registry=DomainRegistry.default(),
            llm_model=FakeLLM("{}"),
        )
