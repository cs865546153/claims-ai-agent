"""投资域请求、响应与建议契约。

投资咨询可以走对话链路；交易指令属于高风险案件模式，必须经过适当性校验、
二次确认和人工审批，模型不能直接下单。
"""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

InvestmentIntent = Literal["投资咨询", "组合诊断", "风险评估", "产品查询", "交易指令"]
RiskLevel = Literal["低", "中", "高", "待核实"]
Suitability = Literal["适合", "不适合", "待核实"]
InvestmentDecision = Literal[
    "pending",
    "advise",
    "review",
    "execute",
    "reject",
    "cancelled",
]


class InvestmentRequest(BaseModel):
    """一次投资域请求；交易指令通过 confirmed 进入二次确认。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=1, max_length=64, description="请求标识")
    question: str = Field(min_length=1, max_length=4000, description="用户问题或指令")
    intent: InvestmentIntent = "投资咨询"
    risk_profile: str | None = Field(default=None, max_length=32)
    portfolio_id: str | None = Field(default=None, max_length=64)
    product_id: str | None = Field(default=None, max_length=64)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    confirmed: bool = False


class InvestmentAdvice(BaseModel):
    """教育性投资分析；不构成收益承诺或自动交易指令。"""

    model_config = ConfigDict(extra="forbid")

    summary: str
    allocation: list[dict[str, str]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "以上为基于当前可见数据的教育性分析，不构成投资建议，不承诺收益。"
        "任何交易指令都需要二次确认和人工审批。"
    )


class InvestmentResponse(BaseModel):
    """投资域处理结果；decision 只是建议，executed 才代表适配器已执行。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64)
    intent: InvestmentIntent
    decision: InvestmentDecision = "pending"
    phase: str = "pending"
    risk_level: RiskLevel = "待核实"
    suitability: Suitability = "待核实"
    requires_confirmation: bool = False
    requires_human_review: bool = False
    executed: bool = False
    demo: bool = False
    message: str


class DemoInvestmentRunResponse(BaseModel):
    """本地合成投资请求的一次完整运行结果。"""

    request: InvestmentRequest
    result: InvestmentResponse
    advice: InvestmentAdvice | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)


class InvestmentConfirmation(BaseModel):
    """交易二次确认输入。"""

    model_config = ConfigDict(extra="forbid")
    confirmed: bool


class InvestmentReviewInput(BaseModel):
    """交易人工审批输入；审核员和理由必须留痕。"""

    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject", "review"]
    reviewer: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=1000)


class InvestmentRAGQuery(BaseModel):
    """投资知识库检索请求；只读，不涉及交易。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=4, ge=1, le=8)


class InvestmentRAGCitation(BaseModel):
    """一条可追溯的投资知识引用。"""

    model_config = ConfigDict(extra="forbid")
    citation_id: str
    doc_id: str
    domain: str = ""
    title: str
    topic: str = ""
    chapter: str
    source: str
    source_url: str = ""
    as_of: str = ""
    text: str


class InvestmentRAGResponse(BaseModel):
    """投资知识库混合检索结果；degraded 表示当前只有 BM25。"""

    model_config = ConfigDict(extra="forbid")
    query: str
    documents: list[InvestmentRAGCitation] = Field(default_factory=list)
    vector_ready: bool = False
    degraded: bool = True
    vector_error: str | None = None
    corpus_size: int = 0
    collection: str = "investment_wiki"
    retrieval: dict[str, Any] = Field(default_factory=dict)
