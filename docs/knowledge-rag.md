# 通用知识库 RAG：多路召回 + RRF + Rerank + 引用回答

> 入口：`tools/knowledge_rag.py`  
> 知识源：`data/knowledge_base/`（通用）+ `data/investment_wiki/`（投资）  
> 接口：`POST /api/rag/search`、`POST /api/rag/answer`、`GET /api/rag/domains`

> **当前状态**：本仓库已下载 `models/bge-reranker-base`，`scripts/embed_server.py` 的
> `/health` 返回 `reranker_available=true`，真实检索返回 `reranked=true`、
> `rerank_fallback=false`、`rerank_error=null`。模型缺失或服务不可用时仍会自动降级为
> 词项重排，不影响检索主链路。

---

## 1. 先回答一个常见问题：BM25 做 rerank 好吗？

**BM25 不是 reranker，它是召回/词法打分。**  
BM25 只看 query 与文档的词项统计，不理解 query 和文档之间的 token 级交互；它适合在第一阶段把关键词、产品名、编号、专有名词召回出来。

**Rerank 应该用 Cross-Encoder，例如 BGE-Reranker。**  
Cross-Encoder 把 `query + document` 拼成一个输入，让模型直接判断两者的相关性，能过滤“向量相似但不回答问题”的假阳性。代价是慢，所以只对 RRF 融合后的少量候选做精排。

推荐链路：

```text
BM25 / BGE-M3 / 元数据召回
        ↓
加权 RRF 融合（几十条候选）
        ↓
BGE-Reranker 精排（Cross-Encoder）
        ↓
Top-K + 引用
        ↓
LLM 回答 + citation_ids 校验
```

BM25 可以作为 rerank 的一个特征，但不应该替代 Cross-Encoder。

---

## 2. 总体数据流

```text
data/knowledge_base/**/*.md|pdf|docx|html
        │
        ▼
章节切分 / 600 字窗口 / 80 字重叠 / 可追溯 doc_id
        │
        ├── BGE-M3 → Milvus（dense 召回）
        ├── BM25（词法召回）
        └── 标题/章节/主题/来源（元数据召回）
        │
        ▼
加权 RRF 融合
        │
        ▼
BGE-Reranker（Cross-Encoder）→ Top-K
        │
        ├── POST /api/rag/search：返回片段 + 引用 + 召回诊断
        └── POST /api/rag/answer：LLM 生成 + citation_ids 校验
```

---

## 3. 多路召回

`MultiRouteRetriever` 支持任意多路，每路只负责返回候选，不负责融合：

| 路 | 实现 | 擅长 |
|---|---|---|
| `dense` | BGE-M3 + Milvus | 语义相似、跨语言、长文本 |
| `bm25` | `rank_bm25.BM25Okapi` + 中文单字/双字 | 精确词项、产品名、编号、专有名词 |
| `metadata` | 标题、章节、主题、来源匹配 | 用户直接问某篇文档/某一章 |

默认权重：

```text
dense 0.55 / bm25 0.30 / metadata 0.15
```

融合使用加权 RRF：

```text
score(doc) = Σ route_weight / (60 + rank_in_route)
```

RRF 只使用排名，不直接相加不同量纲的向量距离、BM25 分数和元数据打分。候选倍数由
`RAG_CANDIDATE_MULTIPLIER` 控制，默认 4。

---

## 4. Rerank

`tools/rerank.py` 提供两级实现：

1. **`HttpBgeReranker`**：调用 `scripts/embed_server.py` 的 `/v1/rerank`，由
   `sentence-transformers.CrossEncoder` 加载 BGE-Reranker；
2. **`LexicalReranker`**：模型服务不可用时的兜底，按词项覆盖、短语命中、
   元数据命中和原排名先验重新排序。

`FallbackReranker` 先尝试 BGE-Reranker；失败后自动降级，不会阻断检索。
失败后默认冷却 60 秒（`RERANK_RETRY_COOLDOWN`），期间直接走词项重排，冷却结束
自动重试，因此下载模型或重启服务后不需要重启主项目。`retrieval.rerank_error`
会记录降级原因，`retrieval.rerank_fallback` 标记是否走了兜底。

### 4.1 安装 reranker 模型（当前已安装）

当前仓库已将 `BAAI/bge-reranker-base` 下载到 `models/bge-reranker-base`，只保留
`model.safetensors` 及 tokenizer/config 文件，体积约 1.1GB。以下命令用于新环境安装
或升级模型。

默认路径 `models/bge-reranker-base`，safetensors 约 1.1GB。使用 ModelScope
（仓库同时提供 `pytorch_model.bin` 和 `model.onnx`，忽略它们可少下约 2.2GB）：

```bash
.venv-py315/bin/python -c "from modelscope import snapshot_download; \
snapshot_download('BAAI/bge-reranker-base', local_dir='models/bge-reranker-base', \
ignore_file_pattern=['pytorch_model.bin', '*.onnx'])"
```

或 HuggingFace：

```bash
huggingface-cli download BAAI/bge-reranker-base --local-dir models/bge-reranker-base
```

需要更强多语言效果可换 `BAAI/bge-reranker-v2-m3`，然后设置：

```dotenv
RERANK_MODEL=bge-reranker-v2-m3
BGE_RERANKER_MODEL_PATH=models/bge-reranker-v2-m3
```

### 4.2 启动服务

