"""意图路由公共层：契约、领域注册表与可替换分类器。"""

from .adapter import AssistantIntentRouter, AssistantRoute
from .contracts import (
    DomainManifest,
    IntentClassificationError,
    IntentClassifier,
    IntentRequest,
    IntentSpec,
    RouteDecision,
    Turn,
)
from .registry import DomainRegistry

__all__ = [
    "AssistantIntentRouter",
    "AssistantRoute",
    "DomainManifest",
    "DomainRegistry",
    "IntentClassificationError",
    "IntentClassifier",
    "IntentRequest",
    "IntentSpec",
    "RouteDecision",
    "Turn",
]
