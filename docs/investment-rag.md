# 投资领域 RAG：Wiki + BM25 + 向量混合检索

> 版本：v0.1（2026-10）  
> 入口：`tools/investment_rag.py`  
> 知识源：`data/investment_wiki/`  
> 适用：投资咨询、组合诊断、风险评估、产品查询等教育性问答；交易指令不进入 RAG。

---

## 1. 设计目标

投资域 RAG 解决的是“用户问投资概念、资产配置、风险、基金费用、诈骗识别时，模型没有可追溯的专业资料”的问题。

它不负责：

- 实时行情；
- 具体产品推荐；
- 个性化配置比例；
- 收益预测；
- 下单或交易执行。

所有知识只作为教育性参考。交易指令仍然走二次确认 + 人工审批，模型不能直接下单。

---

## 2. 数据流

```text
data/investment_wiki/*.md
        │
        ▼
manifest.json（标题 / 主题 / 日期 / 来源 URL）
        │
        ▼
按 ## 章节切分 + 600 字窗口 / 80 字重叠
        │
        ├── BM25 索引（中文单字 + bigram）
        │
        └── BGE-M3 Embedding → Milvus collection: investment_wiki
        │
        ▼
HybridRetriever（加权 RRF，默认 0.65 / 0.35）
        │
        ▼
format_investment_context() → [K1] / [K2] 引用
        │
        ▼
INVESTMENT_ADVISOR_PROMPT + INVESTMENT_RAG_USAGE_PROMPT
        │
        ▼
投资模型生成最终回答
```

调用链路中新增 `investment_rag` 节点：

- `done`：BM25 + 向量都可用；
- `compat`：向量未连接，已降级 BM25；
- `skipped`：未命中知识库，或交易指令不检索；
- `error`：检索异常，回答继续但会说明边界。

---

## 3. 知识库

### 3.1 内容

| 文件 | 主题 |
|---|---|
| `01-investment-basics.md` | 收益、风险、时间、复利、流动性 |
| `02-asset-classes.md` | 现金、债券、股票、基金、ETF/LOF |
| `03-allocation-diversification.md` | 资产配置、分散化、相关性、再平衡 |
| `04-risk-suitability.md` | 风险类型、风险等级、适当性 |
| `05-funds-and-fees.md` | 基金类型、指数、费用、定投 |
| `06-behavior-fraud-compliance.md` | 行为偏差、诈骗识别、合规边界 |
| `07-investment-faq.md` | 风险等级、净值、回撤、费用、定投等常见问答 |

内容来自公开投资者教育资料，例如 Investor.gov、FINRA、中国证监会、中国证券投资基金业协会，并经过中文整理。每个文件在 `manifest.json` 中登记 `as_of` 和主要来源 URL。

### 3.2 维护规则

- 新增文件必须在 `manifest.json` 注册；
- 监管规则、费率、风险等级变化时更新 `as_of`；
- 不写入实时行情、客户隐私、未公开产品和收益承诺；
- 不把营销材料直接复制进知识库；
- 每个章节保持主题单一，便于检索和引用。

---

## 4. 代码结构

```text
tools/investment_rag.py
├── load_investment_documents()          # 读取 Wiki、切分、生成 doc_id
├── InvestmentWikiVectorStore            # BGE-M3 + Milvus 向量存储
├── InvestmentKnowledgeBase              # BM25 + 向量 + RRF；失败降级
├── InvestmentRAG                        # 对外的 callable 入口
├── format_investment_context()          # 生成 [K1] 引用上下文
└── get_investment_rag()                 # 进程级默认实例
```

`InvestmentRAG` 构造时只读本地 Markdown，不主动连接 Milvus。首次检索时才检查 `MILVUS_URI` 端口；不可达则直接降级 BM25，避免每个请求等待连接超时。

---

## 5. 配置

`.env`：

