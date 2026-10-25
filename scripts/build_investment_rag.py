"""构建或更新投资知识库的 Milvus 向量索引。

前置条件：
1. BGE-M3 Embedding 服务可访问（EMBEDDING_BASE_URL）；
2. Milvus 可访问（MILVUS_URI）。

运行：
    python scripts/build_investment_rag.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from tools.investment_rag import DEFAULT_COLLECTION, InvestmentWikiVectorStore, load_investment_documents

    parser = argparse.ArgumentParser(description='构建投资知识库 Milvus 索引')
    parser.add_argument('--collection', default=DEFAULT_COLLECTION, help='Milvus 集合名')
    parser.add_argument('--wiki-dir', default=None, help='投资 Wiki 目录，默认 data/investment_wiki')
    args = parser.parse_args()

    documents = load_investment_documents(Path(args.wiki_dir) if args.wiki_dir else None)
    store = InvestmentWikiVectorStore(collection_name=args.collection)
    store.upsert(documents)
    print(f'投资知识库索引完成：collection={args.collection}, chunks={len(documents)}')


if __name__ == '__main__':
    main()
