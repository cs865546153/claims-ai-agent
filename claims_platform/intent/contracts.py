"""意图路由公共契约：领域清单、请求、决策与分类器接口。

该模块不依赖 LangChain/FastAPI，领域包、评测脚本和测试都可以直接复用。
"""
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

RiskLevel = Literal["low", "medium", "high"]
DomainMode = Literal["conversation", "case"]


class IntentSpec(BaseModel):
    """领域内的一个意图及其路由元数据。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    # JEV 是英文优先模型；提供英文描述可显著提升跨语言路由质量。
    description_en: str | None = Field(default=None, max_length=500)
    examples: list[str] = Field(default_factory=list, max_length=20)
    risk: RiskLevel = "low"
    mode: DomainMode = "conversation"

    def criteria_text(self) -> str:
        """返回给意图引擎的意图描述，优先英文。"""
        return self.description_en or self.description


class DomainManifest(BaseModel):
    """一个可插拔领域的清单；新增领域只需提供该清单和图实现。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=32)
    description: str = Field(min_length=1, max_length=500)
    description_en: str | None = Field(default=None, max_length=500)
    version: str = Field(default="1.0.0", max_length=32)
    intents: list[IntentSpec] = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique_intents(self) -> "DomainManifest":
        names = [item.name for item in self.intents]
        if len(names) != len(set(names)):
            raise ValueError(f"领域 {self.name} 存在重复意图")
        return self

    def criteria_text(self) -> str:
        return self.description_en or self.description

    def intent(self, name: str) -> IntentSpec | None:
        return next((item for item in self.intents if item.name == name), None)


class Turn(BaseModel):
    """最近对话中的一轮。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class IntentRequest(BaseModel):
    """一次意图识别请求；领域清单由分类器持有的注册表提供。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000)
    history: list[Turn] = Field(default_factory=list, max_length=12)
    active_domain: str | None = Field(default=None, max_length=32)
    attachments: list[str] = Field(default_factory=list, max_length=6)


class RouteDecision(BaseModel):
    """统一的路由结果；不同引擎必须收敛到该结构。"""

    model_config = ConfigDict(extra="forbid")

    domain: str
    intent: str
    confidence: float = Field(ge=0, le=1)
    margin: float | None = Field(default=None, ge=0)
    domain_probabilities: dict[str, float] = Field(default_factory=dict)
    intent_probabilities: dict[str, float] = Field(default_factory=dict)
    slots: dict[str, str] = Field(default_factory=dict)
    needs_clarification: bool = False
    engine: str = "unknown"
    latency_ms: int | None = Field(default=None, ge=0)
    fallback_used: bool = False
    fallback_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    shadow: dict[str, Any] | None = None


class IntentClassificationError(RuntimeError):
    """意图识别失败；调用方应决定回落或向用户澄清。"""


@runtime_checkable
class IntentClassifier(Protocol):
    """可替换的意图识别引擎（JEV / LLM / 其他）。"""

    async def classify(self, request: IntentRequest) -> RouteDecision:
        ...
