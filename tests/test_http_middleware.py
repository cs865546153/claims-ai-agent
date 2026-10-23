"""接入层中间件：请求 ID、认证、限流、审计与就绪探针。"""
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agents.audit_store import AuditStore
from app import create_app


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[callable]:
    """按用例构造独立应用，避免模块级 app 的审计库互相干扰。"""
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.delenv('CLAIMS_API_KEY', raising=False)
    monkeypatch.delenv('REVIEWER_API_KEY', raising=False)
    clients: list[TestClient] = []

    def factory(**kwargs) -> TestClient:
        client = TestClient(create_app(database=':memory:', **kwargs))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


def test_request_id_is_echoed(make_client) -> None:
    client = make_client()
    response = client.get('/health', headers={'X-Request-ID': 'req-abcdef12'})
    assert response.status_code == 200
    assert response.headers['X-Request-ID'] == 'req-abcdef12'


def test_request_id_generated_when_absent(make_client) -> None:
    client = make_client()
    response = client.get('/health')
    assert len(response.headers['X-Request-ID']) == 32


def test_invalid_request_id_is_replaced(make_client) -> None:
    client = make_client()
    response = client.get('/health', headers={'X-Request-ID': 'bad id with spaces'})
    assert response.headers['X-Request-ID'] != 'bad id with spaces'
    assert len(response.headers['X-Request-ID']) == 32


def test_api_key_required_when_configured(make_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CLAIMS_API_KEY', 'k' * 24)
    client = make_client()
    assert client.post('/api/claims/process', json={'claim_id': 'C-1', 'description': 'x'}).status_code == 401
    ok = client.post('/api/claims/process', json={'claim_id': 'C-2', 'description': 'x'},
                     headers={'X-API-Key': 'k' * 24})
    assert ok.status_code == 200


def test_health_and_docs_stay_public(make_client) -> None:
    client = make_client()
    assert client.get('/health').status_code == 200
    assert client.get('/openapi.json').status_code == 200


def test_rate_limit_returns_429(make_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HTTP_RATE_LIMIT_PER_MINUTE', '2')
    monkeypatch.setenv('HTTP_STREAM_RATE_LIMIT_PER_MINUTE', '2')
    client = make_client()
    payload = {'claim_id': 'RL-1', 'description': 'x'}
    codes = [client.post('/api/claims/process', json=payload).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_payload_too_large(make_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HTTP_MAX_BODY_BYTES', '32')
    client = make_client()
    response = client.post('/api/claims/process', json={'claim_id': 'C-9', 'description': 'x' * 100})
    assert response.status_code == 413
    assert response.json()['detail']


def test_audit_records_masked_request_and_chain(make_client) -> None:
    client = make_client()
    response = client.post('/api/claims/process',
                           json={'claim_id': 'AUD-1', 'description': '联系人 13812345678'})
    assert response.status_code == 200

    store: AuditStore = client.app.state.audit
    entries = store.recent(10)
    assert entries, '审计表应为空'
    entry = next(item for item in entries if item['resource'] == '/api/claims/process')
    assert entry['action'] == 'POST'
    assert entry['status'] == 200
    assert entry['details']['body']['description'] == '联系人 [手机号]'
    assert '13812345678' not in str(entry['details'])
    ok, bad = store.verify_chain()
    assert ok and bad is None


def test_audit_chain_detects_tampering(make_client, tmp_path) -> None:
    path = tmp_path / 'audit.sqlite'
    store = AuditStore(str(path))
    store.record(request_id='r1', actor='tester', action='POST', resource='/api/x',
                 status=200, latency_ms=1.0, details={'body': 'a'})
    store.record(request_id='r2', actor='tester', action='POST', resource='/api/x',
                 status=200, latency_ms=2.0, details={'body': 'b'})
    assert store.verify_chain() == (True, None)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE audit_events SET details='{\"body\":\"tampered\"}' WHERE request_id='r1'")
        conn.commit()
    ok, bad = store.verify_chain()
    assert not ok and bad == 'r1'
    store.close()


def test_ready_probe(make_client) -> None:
    client = make_client()
    response = client.get('/ready')
    assert response.status_code == 200
    assert response.json() == {'status': 'ready', 'checks': {'graph': True, 'audit': True}}
