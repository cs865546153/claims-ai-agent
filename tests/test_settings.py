"""配置优先级：应用向量库地址覆盖 pymilvus 的 MILVUS_URI。"""
from settings import Settings


def test_vector_store_uri_overrides_milvus_uri(monkeypatch):
    monkeypatch.setenv('VECTOR_STORE_URI', './.data/test.db')
    monkeypatch.setenv('MILVUS_URI', 'http://127.0.0.1:19530')
    cfg = Settings(_env_file=None)
    assert cfg.vector_store_uri == './.data/test.db'
    assert cfg.milvus_uri == './.data/test.db'


def test_vector_store_uri_falls_back_to_milvus_uri(monkeypatch):
    monkeypatch.delenv('VECTOR_STORE_URI', raising=False)
    monkeypatch.setenv('MILVUS_URI', 'http://milvus:19530')
    cfg = Settings(_env_file=None)
    assert cfg.vector_store_uri is None
    assert cfg.milvus_uri == 'http://milvus:19530'


def test_rerank_base_url_is_normalized(monkeypatch):
    monkeypatch.setenv('RERANK_BASE_URL', 'http://127.0.0.1:8010/v1/')
    cfg = Settings(_env_file=None)
    assert cfg.rerank_base_url == 'http://127.0.0.1:8010/v1'
    assert cfg.rerank_enabled is True
    assert cfg.knowledge_base_dir == 'data/knowledge_base'
