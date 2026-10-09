"""本地 SQLite 保单数据源：建表、模拟数据与查询。

真实业务保单仍通过 adapters.legacy_adapter.CoreSystemAdapter（HTTP）获取；
本模块仅提供本地模拟保单，供演示与离线测试使用。查询结果应明确标记为
模拟数据，不得当作真实保单事实。
"""
import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_POLICY_DB = '.data/policies.sqlite'

# 金额以字符串精确到分存储，避免浮点精度；clauses 为 JSON 数组字符串。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    policy_id   TEXT PRIMARY KEY,
    policy_type TEXT NOT NULL,
    status      TEXT NOT NULL,
    coverage    TEXT NOT NULL,
    deductible  TEXT NOT NULL,
    holder      TEXT NOT NULL,
    valid_from  TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    clauses     TEXT NOT NULL DEFAULT '[]',
    source      TEXT NOT NULL
)
"""

_COLUMNS = (
    'policy_id', 'policy_type', 'status', 'coverage', 'deductible',
    'holder', 'valid_from', 'valid_until', 'clauses', 'source',
)

# 模拟保单：仅用于演示/测试，非真实业务事实；投保人已脱敏。
DEMO_POLICIES: list[dict[str, str]] = [
    {'policy_id': 'POL-2024-001', 'policy_type': '机动车商业险', 'status': '有效',
     'coverage': '500000.00', 'deductible': '500.00', 'holder': '张**',
     'valid_from': '2024-01-01', 'valid_until': '2025-01-01',
     'clauses': json.dumps(['车辆损失险', '第三者责任险'], ensure_ascii=False),
     'source': '本地模拟数据'},
    {'policy_id': 'POL-2024-002', 'policy_type': '机动车交强险', 'status': '有效',
     'coverage': '200000.00', 'deductible': '0.00', 'holder': '李**',
     'valid_from': '2024-03-15', 'valid_until': '2025-03-14',
     'clauses': json.dumps(['交强险基础责任'], ensure_ascii=False),
     'source': '本地模拟数据'},
    {'policy_id': 'POL-2023-088', 'policy_type': '健康医疗保险', 'status': '已脱保',
     'coverage': '100000.00', 'deductible': '1000.00', 'holder': '王**',
     'valid_from': '2023-06-01', 'valid_until': '2024-05-31',
     'clauses': json.dumps(['住院医疗', '门诊医疗'], ensure_ascii=False),
     'source': '本地模拟数据'},
    {'policy_id': 'POL-2025-030', 'policy_type': '意外伤害保险', 'status': '无效',
     'coverage': '50000.00', 'deductible': '100.00', 'holder': '赵**',
     'valid_from': '2025-01-01', 'valid_until': '2025-12-31',
     'clauses': json.dumps(['意外身故', '意外医疗'], ensure_ascii=False),
     'source': '本地模拟数据'},
    {'policy_id': 'POL-2025-101', 'policy_type': '家庭财产保险', 'status': '有效',
     'coverage': '300000.00', 'deductible': '500.00', 'holder': '陈**',
     'valid_from': '2025-07-01', 'valid_until': '2026-06-30',
     'clauses': json.dumps(['房屋主体', '室内财产', '水管爆裂'], ensure_ascii=False),
     'source': '本地模拟数据'},
]


class PolicyStore:
    """封装保单表的建表、种子与查询；INSERT OR IGNORE 保证可重复初始化。"""

    def __init__(self, path: str | Path = DEFAULT_POLICY_DB) -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def create_schema(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(_SCHEMA)

    def seed(self, policies: list[dict[str, str]] | None = None) -> int:
        rows = policies if policies is not None else DEMO_POLICIES
        self.create_schema()
        with self.connect() as db:
            db.executemany(
                'INSERT OR IGNORE INTO policies('
                'policy_id,policy_type,status,coverage,deductible,holder,'
                'valid_from,valid_until,clauses,source'
                ') VALUES('
                ':policy_id,:policy_type,:status,:coverage,:deductible,:holder,'
                ':valid_from,:valid_until,:clauses,:source)',
                rows,
            )
        return len(rows)

    def query(self, policy_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                f'SELECT {", ".join(_COLUMNS)} FROM policies WHERE policy_id=?',
                (policy_id,),
            ).fetchone()
        if row is None:
            return None
        data = dict(zip(_COLUMNS, row))
        data['clauses'] = json.loads(data['clauses'] or '[]')
        return data

    def list_all(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                f'SELECT {", ".join(_COLUMNS)} FROM policies ORDER BY policy_id',
            ).fetchall()
        result = []
        for row in rows:
            data = dict(zip(_COLUMNS, row))
            data['clauses'] = json.loads(data['clauses'] or '[]')
            result.append(data)
        return result


def ensure_policy_store(path: str | Path = DEFAULT_POLICY_DB) -> PolicyStore:
    """建表并写入模拟数据，幂等，返回可用的数据源。"""
    store = PolicyStore(path)
    store.seed()
    return store


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=DEFAULT_POLICY_DB, help='SQLite 文件路径')
    parser.add_argument('--query', help='按保单号查询单条')
    parser.add_argument('--list', action='store_true', help='列出全部保单')
    args = parser.parse_args()

    store = ensure_policy_store(args.db)
    if args.query:
        row = store.query(args.query)
        print(json.dumps(row, ensure_ascii=False, indent=2) if row else '未找到该保单')
    elif args.list:
        for row in store.list_all():
            print(json.dumps(row, ensure_ascii=False))
    else:
        print(f'已初始化并写入 {len(DEMO_POLICIES)} 条模拟保单到 {args.db}')
