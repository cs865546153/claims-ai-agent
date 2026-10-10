"""演示用内存条款：无需 Milvus，供判责 RAG 离线演练。

条款为模拟内容，仅用于演示检索与判责流程，非真实保险条款。
"""
from langchain_core.documents import Document

from tools.rag_retrieval import HybridRetriever, build_clause_retriever

_CLAUSES: list[dict[str, str]] = [
    {'doc_id': 'clause-001', 'chapter': '第一条 保险责任',
     'text': '被保险人或其允许的驾驶人在使用被保险机动车过程中，因碰撞、倾覆、坠落造成的被保险机动车损失，保险人负责赔偿。'},
    {'doc_id': 'clause-002', 'chapter': '第二条 第三者责任',
     'text': '被保险机动车发生意外事故造成第三者人身伤亡或财产直接损毁，依法应由被保险人承担的损害赔偿责任，保险人负责赔偿。'},
    {'doc_id': 'clause-003', 'chapter': '第三条 免责条款',
     'text': '无驾驶证、驾驶证被吊销或暂扣期间驾驶，或饮酒、服用国家管制的精神药品、麻醉药品后驾驶，或故意制造事故，造成的损失保险人不负责赔偿。'},
    {'doc_id': 'clause-004', 'chapter': '第四条 免赔额',
     'text': '每次事故绝对免赔额由投保人与保险人在订立合同时协商确定，并在保险单中载明，赔款计算时先扣除免赔额。'},
]


def build_demo_clause_retriever(*, insurance_type: str = 'auto', top_k: int = 3) -> object:
    """构造内存条款检索器，返回 async (claim, policy) -> list[dict]。"""
    corpus = [
        Document(page_content=clause['text'], metadata={
            'doc_id': clause['doc_id'], 'insurance_type': insurance_type, 'version': '2026',
            'chapter': clause['chapter'], 'source': 'demo_auto_clauses.txt',
        })
        for clause in _CLAUSES
    ]
    retriever = HybridRetriever(lambda q, k: corpus, corpus)
    return build_clause_retriever(retriever, insurance_type=insurance_type, top_k=top_k)
