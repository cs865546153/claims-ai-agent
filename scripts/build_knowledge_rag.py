"""构建通用知识库的 Milvus 索引。

示例：
    python scripts/build_knowledge_rag.py --domain general
    python scripts/build_knowledge_rag.py --domain investment
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


def build(domain: str, root: Path | None, collection: str | None) -> int:
    from settings import Settings
    from tools.knowledge_rag import DEFAULT_KNOWLEDGE_DIR, load_knowledge_documents
    from tools.vector_store import KnowledgeVectorStore

    cfg = Settings()
    if domain == 'investment':
        from tools.investment_rag import WIKI_DIR, load_investment_documents
        root = root or WIKI_DIR
        collection = collection or cfg.investment_rag_collection
        documents = load_investment_documents(root)
    elif domain == 'general':
        root = root or DEFAULT_KNOWLEDGE_DIR
        collection = collection or cfg.knowledge_rag_collection
        documents = load_knowledge_documents(root, domain=domain)
    else:
        raise ValueError('domain 只支持 general 或 investment')

    store = KnowledgeVectorStore(collection_name=collection)
    store.upsert(documents)
    print(f'已写入 {len(documents)} 个 chunk 到 {collection}（{root}）')
    return len(documents)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    parser = argparse.ArgumentParser(description='构建知识库 Milvus 索引')
    parser.add_argument('--domain', choices=['general', 'investment'], default='general')
    parser.add_argument('--root', type=Path, default=None)
    parser.add_argument('--collection', default=None)
    args = parser.parse_args()
    build(args.domain, args.root, args.collection)


if __name__ == '__main__':
    main()
