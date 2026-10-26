"""Rerank 实现：本地 BGE-Reranker（Cross-Encoder）优先，词项重排兜底。

BM25 是召回/词法打分，不是 Cross-Encoder reranker。这里把两者分层：

* 召回：BM25、BGE-M3 向量、标题/章节元数据；
* rerank：BGE-Reranker 对 ``query + document`` 成对打分；
* 降级：模型服务不可用时使用 :class:`LexicalReranker`，保证链路可用。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

import httpx
from langchain_core.documents import Document

from settings import Settings
from tools.rag_retrieval import chinese_tokens

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    """接收 query 和候选文档，返回重排后的文档列表。"""

    def __call__(self, query: str, documents: list[Document]) -> list[Document]:
        ...


class RerankUnavailable(RuntimeError):
    """重排服务不可用；调用方应降级到词项重排。"""


class LexicalReranker:
    """无模型兜底：词项覆盖、短语命中、元数据命中和原排名先验。"""

    def __init__(self, *, phrase_weight: float = 0.20) -> None:
        if not 0 <= phrase_weight <= 1:
            raise ValueError('phrase_weight 必须在 0 到 1 之间')
        self.phrase_weight = phrase_weight

    def __call__(self, query: str, documents: list[Document]) -> list[Document]:
        if not documents:
            return []
        query = query.strip()
        query_tokens = set(chinese_tokens(query))
        query_lower = query.lower()
        total = len(documents)
        token_weight = 0.55
        meta_weight = 0.15
        prior_weight = max(0.0, 1.0 - token_weight - self.phrase_weight - meta_weight)

        scored: list[tuple[float, int, Document]] = []
        for index, document in enumerate(documents):
            text = document.page_content
            text_lower = text.lower()
            document_tokens = set(chinese_tokens(text))
            overlap = (
                len(query_tokens & document_tokens) / len(query_tokens)
                if query_tokens else 0.0
            )
            phrase = 1.0 if query_lower and query_lower in text_lower else 0.0
            metadata = document.metadata
            metadata_text = ' '.join(
                str(metadata.get(key) or '')
                for key in ('title', 'chapter', 'topic', 'source')
            )
            metadata_tokens = set(chinese_tokens(metadata_text))
            metadata_overlap = (
                len(query_tokens & metadata_tokens) / len(query_tokens)
                if query_tokens else 0.0
            )
            prior = 1.0 - index / max(total, 1)
            score = (
                token_weight * overlap
                + self.phrase_weight * phrase
                + meta_weight * metadata_overlap
                + prior_weight * prior
            )
            scored.append((score, index, document))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [document for _, _, document in scored]


class HttpBgeReranker:
    """调用本地 ``/v1/rerank`` 的 BGE-Reranker 客户端。

    服务由 ``scripts/embed_server.py`` 提供。失败后进入冷却期，避免每个请求
    都等待超时；冷却结束后自动重试，模型下载/服务重启后无需重启主进程。
    """

    def __init__(
        self,
        base_url: str,
        model: str = 'bge-reranker-base',
        *,
        timeout: float = 10.0,
        top_n: int | None = None,
        retry_cooldown: float = 60.0,
    ) -> None:
        base = base_url.rstrip('/')
        self.url = base if base.endswith('/rerank') else f'{base}/rerank'
        self.model = model
        self.timeout = timeout
        self.top_n = top_n
        self.retry_cooldown = retry_cooldown
        self._disabled_reason: str | None = None
        self._retry_at = 0.0

    @property
    def disabled(self) -> bool:
        return self._disabled_reason is not None and time.monotonic() < self._retry_at

    def __call__(self, query: str, documents: list[Document]) -> list[Document]:
        if not documents:
            return []
        if self._disabled_reason and time.monotonic() < self._retry_at:
            raise RerankUnavailable(self._disabled_reason)

        payload: dict[str, object] = {
            'model': self.model,
            'query': query,
            'documents': [document.page_content for document in documents],
        }
        if self.top_n:
            payload['top_n'] = min(self.top_n, len(documents))

        try:
            response = httpx.post(self.url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
            results = body.get('results')
            if not isinstance(results, list) or not results:
                raise RerankUnavailable('rerank 服务返回空结果')
        except Exception as exc:  # noqa: BLE001 - 外部服务失败必须降级
            self._disabled_reason = f'{type(exc).__name__}: {exc}'
            self._retry_at = time.monotonic() + self.retry_cooldown
            raise RerankUnavailable(self._disabled_reason) from exc

        scores: dict[int, float] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item['index'])
                score = float(item['relevance_score'])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= index < len(documents):
                scores[index] = score
        if not scores:
            self._disabled_reason = 'rerank 服务没有返回可用 index/score'
            self._retry_at = time.monotonic() + self.retry_cooldown
            raise RerankUnavailable(self._disabled_reason)

        self._disabled_reason = None
        self._retry_at = 0.0
        ordered = sorted(
            enumerate(documents),
            key=lambda pair: (-scores.get(pair[0], float('-inf')), pair[0]),
        )
        return [document for _, document in ordered]


class FallbackReranker:
    """先调用主 reranker；失败时固定降级到词项重排。"""

    def __init__(
        self,
        primary: Callable[[str, list[Document]], list[Document]],
        fallback: Callable[[str, list[Document]], list[Document]] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or LexicalReranker()
        self._warned = False
        self.last_error: str | None = None

    def __call__(self, query: str, documents: list[Document]) -> list[Document]:
        try:
            result = self.primary(query, documents)
        except Exception as exc:  # noqa: BLE001 - rerank 失败不能阻断检索
            self.last_error = f'{type(exc).__name__}: {exc}'
            if not self._warned:
                logger.warning('BGE rerank 不可用，降级为词项重排：%s', self.last_error)
                self._warned = True
            return self.fallback(query, documents)
        self.last_error = None
        return result


def build_reranker(settings: Settings | None = None) -> Reranker | None:
    """按配置构建 reranker；关闭时返回 ``None``。"""
    cfg = settings or Settings()
    if not cfg.rerank_enabled:
        return None
    primary = HttpBgeReranker(
        cfg.rerank_base_url,
        cfg.rerank_model,
        timeout=cfg.rerank_timeout,
        top_n=cfg.rerank_top_n,
        retry_cooldown=cfg.rerank_retry_cooldown,
    )
    return FallbackReranker(primary, LexicalReranker())


__all__ = [
    'FallbackReranker',
    'HttpBgeReranker',
    'LexicalReranker',
    'RerankUnavailable',
    'Reranker',
    'build_reranker',
]
