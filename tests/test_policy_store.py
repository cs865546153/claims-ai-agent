"""本地 SQLite 保单数据源测试。"""
from tools.policy_store import DEMO_POLICIES, PolicyStore, ensure_policy_store


def test_seed_and_query(tmp_path) -> None:
    store = PolicyStore(str(tmp_path / 'policies.sqlite'))
    store.seed()
    row = store.query('POL-2025-101')
    assert row is not None
    assert row['policy_type'] == '家庭财产保险'
    assert row['status'] == '有效'
    assert row['coverage'] == '300000.00'
    assert row['clauses'] == ['房屋主体', '室内财产', '水管爆裂']


def test_query_missing_returns_none(tmp_path) -> None:
    store = PolicyStore(str(tmp_path / 'policies.sqlite'))
    store.seed()
    assert store.query('UNKNOWN') is None


def test_seed_is_idempotent(tmp_path) -> None:
    store = PolicyStore(str(tmp_path / 'policies.sqlite'))
    store.seed()
    store.seed()
    assert len(store.list_all()) == len(DEMO_POLICIES)


def test_ensure_policy_store(tmp_path) -> None:
    store = ensure_policy_store(str(tmp_path / 'policies.sqlite'))
    assert store.query('POL-2024-001')['status'] == '有效'
