"""LLM 意图路由器：中文场景的默认主路由，也是 JEV 的兜底。"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .contracts import IntentClassificationError, IntentRequest, RouteDecision
from .registry import DomainRegistry

_JSON_RE = re.compile(r"\{.*\}", re.S)


def _text(value: Any) -> str:
    """兼容字符串、AIMessage 和多模态文本块。"""
    content = getattr(value, "content", value)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return str(content)


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


class LLMIntentClassifier:
    """用通用聊天模型做跨域路由；输出必须收敛到 RouteDecision。"""

    engine_name = "llm"

    def __init__(
        self,
        *,
        registry: DomainRegistry,
        model: Any,
        mask: Callable[[Any], Any] | None = None,
        confidence_threshold: float = 0.8,
    ) -> None:
        self.registry = registry
        self.model = model
        self.mask = mask
        self.confidence_threshold = confidence_threshold

    async def classify(self, request: IntentRequest) -> RouteDecision:
        started = time.monotonic()
        messages = [
            SystemMessage(content=self._system_prompt()),
            HumanMessage(content=self._user_prompt(request)),
        ]
        try:
            response = await self.model.ainvoke(messages)
        except Exception as exc:
            raise IntentClassificationError(f"LLM 意图调用失败：{type(exc).__name__}") from exc

        data = self._parse(_text(response))
        domain = data.get("domain")
        intent = data.get("intent")
        if not isinstance(domain, str) or domain not in self.registry.names():
            raise IntentClassificationError(f"LLM 返回未知领域：{domain!r}")
        manifest = self.registry.get(domain)
        if isinstance(intent, str) and intent.startswith(domain + ":"):
            intent = intent.split(":", 1)[1]
        if not isinstance(intent, str) or manifest.intent(intent) is None:
            raise IntentClassificationError(f"LLM 返回未知意图：{intent!r}")

        confidence = _clamp(data.get("confidence"))
        warnings = ["low_confidence"] if confidence < self.confidence_threshold else []
        return RouteDecision(
            domain=domain,
            intent=intent,
            confidence=confidence,
            needs_clarification=confidence < self.confidence_threshold,
            engine="llm",
            latency_ms=int((time.monotonic() - started) * 1000),
            warnings=warnings,
        )

    def _system_prompt(self) -> str:
        lines = [
            "你是跨领域意图路由器。只返回JSON对象，不要Markdown，不要解释。",
            'JSON格式：{"domain":"...","intent":"...","confidence":0.0}',
            "domain 与 intent 必须从下列目录中选择。",
            "如果当前问题省略主语，继承最近对话的主题；如果用户明确切换主题，以当前问题为准。",
            "不确定时降低 confidence，不要硬猜。",
            "",
            "领域与意图目录：",
        ]
        for domain in self.registry.all():
            lines.append(f"- {domain.name}（{domain.description}）")
            for intent in domain.intents:
                lines.append(f"  - {intent.name}：{intent.description}（risk={intent.risk}, mode={intent.mode}）")
        return "\n".join(lines)

    def _user_prompt(self, request: IntentRequest) -> str:
        def safe(value: str) -> str:
            return str(self.mask(value)) if self.mask is not None else value

        recent = "\n".join(
            f"{'用户' if turn.role == 'user' else '助手'}：{safe(turn.content)}"
            for turn in request.history[-6:]
        )
        active = f"当前领域：{request.active_domain}\n" if request.active_domain else ""
        attachments = f"附件：{', '.join(request.attachments)}\n" if request.attachments else ""
        return (
            f"{active}最近对话：\n{recent or '（无）'}\n"
            f"{attachments}当前消息：{safe(request.message)}"
        )

    @staticmethod
    def _parse(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```")
            text = text.removesuffix("```").strip()
        match = _JSON_RE.search(text)
        if match is None:
            raise IntentClassificationError("LLM 未返回 JSON 路由结果")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise IntentClassificationError("LLM 返回的 JSON 无法解析") from exc
        if not isinstance(data, dict):
            raise IntentClassificationError("LLM 返回的路由结果不是对象")
        return data


class LLMTranslator:
    """可选的翻译前置；仅在显式开启 INTENT_TRANSLATE_TO_ENGLISH 时使用。"""

    def __init__(self, model: Any) -> None:
        self.model = model

    async def __call__(self, text: str) -> str:
        response = await self.model.ainvoke([
            SystemMessage(content=(
                "Translate the user content into English. "
                "Preserve names, numbers, and structured fragments. Output only the translation."
            )),
            HumanMessage(content=text),
        ])
        translated = _text(response).strip()
        if not translated:
            raise ValueError("翻译结果为空")
        return translated


__all__ = ["LLMIntentClassifier", "LLMTranslator"]
