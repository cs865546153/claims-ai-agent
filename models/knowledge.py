"""通用知识库 RAG 请求、引用和响应契约。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeRAGQuery(BaseModel):
    """一次通用知识库检索或回答请求。"""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    domain: str = Field(default='general', min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict)


class KnowledgeCitation(BaseModel):
    """一条可追溯的知识库引用。"""

    model_config = ConfigDict(extra='forbid')

    citation_id: str
    doc_id: str
    domain: str = ''
    title: str = ''
    topic: str = ''
    chapter: str = ''
    source: str = ''
    source_url: str = ''
    as_of: str = ''
    text: str


class KnowledgeSearchResponse(BaseModel):
    """多路召回 + rerank 后的 Top-K 结果。"""

    model_config = ConfigDict(extra='forbid')

    query: str
    domain: str
    documents: list[KnowledgeCitation] = Field(default_factory=list)
    vector_ready: bool = False
    degraded: bool = True
    vector_error: str | None = None
    corpus_size: int = 0
    collection: str = ''
    retrieval: dict[str, Any] = Field(default_factory=dict)


class KnowledgeAnswerResponse(KnowledgeSearchResponse):
    """LLM 回答与引用校验结果。"""

    answer: str = ''
    requires_manual_review: bool = False
    citation_check: str = ''


__all__ = [
    'KnowledgeAnswerResponse',
    'KnowledgeCitation',
    'KnowledgeRAGQuery',
    'KnowledgeSearchResponse',
]
