"""通用 Milvus 向量存储封装。

知识库、投资 Wiki 与理赔条款共享同一套连接参数，但各自使用独立集合。
本地默认使用 Milvus Lite 的 ``.db`` 文件，远程/容器环境使用 HTTP 地址。
"""
from __future__ import annotations

import re
import socket
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from langchain_core.documents import Document

from settings import Settings
from tools.milvus_conn import milvus_connection_args
from tools.rag_retrieval import create_embeddings

COLLECTION_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,254}$')


def milvus_reachable(uri: str, timeout: float = 0.4) -> bool:
    """快速判断 Milvus 是否可达；本地 Milvus Lite 的 .db 路径不需要建连。"""
    if '://' not in uri and (uri.endswith('.db') or '/' in uri or '\\' in uri):
        return True
    target = uri if '://' in uri else f'http://{uri}'
    parsed = urlsplit(target)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == 'https' else 19530)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_filter_expr(filters: dict[str, Any] | None) -> str | None:
    """把等值过滤条件转换成 Milvus 表达式，只允许字符串/数字/布尔值。"""
    if not filters:
        return None
    clauses: list[str] = []
    for key, value in filters.items():
        if not COLLECTION_PATTERN.match(key):
            raise ValueError(f'非法过滤字段：{key}')
        if isinstance(value, bool):
            literal = 'true' if value else 'false'
        elif isinstance(value, (int, float)):
            literal = str(value)
        elif isinstance(value, str):
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            literal = f'"{escaped}"'
        else:
            raise ValueError(f'过滤字段 {key} 只支持字符串、数字或布尔值')
        clauses.append(f'{key} == {literal}')
    return ' and '.join(clauses)


class KnowledgeVectorStore:
    """通用知识库集合：动态 metadata、显式 ID、BGE-M3 向量。"""

    def __init__(
        self,
        *,
        collection_name: str,
        embeddings: Any = None,
        uri: str | None = None,
    ) -> None:
        if not COLLECTION_PATTERN.match(collection_name):
            raise ValueError(f'非法 Milvus 集合名：{collection_name}')
        from langchain_milvus import Milvus

        cfg = Settings()
        self.collection_name = collection_name
        self.store = Milvus(
            embedding_function=embeddings or create_embeddings(),
            collection_name=collection_name,
            connection_args=milvus_connection_args(uri or cfg.milvus_uri),
            index_params={'index_type': 'IVF_FLAT', 'metric_type': 'L2', 'params': {'nlist': 1024}},
            search_params={'metric_type': 'L2', 'params': {'nprobe': 16}},
            enable_dynamic_field=True,
            auto_id=False,
            drop_old=False,
        )

    def upsert(self, documents: Sequence[Document]) -> Any:
        """幂等写入；规避 langchain-milvus 0.1.7 的 upsert ID 透传缺陷。"""
        if not documents:
            return []
        ids = [str(document.metadata['doc_id']) for document in documents]
        if self.store.col is not None:
            self.store.delete(ids=ids)
        return self.add(documents)

    def add(self, documents: Sequence[Document]) -> Any:
        if not documents:
            return []
        ids = [str(document.metadata['doc_id']) for document in documents]
        return self.store.add_documents(documents=list(documents), ids=ids)

    def search(self, query: str, k: int = 5, *, filters: dict[str, Any] | None = None) -> list[Document]:
        if not query.strip() or not 1 <= k <= 100:
            raise ValueError('知识库查询或 top_k 不合法')
        return self.store.similarity_search(
            query,
            k=k,
            expr=build_filter_expr(filters),
        )

    def delete(self, ids: Sequence[str]) -> Any:
        if not ids:
            return []
        return self.store.delete(ids=[str(value) for value in ids])


__all__ = ['KnowledgeVectorStore', 'build_filter_expr', 'milvus_reachable']