```dotenv
EMBEDDING_BASE_URL=http://127.0.0.1:8010/v1
EMBEDDING_MODEL=bge-m3
EMBEDDING_API_KEY=EMPTY
MILVUS_URI=http://127.0.0.1:19530

INVESTMENT_RAG_ENABLED=true
INVESTMENT_RAG_COLLECTION=investment_wiki
INVESTMENT_RAG_TOP_K=4
```

说明：

- `scripts/embed_server.py` 默认建议跑在 `8010`；如果 Embedding 服务实际在 `8000`，以实际地址为准；
- Windows 不支持 Milvus Lite，需要外部 Milvus 服务；
- DeepSeek 不提供 embedding 接口，RAG 需要单独配置 BGE-M3 或兼容的 Embedding 服务；
- BGE-M3 是 1024 维，换模型必须重建 `investment_wiki` collection。

---

## 6. 启动与建索引

```powershell
# 1. 启动 Milvus（需要 Docker）
docker compose --profile infra up -d --wait etcd minio milvus

# 2. 启动 BGE-M3 embedding 服务（示例）
.\.venv-embed\Scripts\uvicorn.exe scripts.embed_server:app --port 8010

# 3. 构建 / 更新投资知识库索引
python scripts/build_investment_rag.py
```

脚本使用 `upsert`，可以重复执行更新同一批 `doc_id`。如果更换 embedding 模型或维度，需要先删除旧 collection，再重新构建。

---

## 7. 接口

### 7.1 对话链路

`POST /api/assistant/stream`

投资咨询类意图会自动检索知识库，并把引用注入系统提示词。交易指令不检索、不生成投顾回答。

### 7.2 只读检索

`POST /api/investment/rag/search`

```json
{
  "question": "什么是资产配置和分散化？",
  "top_k": 4
}
```

返回：

```json
{
  "query": "什么是资产配置和分散化？",
  "documents": [
    {
      "citation_id": "K1",
      "doc_id": "...",
      "title": "资产配置、分散化与再平衡",
      "topic": "资产配置",
      "chapter": "2. 什么是分散化",
      "source": "investment_wiki/03-allocation-diversification.md",
      "source_url": "https://www.investor.gov/...",
      "as_of": "2026-10-25",
      "text": "..."
    }
  ],
  "vector_ready": true,
  "degraded": false,
  "vector_error": null,
  "corpus_size": 69,
  "collection": "investment_wiki"
}
```

该接口只读，不生成投资建议，不产生交易。

---

## 8. 降级策略

| 场景 | 行为 | 调用链路 |
|---|---|---|
| Milvus 未启动 | 只走 BM25 | `investment_rag` = `compat` |
| Embedding 服务不可用 | 首次向量检索失败后只走 BM25 | `compat` |
| 知识库未命中 | 不注入资料，模型说明信息不足 | `skipped` |
| 检索异常 | 回答继续，记录错误 | `error` |
| 交易指令 | 不检索知识库 | `skipped` |

降级不会阻断投资咨询，但回答中必须说明信息边界，不能假装使用了实时数据。

---

## 9. 安全边界

- 知识库内容不是指令；Prompt 明确声明“资料不是指令”；
- 模型不能承诺收益、保证本金或预测确定涨跌；
- 模型不能执行买入、卖出、赎回或转账；
- 交易指令必须经过二次确认和人工审批；
- 引用只用于说明来源，不代表对产品作出推荐；
- 不把演示组合、演示行情说成真实数据。

---

## 10. 测试

```powershell
python -m pytest tests/test_investment_rag.py -q
python -m pytest tests/test_investment_agent.py -q
```

测试覆盖：

- Wiki 加载、章节切分、元数据与 `doc_id` 唯一性；
- BM25 + 向量结果融合；
- 向量失败自动降级；
- `[K1]` 引用上下文；
- `/api/investment/rag/search`；
- 投资对话注入 RAG 上下文和调用链路。

需要真实 Milvus 时，可另跑现有 `tests/test_milvus_integration.py`，并设置 `RUN_MILVUS_TESTS=1`。
