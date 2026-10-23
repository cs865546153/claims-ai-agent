"""JEV 适配器测试：请求契约、脱敏、翻译、纠正与错误处理。"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent_core.intent.contracts import IntentRequest, Turn
from agent_core.intent.jev import JevError, JevIntentClassifier
from agent_core.intent.registry import DomainRegistry


def _response(
    *,
    domain: str = "claims",
    domain_confidence: float = 0.95,
    domain_probs: dict[str, float] | None = None,
    intent: str = "claims:理赔报案",
    intent_confidence: float = 0.90,
    intent_probs: dict[str, float] | None = None,
) -> dict:
    return {
        "model": "ateve-jev-v1",
        "answers": {
            "domain": {
                "type": "choice",
                "choice": domain,
                "probabilities": domain_probs
                or {"claims": domain_confidence, "investment": 0.03, "general": 0.02},
                "confidence": domain_confidence,
            },
            "intent": {
                "type": "choice",
                "choice": intent,
                "probabilities": intent_probs
                or {intent: intent_confidence, "claims:保单查询": 0.05},
                "confidence": intent_confidence,
            },
        },
        "usage": {"input_tokens": 100, "output_tokens": 0},
    }


def _request(message: str = "我的车被追尾了，怎么报案？") -> IntentRequest:
    return IntentRequest(
        message=message,
        history=[Turn(role="user", content="我的车被追尾了")],
        active_domain="claims",
    )


def test_jev_payload_and_parsing() -> None:
    async def scenario() -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_response())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            classifier = JevIntentClassifier(
                registry=DomainRegistry.default(),
                base_url="https://example.test/jev",
                api_key="test-key",
                client=client,
            )
            decision = await classifier.classify(_request())

        assert decision.domain == "claims"
        assert decision.intent == "理赔报案"
        assert decision.engine == "jev"
        assert decision.confidence == pytest.approx(0.90)
        assert decision.margin is not None and decision.margin > 0.8
        assert decision.needs_clarification is False

        assert seen["authorization"] == "Bearer test-key"
        body = seen["body"]
        assert isinstance(body, dict)
        assert body["model"] == "ateve-jev-v1"
        assert "Active domain: claims" in body["state"]
        assert "Current: 我的车被追尾了，怎么报案？" in body["state"]
        assert body["questions"]["domain"]["type"] == "choice"
        assert "claims" in body["questions"]["domain"]["criteria"]
        assert "Insurance claims" in body["questions"]["domain"]["criteria"]["claims"]
        assert "claims:理赔报案" in body["questions"]["intent"]["criteria"]

    asyncio.run(scenario())


def test_jev_masks_pii_before_sending() -> None:
    async def scenario() -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["state"] = json.loads(request.content)["state"]
            return httpx.Response(200, json=_response())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            classifier = JevIntentClassifier(
                registry=DomainRegistry.default(),
                base_url="https://example.test/jev",
                api_key="test-key",
                client=client,
                mask=lambda value: str(value).replace("13800138000", "[手机号]"),
            )
            await classifier.classify(_request("我的手机号是 13800138000，帮我查保单"))

        assert "13800138000" not in seen["state"]
        assert "[手机号]" in seen["state"]

    asyncio.run(scenario())


def test_jev_uses_translator_and_warns_without_it() -> None:
    async def with_translator() -> str:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["state"] = json.loads(request.content)["state"]
            return httpx.Response(200, json=_response())

        async def translator(text: str) -> str:
            return "EN: " + text

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            classifier = JevIntentClassifier(
                registry=DomainRegistry.default(),
                base_url="https://example.test/jev",
                api_key="test-key",
                client=client,
                translator=translator,
            )
            await classifier.classify(_request())
        return seen["state"]

    async def without_translator() -> str:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_response())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            classifier = JevIntentClassifier(
                registry=DomainRegistry.default(),
                base_url="https://example.test/jev",
                api_key="test-key",
                client=client,
            )
            decision = await classifier.classify(_request())
        return decision.warnings[0]

    assert asyncio.run(with_translator()).startswith("EN: ")
    assert asyncio.run(without_translator()) == "cjk_without_translation"


def test_jev_http_error_raises() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="upstream down")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            classifier = JevIntentClassifier(
                registry=DomainRegistry.default(),
                base_url="https://example.test/jev",
                api_key="test-key",
                client=client,
            )
            with pytest.raises(JevError):
                await classifier.classify(_request())

    asyncio.run(scenario())


def test_jev_corrects_unknown_domain_and_cross_domain_intent() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_response(
                domain="unknown",
                domain_probs={"claims": 0.60, "investment": 0.30},
                intent="investment:组合诊断",
                intent_probs={
                    "claims:理赔报案": 0.70,
                    "claims:保单查询": 0.10,
                    "investment:组合诊断": 0.15,
                },
            ))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            classifier = JevIntentClassifier(
                registry=DomainRegistry.default(),
                base_url="https://example.test/jev",
                api_key="test-key",
                client=client,
            )
            decision = await classifier.classify(_request())

        assert decision.domain == "claims"
        assert decision.intent == "理赔报案"
        assert "unknown_domain_corrected" in decision.warnings
        assert "intent_corrected_to_domain" in decision.warnings

    asyncio.run(scenario())


def test_jev_low_confidence_needs_clarification() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_response(
                domain_confidence=0.55,
                domain_probs={"claims": 0.55, "investment": 0.40, "general": 0.05},
                intent_confidence=0.52,
                intent_probs={"claims:理赔报案": 0.52, "claims:保单查询": 0.44},
            ))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            classifier = JevIntentClassifier(
                registry=DomainRegistry.default(),
                base_url="https://example.test/jev",
                api_key="test-key",
                client=client,
            )
            decision = await classifier.classify(_request())

        assert decision.needs_clarification is True
        assert "low_confidence" in decision.warnings
        assert "low_margin" in decision.warnings

    asyncio.run(scenario())


def test_jev_requires_api_key() -> None:
    with pytest.raises(ValueError):
        JevIntentClassifier(
            registry=DomainRegistry.default(),
            base_url="https://example.test/jev",
            api_key="",
        )
