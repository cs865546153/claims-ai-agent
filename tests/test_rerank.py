"""Rerank 客户端与降级行为。"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.documents import Document

from settings import Settings
from tools.rerank import FallbackReranker, HttpBgeReranker, LexicalReranker, RerankUnavailable, build_reranker


def _documents() -> list[Document]:
    return [
        Document(page_content='基金有市场风险', metadata={'doc_id': 'a'}),
        Document(page_content='BGE-Reranker 用于精排', metadata={'doc_id': 'b'}),
    ]


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def test_http_reranker_orders_by_server_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, json: dict[str, Any], timeout: float) -> _Response:
        assert url.endswith('/v1/rerank')
        return _Response({'results': [
            {'index': 0, 'relevance_score': 0.1},
            {'index': 1, 'relevance_score': 0.9},
        ]})

    monkeypatch.setattr('tools.rerank.httpx.post', fake_post)
    reranker = HttpBgeReranker('http://127.0.0.1:8010/v1', timeout=0.1)

    ordered = reranker('精排', _documents())

    assert [document.metadata['doc_id'] for document in ordered] == ['b', 'a']


def test_http_reranker_disables_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_post(*args: Any, **kwargs: Any) -> _Response:
        raise RuntimeError('service down')

    monkeypatch.setattr('tools.rerank.httpx.post', broken_post)
    reranker = HttpBgeReranker('http://127.0.0.1:8010/v1', timeout=0.1)

    with pytest.raises(RerankUnavailable):
        reranker('精排', _documents())
    with pytest.raises(RerankUnavailable):
        reranker('精排', _documents())


def test_http_reranker_retries_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def flaky_post(url: str, json: dict[str, Any], timeout: float) -> _Response:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('cold start')
        return _Response({'results': [
            {'index': 0, 'relevance_score': 0.8},
            {'index': 1, 'relevance_score': 0.2},
        ]})

    monkeypatch.setattr('tools.rerank.httpx.post', flaky_post)
    reranker = HttpBgeReranker('http://127.0.0.1:8010/v1', timeout=10.0, retry_cooldown=60.0)

    with pytest.raises(RerankUnavailable):
        reranker('精排', _documents())
    assert reranker.disabled is True
    assert len(calls) == 1

    reranker._retry_at = 0.0
    ordered = reranker('精排', _documents())

    assert [document.metadata['doc_id'] for document in ordered] == ['a', 'b']
    assert reranker.disabled is False
    assert len(calls) == 2


def test_fallback_reranker_uses_lexical_when_primary_fails() -> None:
    def broken(*args: Any, **kwargs: Any) -> list[Document]:
        raise RuntimeError('down')

    reranker = FallbackReranker(broken, LexicalReranker())
    ordered = reranker('BGE-Reranker 精排', _documents())

    assert ordered[0].metadata['doc_id'] == 'b'
    assert reranker.last_error and 'down' in reranker.last_error


def test_build_reranker_can_be_disabled() -> None:
    assert build_reranker(Settings(_env_file=None, rerank_enabled=False)) is None
