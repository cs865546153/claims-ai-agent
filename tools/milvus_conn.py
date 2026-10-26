"""Milvus 连接参数集中构造。

pymilvus 默认开启 ``grpc.keepalive_time_ms=10000`` 且允许无调用时发心跳。
Milvus/Milvus Lite 的 gRPC 服务端默认只允许每 5 分钟（无数据传输时）心跳一次，
因此空闲连接会在约 20 秒后被服务端以 ``GOAWAY ... too_many_pings
(ENHANCE_YOUR_CALM)`` 断开，下次检索需要重建通道，表现为突发延迟或检索失败。

这里显式覆盖为“仅在存在调用时按 5 分钟心跳”，避免服务端限流。
"""
from __future__ import annotations

from typing import Any

# 服务端（grpc 默认）无数据时最小接收心跳间隔为 300000ms，客户端不得更频繁。
GRPC_KEEPALIVE_TIME_MS = 300_000
GRPC_KEEPALIVE_TIMEOUT_MS = 20_000


def milvus_connection_args(uri: str) -> dict[str, Any]:
    """返回 langchain-milvus 的 ``connection_args``，覆盖 pymilvus 默认心跳。

    pymilvus 会用本字典覆盖内置默认项（``grpc_options`` 优先），
    其余键原样透传给 ``connections.connect``。
    """
    return {
        'uri': uri,
        'grpc_options': {
            'grpc.keepalive_time_ms': GRPC_KEEPALIVE_TIME_MS,
            'grpc.keepalive_timeout_ms': GRPC_KEEPALIVE_TIMEOUT_MS,
            # 空闲连接不发送心跳，从根上避免 too_many_pings。
            'grpc.keepalive_permit_without_calls': 0,
            'grpc.enable_retries': 1,
        },
    }


__all__ = ['GRPC_KEEPALIVE_TIME_MS', 'GRPC_KEEPALIVE_TIMEOUT_MS', 'milvus_connection_args']
