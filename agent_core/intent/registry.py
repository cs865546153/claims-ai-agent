"""领域注册表：从 YAML 加载领域清单，供意图路由与领域解析使用。"""
from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import yaml

from .contracts import DomainManifest, RouteDecision

# 目录名用 configs 而不是 config，避免与项目根目录的 config.py 同名冲突。
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "domains.yaml"


class DomainRegistry:
    """启动时构建、运行时只读的领域注册表。"""

    def __init__(self, domains: Iterable[DomainManifest] = ()) -> None:
        self._domains: dict[str, DomainManifest] = {}
        for manifest in domains:
            self.register(manifest)

    def register(self, manifest: DomainManifest) -> None:
        if manifest.name in self._domains:
            raise ValueError(f"领域重复注册：{manifest.name}")
        self._domains[manifest.name] = manifest

    def get(self, name: str) -> DomainManifest:
        try:
            return self._domains[name]
        except KeyError:
            raise KeyError(f"未注册领域：{name}") from None

    def all(self) -> list[DomainManifest]:
        return list(self._domains.values())

    def names(self) -> list[str]:
        return list(self._domains)

    def resolve(self, decision: RouteDecision) -> DomainManifest:
        """校验路由结果确实落在已注册领域和意图内。"""
        manifest = self.get(decision.domain)
        if manifest.intent(decision.intent) is None:
            raise ValueError(f"领域 {decision.domain} 不存在意图：{decision.intent}")
        return manifest

    @classmethod
    def from_yaml(cls, path: str | Path | None = None) -> "DomainRegistry":
        config_path = Path(path or os.getenv("DOMAINS_CONFIG") or DEFAULT_CONFIG_PATH)
        if not config_path.exists():
            raise FileNotFoundError(f"领域配置不存在：{config_path}")
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        items = raw.get("domains")
        if not isinstance(items, list) or not items:
            raise ValueError(f"领域配置必须包含非空 domains 列表：{config_path}")
        return cls(DomainManifest.model_validate(item) for item in items)

    @classmethod
    def default(cls) -> "DomainRegistry":
        return cls.from_yaml()


__all__ = ["DEFAULT_CONFIG_PATH", "DomainRegistry"]
