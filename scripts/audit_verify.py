"""校验审计库哈希链并打印最近记录。

用法：
    python -m scripts.audit_verify                       # 默认 .data/audit.sqlite
    python -m scripts.audit_verify --db /path/audit.sqlite --limit 20
退出码 0 表示链完整，1 表示检测到篡改或缺失。
"""
from __future__ import annotations

import argparse
import json
import sys

from agents.audit_store import AuditStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='.data/audit.sqlite', help='审计库路径')
    parser.add_argument('--limit', type=int, default=10, help='打印最近 N 条')
    args = parser.parse_args()

    store = AuditStore(args.db)
    try:
        ok, broken = store.verify_chain()
        if ok:
            print('哈希链：完整')
        else:
            print(f'哈希链：已损坏，首个异常 request_id={broken}')
        for entry in store.recent(args.limit):
            print(json.dumps({
                'time': entry['created_at'],
                'request_id': entry['request_id'],
                'actor': entry['actor'],
                'action': entry['action'],
                'resource': entry['resource'],
                'status': entry['status'],
                'latency_ms': entry['latency_ms'],
                'body': entry['details'].get('body'),
            }, ensure_ascii=False))
        sys.exit(0 if ok else 1)
    finally:
        store.close()


if __name__ == '__main__':
    main()
