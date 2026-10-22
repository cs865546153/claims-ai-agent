"""按配置组装意图分类器：JEV/LLM 可组合为主路由、兜底与影子。"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .contracts import IntentClassifier, RouteDecision
from .hybrid import HybridIntentClassifier
from .jev import JevIntentClassifier
from .llm import LLMIntentClassifier, LLMTranslator
from .registry import DomainRegistry

LOGGER = logging.getLogger("claims.intent")

# 预设：
#   shadow  = LLM 主路由 + JEV 影子（默认，中文安全）
#   hybrid   = JEV 主路由 + LLM 兜底（中文评测达标后启用）
#   jev/llm = 单引擎
PRESETS: dict[str, dict[str, str | None]] = {
    "shadow": {"primary": "llm", "fallback": None, "shadow": "jev"},
    "hybrid": {"primary": "jev", "fallback": "llm", "shadow": None},
    "jev": {"primary": "jev", "fallback": None, "shadow": None},
    "llm": {"primary": "llm", "fallback": None, "shadow": None},
}


@dataclass(frozen=True)
class IntentConfig:
    """意图路由配置；可由 Settings 或测试直接构造。"""

    primary: str = "llm"
    fallback: str | None = None
    shadow: str | None = "jev"
    confidence_threshold: float = 0.8
    margin_threshold: float = 0.2
    translate_to_english: bool = False
    jev_base_url: str = "https://tokendance.space/gateway/typesafe/v1/systemone"
    jev_api_key: str = ""
    jev_model: str = "ateve-jev-v1"
    jev_timeout_s: float = 10.0

    @classmethod
    def from_settings(cls, settings: Any = None) -> "IntentConfig":
        if settings is None:
            from settings import Settings

            settings = Settings()
        engine = str(getattr(settings, "intent_engine", "shadow") or "shadow").lower()
        preset = PRESETS.get(engine, PRESETS["shadow"])

        def pick(value: Any, key: str) -> str | None:
            if value is None:
                return preset[key]
            text = str(value).strip().lower()
            return None if text in ("", "none", "off") else text

        raw_key = getattr(settings, "jev_api_key", "")
        api_key = raw_key.get_secret_value() if hasattr(raw_key, "get_secret_value") else str(raw_key or "")
        return cls(
            primary=pick(getattr(settings, "intent_primary", None), "primary") or "llm",
            fallback=pick(getattr(settings, "intent_fallback", None), "fallback"),
            shadow=pick(getattr(settings, "intent_shadow", None), "shadow"),
            confidence_threshold=float(getattr(settings, "intent_confidence_threshold", 0.8)),
            margin_threshold=float(getattr(settings, "intent_margin_threshold", 0.2)),
            translate_to_english=bool(getattr(settings, "intent_translate_to_english", False)),
            jev_base_url=str(getattr(settings, "jev_base_url", cls.jev_base_url)),
            jev_api_key=api_key,
            jev_model=str(getattr(settings, "jev_model", "ateve-jev-v1")),
            jev_timeout_s=float(getattr(settings, "jev_timeout_s", 10.0)),
        )


def _default_mask(value: Any) -> Any:
    """复用现有 PII 脱敏；导入失败时保持原值，便于独立使用。"""
    try:
        from agents.middleware_audit import mask_pii
    except Exception:  # noqa: BLE001
        return value
    return mask_pii(value)


def build_intent_classifier(
    config: IntentConfig | None = None,
    *,
    registry: DomainRegistry | None = None,
    llm_model: Any = None,
    jev_client: Any = None,
    translator: Callable[[str], Awaitable[str]] | None = None,
    mask: Callable[[Any], Any] | None = None,
    on_decision: Callable[[RouteDecision], None] | None = None,
) -> HybridIntentClassifier:
    """按配置构建分类器；缺少 JEV key 时按角色降级而不是整体失败。"""
    cfg = config or IntentConfig.from_settings()
    domains = registry or DomainRegistry.default()
    effective_mask = mask or _default_mask

    roles = {cfg.primary, cfg.fallback, cfg.shadow}
    needs_llm = cfg.translate_to_english or "llm" in roles
    resolved_llm_model = llm_model
    llm: LLMIntentClassifier | None = None
    if needs_llm:
        if resolved_llm_model is None:
            from config import get_model

            resolved_llm_model = get_model("classification")
        llm = LLMIntentClassifier(
            registry=domains,
            model=resolved_llm_model,
            mask=effective_mask,
            confidence_threshold=cfg.confidence_threshold,
        )

    if cfg.translate_to_english:
        translator = translator or LLMTranslator(resolved_llm_model)

    jev: JevIntentClassifier | None = None

    def make_jev() -> JevIntentClassifier:
        nonlocal jev
        if jev is None:
            if not cfg.jev_api_key:
                raise ValueError("JEV_API_KEY 未配置")
            jev = JevIntentClassifier(
                registry=domains,
                base_url=cfg.jev_base_url,
                api_key=cfg.jev_api_key,
                model=cfg.jev_model,
                timeout_s=cfg.jev_timeout_s,
                client=jev_client,
                translator=translator,
                mask=effective_mask,
                confidence_threshold=cfg.confidence_threshold,
                margin_threshold=cfg.margin_threshold,
            )
        return jev

    def make(name: str) -> IntentClassifier:
        if name == "jev":
            return make_jev()
        if name == "llm":
            if llm is None:
                raise ValueError("LLM 模型不可用")
            return llm
        raise ValueError(f"未知意图引擎：{name}")

    primary = make(cfg.primary)

    fallback: IntentClassifier | None = None
    if cfg.fallback:
        try:
            fallback = make(cfg.fallback)
        except ValueError as exc:
            LOGGER.warning("兜底意图引擎不可用，已跳过：%s", exc)

    shadow: IntentClassifier | None = None
    if cfg.shadow:
        try:
            shadow = make(cfg.shadow)
        except ValueError as exc:
            LOGGER.warning("影子意图引擎不可用，已跳过：%s", exc)

    return HybridIntentClassifier(
        primary=primary,
        fallback=fallback,
        shadow=shadow,
        confidence_threshold=cfg.confidence_threshold,
        margin_threshold=cfg.margin_threshold,
        on_decision=on_decision,
    )


__all__ = ["IntentConfig", "PRESETS", "build_intent_classifier"]
