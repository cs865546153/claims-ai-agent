"""部署辅助：从 Hugging Face 下载 BGE-M3 与 BGE-Reranker 权重。

只在服务器容器内运行，不进入应用运行链路：

    docker run --rm -v /opt/claims-ai-agent/models:/models \
      claims-model-downloader python scripts/download_models.py
"""
from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(os.getenv('MODEL_DIR', '/models'))

snapshot_download(
    repo_id='BAAI/bge-m3',
    local_dir=ROOT / 'bge-m3',
    allow_patterns=[
        '*.json',
        '*.txt',
        '*.model',
        '*.pt',
        'pytorch_model.bin',
        '1_Pooling/*',
        'modules.json',
    ],
    ignore_patterns=['onnx/*', 'imgs/*', '*.jpg', '*.webp', '*.DS_Store'],
)

snapshot_download(
    repo_id='BAAI/bge-reranker-base',
    local_dir=ROOT / 'bge-reranker-base',
    allow_patterns=['*.json', '*.txt', '*.model', 'model.safetensors'],
    ignore_patterns=['onnx/*', 'pytorch_model.bin'],
)

print('models downloaded to', ROOT)
