"""本地 BGE-M3 嵌入与 BGE-Reranker 精排服务。

以 OpenAI 兼容的 ``/v1/embeddings`` 供主项目调用，并提供 ``/v1/rerank``。
运行环境与主项目隔离（主项目 Python 3.15 暂无 torch wheel）：

    .venv-embed/bin/uvicorn scripts.embed_server:app --port 8010

reranker 模型默认从 ``models/bge-reranker-base`` 读取；不存在时只在调用
``/v1/rerank`` 时返回 503，不影响 embedding。主项目会自动降级为词项重排。
"""
from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import os
from pathlib import Path
import threading


def _load_dotenv(path: str = '.env') -> None:
    """读取项目根目录 .env；已存在的进程环境变量优先。"""
    env_file = Path(path)
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key.startswith('export '):
            key = key[7:].strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        os.environ[key] = value


_load_dotenv()

# 本地权重不需要联网；未设置时 transformers 会尝试连接 huggingface.co，
# 在无法访问该站点的网络下会卡住数分钟。
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import numpy as np  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sentence_transformers import CrossEncoder, SentenceTransformer  # noqa: E402

MODEL_PATH = Path(os.getenv('BGE_M3_MODEL_PATH', 'models/bge-m3'))
RERANKER_MODEL_PATH = Path(os.getenv('BGE_RERANKER_MODEL_PATH', 'models/bge-reranker-base'))
_model: SentenceTransformer | None = None
_reranker: CrossEncoder | None = None
_load_lock = threading.Lock()
_reranker_lock = threading.Lock()
_encode_lock = threading.Lock()
_rerank_lock = threading.Lock()


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _load_lock:
            if _model is None:
                _model = SentenceTransformer(str(MODEL_PATH), device='cpu')
                _model.max_seq_length = 8192
    return _model


def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                if not RERANKER_MODEL_PATH.exists():
                    raise RuntimeError(f'reranker 模型不存在：{RERANKER_MODEL_PATH}')
                _reranker = CrossEncoder(str(RERANKER_MODEL_PATH), device='cpu', max_length=512)
    return _reranker


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = 'bge-m3'
    encoding_format: str | None = None
    dimensions: int | None = None


class RerankRequest(BaseModel):
    model: str = 'bge-reranker-base'
    query: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1)
    top_n: int | None = Field(default=None, ge=1)


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_model()
    yield


app = FastAPI(title='BGE-M3 embedding / BGE-Reranker service', lifespan=lifespan)


@app.get('/health')
def health() -> dict[str, object]:
    return {
        'status': 'ok',
        'model': str(MODEL_PATH),
        'loaded': _model is not None,
        'reranker_model': str(RERANKER_MODEL_PATH),
        'reranker_loaded': _reranker is not None,
        'reranker_available': RERANKER_MODEL_PATH.exists(),
    }


@app.post('/v1/embeddings')
def embeddings(request: EmbeddingRequest) -> dict[str, object]:
    texts = [request.input] if isinstance(request.input, str) else request.input
    if not texts or not all(isinstance(text, str) and text for text in texts):
        raise ValueError('input 必须是非空字符串或字符串列表')
    model = get_model()
    with _encode_lock:
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=8,
                               convert_to_numpy=True)
    data = []
    for index, vector in enumerate(vectors):
        values: object = vector.tolist()
        if request.encoding_format == 'base64':
            values = base64.b64encode(np.asarray(vector, dtype=np.float32).tobytes()).decode()
        data.append({'object': 'embedding', 'index': index, 'embedding': values})
    tokens = sum(len(model.tokenizer(text)['input_ids']) for text in texts)
    return {'object': 'list', 'model': request.model, 'data': data,
            'usage': {'prompt_tokens': tokens, 'total_tokens': tokens}}


@app.post('/v1/rerank')
def rerank(request: RerankRequest) -> dict[str, object]:
    if any(not text or not text.strip() for text in request.documents):
        raise HTTPException(status_code=422, detail='documents 必须全部是非空文本')
    documents = request.documents
    try:
        model = get_reranker()
    except Exception as exc:  # noqa: BLE001 - 模型缺失/损坏都应让主项目降级
        raise HTTPException(status_code=503, detail=f'reranker 不可用：{exc}') from exc
    with _rerank_lock:
        scores = model.predict(
            [(request.query, text) for text in documents],
            batch_size=8,
            convert_to_numpy=True,
        )
    scores = np.asarray(scores).reshape(-1)
    top_n = min(request.top_n or len(documents), len(documents))
    order = np.argsort(-scores)[:top_n]
    return {
        'model': request.model,
        'results': [
            {'index': int(index), 'relevance_score': float(scores[int(index)])}
            for index in order
        ],
    }
