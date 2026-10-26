"""通用知识库 RAG：加载、多路召回、rerank、回答与 API。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app import create_app
from tools.knowledge_rag import (
    KnowledgeAnswerError,
    KnowledgeBase,
    KnowledgeRAG,
    KnowledgeSource,
    MultiRouteRetriever,
    RetrievalRoute,
    load_knowledge_documents,
)
from tools.rerank import FallbackReranker, LexicalReranker


def _docs() -> list[Document]:
    return [
        Document(
            page_content='基金风险包括市场风险、信用风险和流动性风险。',
            metadata={
                'doc_id': 'fund-risk',
                'domain': 'general',
                'title': '基金风险',
                'chapter': '风险',
                'source': 'fund.md',
            },
        ),
        Document(
            page_content='知识库 RAG 使用 BM25、向量和元数据多路召回。',
            metadata={
                'doc_id': 'rag-recall',
                'domain': 'general',
                'title': 'RAG 召回',
                'chapter': '多路召回',
                'source': 'rag.md',
            },
        ),
        Document(
            page_content='BGE-Reranker 对 query 和文档成对打分，用于精排。',
            metadata={
                'doc_id': 'rag-rerank',
                'domain': 'general',
                'title': 'RAG 精排',
                'chapter': 'Rerank',
                'source': 'rag.md',
            },
        ),
    ]


class _AnswerModel:
    model_name = 'fake-answer'

    def __init__(self, citation_ids: list[str] | None = None, *, fail: bool = False) -> None:
        self.citation_ids = citation_ids or ['rag-recall']
        self.fail = fail

    def bind(self, **_: Any) -> '_AnswerModel':
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        if self.fail:
            raise RuntimeError('model offline')
        return AIMessage(content=json.dumps({
            'answer': '知识库 RAG 先多路召回，再融合和 rerank。',
            'citation_ids': self.citation_ids,
        }, ensure_ascii=False))


def test_load_knowledge_documents_skips_readme_and_tracks_sections(tmp_path: Path) -> None:
    (tmp_path / 'README.md').write_text('# 不应索引\n', encoding='utf-8')
    (tmp_path / 'guide.md').write_text(
        '# 指南\n\n## 召回\n\nBM25 和向量召回。\n\n## 精排\n\nBGE-Reranker 精排。\n',
        encoding='utf-8',
    )

    documents = load_knowledge_documents(tmp_path, domain='general')

    assert len(documents) >= 2
    assert all(document.metadata['domain'] == 'general' for document in documents)
    assert all(document.metadata['doc_id'] for document in documents)
    assert len({document.metadata['doc_id'] for document in documents}) == len(documents)
    assert any(document.metadata['chapter'] == '召回' for document in documents)
    assert all(document.metadata['source'] == 'guide.md' for document in documents)


def test_load_knowledge_documents_merges_preamble_and_skips_references(tmp_path: Path) -> None:
    (tmp_path / 'guide.md').write_text(
        '# 指南\n\n'
        '> 免责声明：仅用于测试。\n\n'
        '## 召回\n\n'
        'BM25 和向量召回。\n\n'
        '## 参考资料\n\n'
        '- [示例](https://example.com)\n\n'
        '风险提示：不构成建议。\n',
        encoding='utf-8',
    )

    documents = load_knowledge_documents(tmp_path, domain='general')

    assert len(documents) == 1
    document = documents[0]
    assert document.metadata['chapter'] == '召回'
    assert '免责声明' in document.page_content
    assert 'BM25 和向量召回' in document.page_content
    assert '参考资料' not in document.page_content


def test_multi_route_retriever_fuses_and_deduplicates() -> None:
    first, second = _docs()[:2]
    retriever = MultiRouteRetriever([
        RetrievalRoute('left', 0.5, lambda query, k: [first]),
        RetrievalRoute('right', 0.5, lambda query, k: [second, first]),
    ])

    result = retriever.retrieve('基金风险', 2)

    assert [document.metadata['doc_id'] for document in result.documents] == ['fund-risk', 'rag-recall']
    assert result.diagnostics['route_hits'] == {'left': 1, 'right': 2}
    assert result.diagnostics['fused_count'] == 2


class _TopNReranker:
    top_n = 2

    def __call__(self, query: str, documents: list[Document]) -> list[Document]:
        return list(reversed(documents))


def test_rerank_candidate_pool_aligns_with_top_n() -> None:
    documents = _docs()
    reranker = FallbackReranker(_TopNReranker())
    retriever = MultiRouteRetriever([
        RetrievalRoute('only', 1.0, lambda query, k: documents),
    ], reranker=reranker)

    result = retriever.retrieve('重新排序', 1)

    assert reranker.top_n == 2
    assert result.diagnostics['rerank_top_n'] == 2
    assert result.diagnostics['rerank_candidates'] == 2
    assert result.documents[0].metadata['doc_id'] == 'rag-recall'


def test_lexical_reranker_moves_query_relevant_document_first() -> None:
    documents = _docs()
    reranker = LexicalReranker()

    ordered = reranker('BGE-Reranker 精排', documents)

    assert ordered[0].metadata['doc_id'] == 'rag-rerank'


def test_knowledge_base_degrades_to_keyword_and_metadata() -> None:
    def broken_factory():
        raise RuntimeError('milvus_unreachable')

    knowledge = KnowledgeBase(
        _docs(),
        vector_factory=broken_factory,
        reranker=LexicalReranker(),
    )

    result = knowledge.retrieve('多路召回', 2)

    assert result['documents']
    assert result['degraded'] is True
    assert 'milvus_unreachable' in (result['vector_error'] or '')
    assert result['retrieval']['reranked'] is True


@pytest.mark.asyncio
async def test_knowledge_rag_answer_validates_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('tools.knowledge_rag.milvus_reachable', lambda uri: False)
    rag = KnowledgeRAG(
        {'general': KnowledgeSource('general', Path('.'), 'test_general', lambda root: _docs())},
        top_k=2,
        reranker=LexicalReranker(),
    )

    result = await rag.answer('general', '什么是多路召回', _AnswerModel(), 2)

    assert result['answer']
    assert result['requires_manual_review'] is False
    assert result['documents']

    with pytest.raises(KnowledgeAnswerError):
        await rag.answer('general', '什么是多路召回', _AnswerModel(['outside-id']), 2)
    with pytest.raises(KnowledgeAnswerError, match='回答模型调用失败'):
        await rag.answer('general', '什么是多路召回', _AnswerModel(fail=True), 2)


def test_rag_search_and_answer_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('tools.knowledge_rag.milvus_reachable', lambda uri: False)
    rag = KnowledgeRAG(
        {'general': KnowledgeSource('general', Path('.'), 'test_general', lambda root: _docs())},
        top_k=2,
        reranker=LexicalReranker(),
    )

    with TestClient(create_app(
        database=':memory:',
        investment_rag=False,
        knowledge_rag=rag,
        knowledge_model=_AnswerModel(),
    )) as client:
        search = client.post('/api/rag/search', json={
            'domain': 'general',
            'question': '多路召回和 rerank',
            'top_k': 2,
        })
        answer = client.post('/api/rag/answer', json={
            'domain': 'general',
            'question': '多路召回和 rerank',
            'top_k': 2,
        })
        domains = client.get('/api/rag/domains')

    assert search.status_code == 200
    assert search.json()['retrieval']['reranked'] is True
    assert search.json()['degraded'] is True
    assert answer.status_code == 200
    assert answer.json()['answer']
    assert answer.json()['documents']
    assert domains.status_code == 200
    assert domains.json()['domains'][0]['domain'] == 'general'


def test_search_audit_records_retrieval_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('tools.knowledge_rag.milvus_reachable', lambda uri: False)
    rag = KnowledgeRAG(
        {'general': KnowledgeSource('general', Path('.'), 'test_general', lambda root: _docs())},
        top_k=2,
        reranker=LexicalReranker(),
    )

    with TestClient(create_app(
        database=':memory:',
        investment_rag=False,
        knowledge_rag=rag,
        knowledge_model=_AnswerModel(),
    )) as client:
        response = client.post('/api/rag/search', json={
            'domain': 'general',
            'question': '多路召回和 rerank',
            'top_k': 2,
        })
        assert response.status_code == 200
        store = client.app.state.audit
        entry = next(item for item in store.recent(10) if item['resource'] == '/api/rag/search')

    retrieval = entry['details']['retrieval']
    assert retrieval
    record = retrieval[0]
    assert record['collection'] == 'test_general'
    assert record['route_hits']['dense'] == 0
    assert record['fused_count'] >= 1
    assert record['rerank_candidates'] >= 1
    assert record['reranked'] is True
    assert record['citations'][0]['citation_id'] == 'K1'
