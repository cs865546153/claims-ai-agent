"""判责链路 RAG 条款检索接入测试。"""
import asyncio
import json

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from agents.risk_agent import run_expert
from tools.rag_retrieval import HybridRetriever, build_clause_retriever


def _clauses() -> list[dict[str, str]]:
    return [
        {'doc_id': 'c1', 'text': '车辆损失险保险责任条款', 'chapter': '第一条', 'source': 'auto.txt'},
        {'doc_id': 'c2', 'text': '第三者责任险免责条款', 'chapter': '第二条', 'source': 'auto.txt'},
    ]


class _ExpertModel:
    """返回带 clause_ids 的专家 JSON，并记录 human 输入以断言条款被注入。"""

    def __init__(self, clause_ids: list[str]) -> None:
        self.clause_ids = clause_ids
        self.seen_payload: dict | None = None

    def bind(self, **kwargs: object) -> '_ExpertModel':
        return self

    async def ainvoke(self, messages: list, config: dict | None = None) -> AIMessage:
        self.seen_payload = json.loads(messages[-1].content)
        return AIMessage(content=json.dumps({
            'expert': 'liability', 'recommendation': 'accept', 'confidence': 0.9,
            'risk_score': None, 'rationale': '依据检索条款判断责任',
            'clause_ids': self.clause_ids, 'missing_information': [],
        }, ensure_ascii=False))


def test_run_expert_injects_clauses_and_validates_citation() -> None:
    clauses = _clauses()
    model = _ExpertModel(['c1'])
    result = asyncio.run(run_expert(
        model, 'liability', {'description': '车辆刮擦'}, {'policy_type': '机动车商业险'}, clauses=clauses,
    ))
    assert result['clause_ids'] == ['c1']
    assert model.seen_payload is not None
    assert any(doc['doc_id'] == 'c1' for doc in model.seen_payload['clauses'])


def test_run_expert_rejects_fabricated_citation() -> None:
    clauses = _clauses()
    model = _ExpertModel(['invented'])
    with pytest.raises(ValueError, match='未检索到'):
        asyncio.run(run_expert(
            model, 'liability', {'description': 'x'}, {'policy_type': 'y'}, clauses=clauses,
        ))


def test_run_expert_without_clauses_does_not_require_citation() -> None:
    model = _ExpertModel([])
    result = asyncio.run(run_expert(
        model, 'liability', {'description': 'x'}, {'policy_type': 'y'},
    ))
    assert result['clause_ids'] == []
    assert model.seen_payload is not None and 'clauses' not in model.seen_payload


def test_build_clause_retriever_returns_clauses() -> None:
    corpus = [Document(page_content='车辆损失保险责任', metadata={
        'doc_id': 'a', 'insurance_type': 'auto', 'version': '1', 'chapter': '第一条', 'source': 'p.txt',
    })]
    retrieve = build_clause_retriever(HybridRetriever(lambda q, k: corpus, corpus), insurance_type='auto')
    clauses = asyncio.run(retrieve(
        {'description': '车辆刮擦', 'accident_type': '追尾'}, {'policy_type': '机动车商业险'},
    ))
    assert clauses and clauses[0]['doc_id'] == 'a'
    assert clauses[0]['chapter'] == '第一条'


def test_build_clause_retriever_degrades_on_error() -> None:
    def broken(query: str, k: int) -> list[Document]:
        raise RuntimeError('milvus down')

    retrieve = build_clause_retriever(HybridRetriever(broken, []))
    assert asyncio.run(retrieve({'description': 'x'}, {'policy_type': 'y'})) == []


def test_build_clause_retriever_degrades_on_empty_query() -> None:
    retrieve = build_clause_retriever(HybridRetriever(lambda q, k: [], []))
    assert asyncio.run(retrieve({}, {})) == []