```bash
.venv-embed/bin/uvicorn scripts.embed_server:app --host 127.0.0.1 --port 8010
```

健康检查：

```bash
curl -s http://127.0.0.1:8010/health
# {"status":"ok","model":"models/bge-m3","loaded":true,
#  "reranker_model":"models/bge-reranker-base",
#  "reranker_loaded":true,"reranker_available":true}
```

`reranker_loaded` 在首次调用 `/v1/rerank` 后才变为 `true`。当前已用以下请求验证：
相关文档得分约 `0.996`，不相关文档约 `0.00004`。

```bash
curl -s http://127.0.0.1:8010/v1/rerank \
  -H 'Content-Type: application/json' \
  -d '{"query":"基金风险","documents":["基金有市场风险","今天天气很好"]}'
```

模型不存在时 `/v1/rerank` 返回 503，主项目自动使用词项重排；embedding 不受影响。

---

## 5. 知识库目录

通用知识库默认 `data/knowledge_base/`，支持：

- Markdown：按 `##` 切章节；
- TXT / PDF / DOCX / HTML；
- 根目录 `README.md` 不进入索引。

首次检索时按 domain 懒加载。新增或修改文档后需要重启应用，让 BM25/元数据索引
重新加载；如需 dense 向量召回也覆盖新文档，再重建向量索引：

```bash
python scripts/build_knowledge_rag.py --domain general
python scripts/build_knowledge_rag.py --domain investment
```

投资 Wiki 使用 `data/investment_wiki/manifest.json`，集合名 `investment_wiki`。
通用知识库集合名 `knowledge_general`。

---

## 6. 配置

```dotenv
# 通用知识库
KNOWLEDGE_RAG_ENABLED=true
KNOWLEDGE_BASE_DIR=data/knowledge_base
KNOWLEDGE_RAG_COLLECTION=knowledge_general
KNOWLEDGE_RAG_TOP_K=5

# 多路召回 + rerank
RAG_CANDIDATE_MULTIPLIER=4
RERANK_ENABLED=true
RERANK_BASE_URL=http://127.0.0.1:8010/v1
RERANK_MODEL=bge-reranker-base
RERANK_TIMEOUT=10.0
RERANK_TOP_N=20
RERANK_RETRY_COOLDOWN=60
# embed_server 读取；主项目不读取
BGE_RERANKER_MODEL_PATH=models/bge-reranker-base
```

`RERANK_BASE_URL` 指向 `scripts/embed_server.py`；`RERANK_MODEL` 只用于请求标识，
模型实际路径由服务端 `BGE_RERANKER_MODEL_PATH` 决定。

---

## 7. 接口

### 7.1 列出知识库

```http
GET /api/rag/domains
```

返回已配置的 `general` / `investment`，不会主动连接 Milvus。

### 7.2 检索

```http
POST /api/rag/search
```

```json
{
  "domain": "general",
  "question": "多路召回和 rerank 是什么？",
  "top_k": 5,
  "filters": {}
}
```

返回：

```json
{
  "query": "多路召回和 rerank 是什么？",
  "domain": "general",
  "documents": [
    {
      "citation_id": "K1",
      "doc_id": "...",
      "domain": "general",
      "title": "知识库 RAG 链路",
      "topic": "通用知识",
      "chapter": "多路召回",
      "source": "rag-pipeline.md",
      "source_url": "",
      "as_of": "",
      "text": "..."
    }
  ],
  "vector_ready": true,
  "degraded": false,
  "vector_error": null,
  "corpus_size": 4,
  "collection": "knowledge_general",
  "retrieval": {
    "rrf_k": 60,
    "weights": {"dense": 0.55, "bm25": 0.3, "metadata": 0.15},
    "route_hits": {"dense": 4, "bm25": 4, "metadata": 4},
    "fused_count": 4,
    "reranked": true,
    "rerank_fallback": false,
    "rerank_error": null
  }
}
```

### 7.3 回答

```http
POST /api/rag/answer
```

请求体同上。内部执行检索 + LLM，返回 `answer`、`documents`、`citation_check`。
`citation_ids` 必须属于本轮检索结果；没有有效引用时返回 502，并提示转人工核实。

```json
{
  "query": "多路召回和 rerank 是什么？",
  "domain": "general",
  "answer": "...",
  "documents": [],
  "requires_manual_review": false,
  "citation_check": "citation_ids 已校验；语义支持度需人工或黄金数据集评估"
}
```

---

## 8. 降级策略

| 场景 | 行为 |
|---|---|
| Milvus / embedding 不可用 | dense 路为空，继续 BM25 + 元数据；`degraded=true` |
| BGE-Reranker 未下载/服务不可用 | 词项重排兜底；`rerank_fallback=true`（当前模型已启用，正常为 `false`） |
| 知识库目录不存在/为空 | 接口返回 503，不影响其他 domain |
| 未知 domain | 接口返回 404 |
| LLM 引用越界/无引用 | 返回 502，转人工核实 |

---

## 9. 测试

```bash
python -m pytest tests/test_knowledge_rag.py tests/test_rerank.py -q
```

覆盖：

- Markdown 章节加载、README 跳过、doc_id 唯一；
- 多路 RRF 融合与去重；
- 词项 rerank；
- 向量失败降级；
- 回答引用校验；
- `/api/rag/search`、`/api/rag/answer`、`/api/rag/domains`；
- HTTP rerank 客户端与 fallback。

完整测试：

```bash
python -m pytest -q
```
