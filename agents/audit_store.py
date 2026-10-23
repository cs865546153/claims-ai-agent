"""企业级审计存储：append-only + 哈希链，用于事后追溯与篡改检测。

设计要点：
- 只追加不更新/删除，SQLite 开启 WAL；
- 每条记录包含 prev_hash，组成哈希链，可用 verify_chain() 校验；
- 与现有 stdout 审计（AuditLogMiddleware）并存：前者给人看，这里给监管与排障用；
- 生产环境应替换为 Postgres/ClickHouse + WORM 存储，本类只定义接口与最小实现。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS_HASH = '0' * 64


def _canonical(payload: dict[str, Any]) -> str:
    """稳定序列化：排序键、禁用 NaN，避免同一内容产生不同哈希。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


class AuditStore:
    """最小可用的不可变审计库；写入失败不应拖垮业务请求。"""

    def __init__(self, path: str = '.data/audit.sqlite') -> None:
        self.path = path
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                request_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                status INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                details TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL
            )
            '''
        )
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events(request_id)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at)')
        self._conn.commit()

    def record(self, *, request_id: str, actor: str, action: str, resource: str,
               status: int, latency_ms: float, details: dict[str, Any]) -> str:
        """追加一条审计记录，返回 entry_hash。"""
        entry = {
            'created_at': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'request_id': request_id,
            'actor': actor,
            'action': action,
            'resource': resource,
            'status': int(status),
            'latency_ms': round(float(latency_ms), 3),
            'details': details,
        }
        with self._lock:
            row = self._conn.execute('SELECT entry_hash FROM audit_events ORDER BY id DESC LIMIT 1').fetchone()
            prev_hash = row[0] if row else GENESIS_HASH
            entry_hash = hashlib.sha256((prev_hash + _canonical(entry)).encode('utf-8')).hexdigest()
            self._conn.execute(
                'INSERT INTO audit_events (created_at, request_id, actor, action, resource, status, '
                'latency_ms, details, prev_hash, entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (entry['created_at'], entry['request_id'], entry['actor'], entry['action'],
                 entry['resource'], entry['status'], entry['latency_ms'],
                 _canonical(entry['details']), prev_hash, entry_hash),
            )
            self._conn.commit()
            return entry_hash

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """按时间倒序读取，供排障与审查使用（不提供修改接口）。"""
        with self._lock:
            rows = self._conn.execute(
                'SELECT created_at, request_id, actor, action, resource, status, latency_ms, details, entry_hash '
                'FROM audit_events ORDER BY id DESC LIMIT ?', (max(1, min(limit, 500)),)
            ).fetchall()
        return [
            {'created_at': r[0], 'request_id': r[1], 'actor': r[2], 'action': r[3],
             'resource': r[4], 'status': r[5], 'latency_ms': r[6],
             'details': json.loads(r[7]), 'entry_hash': r[8]}
            for r in rows
        ]

    def verify_chain(self) -> tuple[bool, str | None]:
        """重算整条链；返回 (是否完整, 首个异常 request_id)。"""
        with self._lock:
            rows = self._conn.execute(
                'SELECT created_at, request_id, actor, action, resource, status, latency_ms, details, '
                'prev_hash, entry_hash FROM audit_events ORDER BY id ASC'
            ).fetchall()
        expected_prev = GENESIS_HASH
        for r in rows:
            entry = {'created_at': r[0], 'request_id': r[1], 'actor': r[2], 'action': r[3],
                     'resource': r[4], 'status': r[5], 'latency_ms': r[6], 'details': json.loads(r[7])}
            if r[8] != expected_prev:
                return False, r[1]
            digest = hashlib.sha256((r[8] + _canonical(entry)).encode('utf-8')).hexdigest()
            if digest != r[9]:
                return False, r[1]
            expected_prev = r[9]
        return True, None

    def ping(self) -> bool:
        """就绪探针：能读到表即视为可用。"""
        try:
            with self._lock:
                self._conn.execute('SELECT 1 FROM audit_events LIMIT 1').fetchone()
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._conn.close()
