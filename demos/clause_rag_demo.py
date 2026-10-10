r"""判责条款检索（RAG）离线演示：内存条款 + 假专家，验证检索注入与引用校验。

运行：.\.venv-py314\Scripts\python.exe -m demos.clause_rag_demo
不连接真实 LLM 或 Milvus，仅演示「检索 -> 注入 -> 判责 -> 引用校验」的机制。
"""
import asyncio
import json

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from agents.risk_agent import run_expert
from tools.rag_retrieval import HybridRetriever, build_clause_retriever


class DemoExpert:
    """假专家：从注入的条款里挑第一条 doc_id 作为引用，演示引用校验。"""

    def bind(self, **kwargs: object) -> 'DemoExpert':
        return self

    async def ainvoke(self, messages: list, config: dict | None = None) -> AIMessage:
        payload = json.loads(messages[-1].content)
        clause_ids = [payload['clauses'][0]['doc_id']] if payload.get('clauses') else []
        return AIMessage(content=json.dumps({
            'expert': 'liability', 'recommendation': 'review', 'confidence': 0.7,
            'risk_score': None, 'rationale': '演示：引用检索到的条款',
            'clause_ids': clause_ids, 'missing_information': [],
        }, ensure_ascii=False))


def main() -> None:
    corpus = [
        Document(page_content='第一条 车辆损失险：碰撞、倾覆造成的车辆损失属保险责任。',
                 metadata={'doc_id': 'clause-001', 'insurance_type': 'auto', 'version': '2026',
                           'chapter': '第一条', 'source': 'demo_auto.txt'}),
        Document(page_content='第二条 第三者责任险：依法应由被保险人承担的损害赔偿责任。',
                 metadata={'doc_id': 'clause-002', 'insurance_type': 'auto', 'version': '2026',
                           'chapter': '第二条', 'source': 'demo_auto.txt'}),
        Document(page_content='第三条 免责：无证驾驶、醉酒驾驶造成的损失不属保险责任。',
                 metadata={'doc_id': 'clause-003', 'insurance_type': 'auto', 'version': '2026',
                           'chapter': '第三条', 'source': 'demo_auto.txt'}),
    ]
    retriever = HybridRetriever(lambda q, k: corpus, corpus)
    clause_retriever = build_clause_retriever(retriever, insurance_type='auto', top_k=3)

    claim = {'description': '车辆追尾造成前保险杠损坏', 'accident_type': '追尾'}
    policy = {'policy_type': '机动车商业险'}

    clauses = asyncio.run(clause_retriever(claim, policy))
    print('检索到的条款：')
    for clause in clauses:
        print(f"  [{clause['doc_id']}] {clause['chapter']} {clause['text'][:32]}")

    result = asyncio.run(run_expert(DemoExpert(), 'liability', claim, policy, clauses=clauses))
    print('专家引用 clause_ids =', result['clause_ids'])


if __name__ == '__main__':
    main()
