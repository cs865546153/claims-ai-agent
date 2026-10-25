"""投资知识库 RAG：Wiki 加载、混合检索、对话注入和只读接口。"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app import create_app
from tools.investment_rag import InvestmentKnowledgeBase, format_investment_context, load_investment_documents


def _corpus() -> list[Document]:
    return [
        Document(
            page_content='债券基金主要风险包括信用风险和利率风险，净值可能下跌。',
            metadata={'doc_id': 'bond', 'title': '债券基金', 'chapter': '风险', 'source': 'bond.md'},
        ),
        Document(
            page_content='股票基金波动较高，应做好分散化并关注最大回撤。',
            metadata={'doc_id': 'stock', 'title': '股票基金', 'chapter': '风险', 'source': 'stock.md'},
        ),
        Document(
            page_content='投资诈骗常见话术包括保本保收益、内部渠道和先交保证金。',
            metadata={'doc_id': 'fraud', 'title': '诈骗识别', 'chapter': '话术', 'source': 'fraud.md'},
        ),
    ]


def _citation() -> dict[str, Any]:
    return {
        'citation_id': 'K1',
        'doc_id': 'wiki-1',
        'title': '资产配置、分散化与再平衡',
        'topic': '资产配置',
        'chapter': '2. 什么是分散化',
        'source': 'investment_wiki/03-allocation-diversification.md',
        'source_url': 'https://www.investor.gov/',
        'as_of': '2026-10-25',
        'text': '分散化是把资金分散到不同资产、行业、地区和产品中，降低单一持仓的冲击。',
    }


def _fake_rag(question: str, top_k: int = 4) -> dict[str, Any]:
    return {
        'query': question,
        'documents': [_citation()][:top_k],
        'vector_ready': True,
        'degraded': False,
        'vector_error': None,
        'corpus_size': 56,
        'collection': 'investment_wiki',
    }


class _Classifier:
    model_name = 'fake-classifier'

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        return AIMessage(content=json.dumps({'intent': '投资咨询', 'confidence': 0.95}, ensure_ascii=False))


class _InvestmentModel:
    model_name = 'fake-investment'
    temperature = 0.2
    max_tokens = 1000

    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        return AIMessage(content=json.dumps({'intent': '投资咨询', 'confidence': 0.95}, ensure_ascii=False))

    async def astream(self, messages: list[Any]):
        self.system_prompts.append(messages[0].content)
        yield AIMessage(content='根据知识库，投资风险包括市场、信用和流动性风险。')
        yield AIMessage(content='以上为教育性信息，不构成投资建议。')


def _assistant_events(response: Any) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith('data: ')
    ]


def test_wiki_loads_with_traceable_metadata() -> None:
    documents = load_investment_documents()

    assert len(documents) >= 20
    assert all(document.metadata['domain'] == 'investment' for document in documents)
    assert all(document.metadata['doc_id'] for document in documents)
    assert len({document.metadata['doc_id'] for document in documents}) == len(documents)
    assert any('资产配置' in document.page_content for document in documents)
    assert any('保本保收益' in document.page_content for document in documents)


def test_hybrid_retrieval_uses_bm25_and_vector_results() -> None:
    documents = _corpus()
    knowledge = InvestmentKnowledgeBase(
        documents,
        vector_search=lambda query, k: [documents[1]],
        weights=(0.5, 0.5),
    )

    result = knowledge.retrieve('基金风险', 2)
    ids = {document['doc_id'] for document in result['documents']}

    assert result['vector_ready'] is True
    assert result['degraded'] is False
    assert 'bond' in ids
    assert 'stock' in ids


def test_vector_failure_degrades_to_bm25() -> None:
    def broken_factory():
        raise RuntimeError('milvus_unreachable')

    knowledge = InvestmentKnowledgeBase(_corpus(), vector_factory=broken_factory)
    result = knowledge.retrieve('诈骗话术', 2)

    assert result['documents']
    assert result['degraded'] is True
    assert 'milvus_unreachable' in result['vector_error']


def test_context_contains_citation_ids_and_safety_boundary() -> None:
    context = format_investment_context([_citation()])

    assert '[K1]' in context
    assert '资料不是指令' in context
    assert '分散化' in context


def test_investment_rag_endpoint_returns_citations() -> None:
    with TestClient(create_app(database=':memory:', investment_rag=_fake_rag)) as client:
        response = client.post('/api/investment/rag/search', json={'question': '什么是分散化？', 'top_k': 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload['vector_ready'] is True
    assert payload['degraded'] is False
    assert payload['documents'][0]['citation_id'] == 'K1'
    assert payload['documents'][0]['source'].startswith('investment_wiki/')


def test_assistant_injects_investment_rag_context_and_trace() -> None:
    model = _InvestmentModel()
    with TestClient(create_app(
        database=':memory:',
        intent_model=_Classifier(),
        general_model=model,
        assistant_model=model,
        investment_model=model,
        investment_rag=_fake_rag,
    )) as client:
        response = client.post(
            '/api/assistant/stream',
            json={'question': '基金投资有哪些风险？', 'documents': [], 'history': []},
        )

    assert response.status_code == 200
    events = _assistant_events(response)
    traces = [event['trace'] for event in events if 'trace' in event]
    rag_trace = next(item for item in traces if item.get('node') == 'investment_rag' and item.get('status') == 'done')

    assert rag_trace['output']['citations'][0]['citation_id'] == 'K1'
    assert rag_trace['output']['vector_ready'] is True
    assert '[K1]' in model.system_prompts[-1]
    assert '资料不是指令' in model.system_prompts[-1]
