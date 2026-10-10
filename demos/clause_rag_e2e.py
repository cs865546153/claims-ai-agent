r"""判责条款检索端到端演示：内存条款 + 真实 LLM（无需 Milvus/Docker）。

运行：.\.venv-py314\Scripts\python.exe -m demos.clause_rag_e2e
用 BM25 混合检索内存条款，调用真实模型（liability 用 pro 档）判责并输出 clause_ids。
"""
import asyncio
import json

from langchain_core.documents import Document

from agents.risk_agent import run_expert
from config import ClaimLLMFactory
from tools.rag_retrieval import HybridRetriever, build_clause_retriever


def _corpus() -> list[Document]:
    return [
        Document(page_content='第一条 保险责任：被保险人或其允许的驾驶人在使用被保险机动车过程中，因碰撞、倾覆、坠落造成的被保险机动车损失，保险人负责赔偿。',
                 metadata={'doc_id': 'clause-001', 'insurance_type': 'auto', 'version': '2026',
                           'chapter': '第一条 保险责任', 'source': '机动车商业险条款.txt'}),
        Document(page_content='第二条 第三者责任：被保险机动车发生意外事故造成第三者人身伤亡或财产直接损毁，依法应由被保险人承担的损害赔偿责任，保险人负责赔偿。',
                 metadata={'doc_id': 'clause-002', 'insurance_type': 'auto', 'version': '2026',
                           'chapter': '第二条 第三者责任', 'source': '机动车商业险条款.txt'}),
        Document(page_content='第三条 免责：无驾驶证、驾驶证被吊销或暂扣期间驾驶机动车，或饮酒、服用国家管制的精神药品、麻醉药品后驾驶，造成的损失保险人不负责赔偿。',
                 metadata={'doc_id': 'clause-003', 'insurance_type': 'auto', 'version': '2026',
                           'chapter': '第三条 免责条款', 'source': '机动车商业险条款.txt'}),
        Document(page_content='第四条 免赔额：每次事故绝对免赔额由投保人与保险人在订立合同时协商确定，并在保险单中载明。',
                 metadata={'doc_id': 'clause-004', 'insurance_type': 'auto', 'version': '2026',
                           'chapter': '第四条 免赔额', 'source': '机动车商业险条款.txt'}),
    ]


def main() -> None:
    corpus = _corpus()
    retriever = HybridRetriever(lambda q, k: corpus, corpus)
    clause_retriever = build_clause_retriever(retriever, insurance_type='auto', top_k=3)

    claim = {'description': '车辆在高速追尾前方车辆，造成前保险杠和引擎盖损坏，已报警并取得事故认定书。',
             'accident_type': '追尾'}
    policy = {'policy_type': '机动车商业险', 'coverage': '500000.00', 'deductible': '500.00'}

    clauses = asyncio.run(clause_retriever(claim, policy))
    print('检索到的条款：')
    for clause in clauses:
        print(f"  [{clause['doc_id']}] {clause['chapter']}")

    model = ClaimLLMFactory.create('pro', max_retries=0)
    result = asyncio.run(run_expert(model, 'liability', claim, policy, clauses=clauses))
    print('\n责任专家意见：')
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
