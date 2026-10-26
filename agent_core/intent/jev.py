"""JEV 意图识别适配器：把 choice 问题映射为领域/意图概率。

实测契约（ateve-jev-v1）：
  POST {base_url}
  {"model": "...", "state": "...", "questions": {"domain": {"type": "choice",
   "instructions": "...", "criteria": {"claims": "..."}}}}
  返回 answers.<问题>.{choice, probabilities, confidence}

注意：该模型英文输入效果显著优于中文。未配置 translator 时会记录
cjk_without_translation 警告，交由上层决定是否回落。
"""
from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .contracts import IntentRequest, RouteDecision
from .registry import DomainRegistry

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class JevError(RuntimeError):
    """JEV 调用或响应解析失败。"""


def _clamp(value: Any) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _probability_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, score in value.items():
        parsed = _clamp(score)
        if parsed is not None:
            result[str(key)] = parsed
    return result


def _top_margin(probabilities: dict[str, float]) -> float | None:
    if len(probabilities) < 2:
        return None
    values = sorted(probabilities.values(), reverse=True)
    return max(0.0, values[0] - values[1])


class JevIntentClassifier:
    """JEV 意图引擎；一次调用同时返回领域与意图。"""

    engine_name = "jev"

    def __init__(
        self,
        *,
        registry: DomainRegistry,
        base_url: str,
        api_key: str,
        model: str = "ateve-jev-v1",
        timeout_s: float = 10.0,
        client: httpx.AsyncClient | None = None,
        translator: Callable[[str], Awaitable[str]] | None = None,
        mask: Callable[[Any], Any] | None = None,
        confidence_threshold: float = 0.8,
        margin_threshold: float = 0.2,
    ) -> None:
        if not base_url:
            raise ValueError("JEV base_url 不能为空")
        if not api_key:
            raise ValueError("JEV api_key 不能为空")
        self.registry = registry
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.translator = translator
        self.mask = mask
        self.confidence_threshold = confidence_threshold
        self.margin_threshold = margin_threshold
        self._client = client
        self._owns_client = False

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
            self._owns_client = False

    async def classify(self, request: IntentRequest) -> RouteDecision:
        started = time.monotonic()
        warnings: list[str] = []
        state = self._serialize(request)
        # 先脱敏再翻译/发送，避免 PII 离开本进程。
        if self.mask is not None:
            state = str(self.mask(state))
        if self.translator is not None:
            try:
                state = await self.translator(state)
            except Exception:
                warnings.append("translation_failed")
        elif CJK_RE.search(state):
            warnings.append("cjk_without_translation")

        payload = {
            "model": self.model,
            "state": state,
            "questions": self._questions(),
        }
        data = await self._post(payload)
        decision = self._parse(data, warnings)
        decision.latency_ms = int((time.monotonic() - started) * 1000)
        return decision

    def _serialize(self, request: IntentRequest) -> str:
        lines: list[str] = []
        if request.active_domain:
            lines.append(f"Active domain: {request.active_domain}")
        for turn in request.history[-6:]:
            speaker = "User" if turn.role == "user" else "Assistant"
            lines.append(f"{speaker}: {turn.content}")
        lines.append(f"Current: {request.message}")
        if request.attachments:
            lines.append("Attachments: " + ", ".join(request.attachments))
        return "\n".join(lines)

    def _questions(self) -> dict[str, Any]:
        domains = self.registry.all()
        domain_criteria = {item.name: item.criteria_text() for item in domains}
        intent_criteria = {
            f"{domain.name}:{intent.name}": intent.criteria_text()
            for domain in domains
            for intent in domain.intents
        }
        return {
            "domain": {
                "type": "choice",
                "instructions": (
                    "Which business domain does the current user message belong to? "
                    "Use the active domain only when the message is ambiguous."
                ),
                "criteria": domain_criteria,
            },
            "intent": {
                "type": "choice",
                "instructions": (
                    "What is the user's intent within the selected domain? "
                    "Pick the most specific intent that matches the current message."
                ),
                "criteria": intent_criteria,
            },
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._http().post(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise JevError(f"JEV 请求失败：{type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise JevError(f"JEV HTTP {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise JevError("JEV 返回非 JSON") from exc
        if not isinstance(data, dict):
            raise JevError("JEV 返回格式无效")
        return data

    def _parse(self, data: dict[str, Any], warnings: list[str]) -> RouteDecision:
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise JevError("JEV 响应缺少 answers")
        domain_answer = answers.get("domain")
        intent_answer = answers.get("intent")
        if not isinstance(domain_answer, dict) or not isinstance(intent_answer, dict):
            raise JevError("JEV 响应缺少 domain/intent")

        domain_probs = _probability_map(domain_answer.get("probabilities"))
        domain = domain_answer.get("choice")
        if not isinstance(domain, str) or domain not in self.registry.names():
            known = {key: score for key, score in domain_probs.items() if key in self.registry.names()}
            if not known:
                raise JevError(f"JEV 返回未知领域：{domain!r}")
            domain = max(known, key=known.get)
            warnings.append("unknown_domain_corrected")

        domain_conf = _clamp(domain_answer.get("confidence"))
        if domain_conf is None:
            domain_conf = domain_probs.get(domain, 0.0)
        manifest = self.registry.get(domain)

        intent_probs_all = _probability_map(intent_answer.get("probabilities"))
        intent_probs = {
            key.split(":", 1)[1]: score
            for key, score in intent_probs_all.items()
            if key.startswith(domain + ":")
        }
        intent = intent_answer.get("choice")
        if isinstance(intent, str) and intent.startswith(domain + ":"):
            intent = intent.split(":", 1)[1]
        if not isinstance(intent, str) or manifest.intent(intent) is None:
            if intent_probs:
                intent = max(intent_probs, key=intent_probs.get)
                warnings.append("intent_corrected_to_domain")
            else:
                intent = manifest.intents[0].name
                warnings.append("intent_missing")

        intent_conf = intent_probs.get(intent)
        if intent_conf is None:
            intent_conf = _clamp(intent_answer.get("confidence")) or 0.0
        confidence = min(domain_conf, intent_conf)

        margins = [
            value
            for value in (_top_margin(domain_probs), _top_margin(intent_probs))
            if value is not None
        ]
        margin = min(margins) if margins else None
        needs_clarification = confidence < self.confidence_threshold
        if confidence < self.confidence_threshold:
            warnings.append("low_confidence")
        if margin is not None and margin < self.margin_threshold:
            needs_clarification = True
            warnings.append("low_margin")

        return RouteDecision(
            domain=domain,
            intent=intent,
            confidence=confidence,
            margin=margin,
            domain_probabilities=domain_probs or {domain: domain_conf},
            intent_probabilities=intent_probs or {intent: intent_conf},
            needs_clarification=needs_clarification,
            engine="jev",
            warnings=warnings,
        )


__all__ = ["JevError", "JevIntentClassifier"]
