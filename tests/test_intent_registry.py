"""领域注册表测试：YAML 加载、校验与解析。"""
from __future__ import annotations

import pytest

from claims_platform.intent.contracts import RouteDecision
from claims_platform.intent.registry import DomainRegistry


def test_default_registry_loads_expected_domains() -> None:
    registry = DomainRegistry.default()
    assert set(registry.names()) == {"claims", "investment", "general"}
    assert registry.get("claims").criteria_text().startswith("Insurance claims")
    assert registry.get("investment").intent("交易指令").risk == "high"
    assert registry.get("claims").intent("保单查询") is not None


def test_duplicate_domain_is_rejected() -> None:
    registry = DomainRegistry.default()
    with pytest.raises(ValueError):
        registry.register(registry.get("claims"))


def test_resolve_rejects_unknown_intent() -> None:
    registry = DomainRegistry.default()
    with pytest.raises(ValueError):
        registry.resolve(RouteDecision(domain="claims", intent="不存在的意图", confidence=0.9))
    manifest = registry.resolve(RouteDecision(domain="claims", intent="理赔报案", confidence=0.9))
    assert manifest.name == "claims"


def test_missing_config_raises() -> None:
    with pytest.raises(FileNotFoundError):
        DomainRegistry.from_yaml("definitely-missing-domains.yaml")
