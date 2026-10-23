"""本地 BGE-M3 嵌入服务：以 OpenAI 兼容的 /v1/embeddings 供主项目调用。

运行环境与主项目隔离（主项目 Python 3.15 暂无 torch wheel）：
    .venv-embed/bin/uvicorn scripts.embed_server:app --port 8010
"""
from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import os
from pathlib import Path
import threading

# 本地权重不需要联网；未设置时 transformers 会尝试连接 huggingface.co，
# 在无法访问该站点的网络下会卡住数分钟。
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_PATH = Path(os.getenv('BGE_M3_MODEL_PATH', 'models/bge-m3'))
_model: SentenceTransformer | None = None
_load_lock = threading.Lock()
_encode_lock = threading.Lock()


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _load_lock:
            if _model is None:
                _model = SentenceTransformer(str(MODEL_PATH), device='cpu')
                _model.max_seq_length = 8192
    return _model


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = 'bge-m3'
    encoding_format: str | None = None
    dimensions: int | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_model()
    yield


app = FastAPI(title='BGE-M3 embedding service', lifespan=lifespan)


@app.get('/health')
def health() -> dict[str, object]:
    return {'status': 'ok', 'model': str(MODEL_PATH), 'loaded': _model is not None}


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
